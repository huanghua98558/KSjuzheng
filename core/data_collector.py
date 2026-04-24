# -*- coding: utf-8 -*-
"""Internal data collector — our 13 matrix accounts' daily metrics.

Pulls per-account data via their OWN kuaishou_uid + cookie:
  - profile/feed (list recent works + stats)
  - (optional future) cp.kuaishou.com dashboard APIs

Writes to:
  - daily_account_metrics  (date + uid → fans, plays, likes, level)
  - work_metrics           (date + photo_id → play/like/comment deltas)

Runs nightly 22:00 to feed the AI decision loop.
"""
from __future__ import annotations

import json
import logging
import time
from datetime import date, datetime
from typing import Any

from core.drama_collector import DramaCollector
from core.hot_rankings import _as_int

log = logging.getLogger(__name__)


class DataCollector:
    """Nightly internal-metrics harvester for the matrix."""

    def __init__(self, db_manager, cookie_manager):
        self.db = db_manager
        self.cm = cookie_manager
        self.collector = DramaCollector(db_manager, cookie_manager)

    def snapshot_all_accounts(
        self,
        browser_account_pk: int | None = None,
        pages_per_account: int = 2,
    ) -> dict[str, Any]:
        """For every logged_in account, pull its own profile/feed + metrics.

        ``browser_account_pk`` is the cookie identity used to call profile/feed;
        if None, uses each account's own cookie (recommended — most accurate
        since authenticated == better data visibility).
        """
        accounts = self.db.get_logged_in_accounts()
        today = date.today().isoformat()

        stats = {
            "accounts_processed": 0,
            "accounts_failed": 0,
            "total_works_captured": 0,
            "per_account": {},
        }

        for acct in accounts:
            uid = acct.get("kuaishou_uid")
            name = acct.get("account_name", "")
            acct_pk = acct["id"]
            if not uid:
                continue
            use_pk = browser_account_pk or acct_pk

            try:
                photos = self.collector.fetch_profile_feed(
                    uid, use_pk, max_pages=pages_per_account,
                )
            except Exception as exc:
                log.error("[DataCollector] fetch failed for %s (%s): %s",
                          name, uid, exc)
                stats["accounts_failed"] += 1
                stats["per_account"][uid] = {"error": str(exc)}
                continue

            # Aggregate for daily_account_metrics
            total_plays = sum(_as_int(p.get("view_count")) for p in photos)
            total_likes = sum(_as_int(p.get("like_count")) for p in photos)
            works_visible = len(photos)

            # Yesterday's totals for delta
            prev_row = self.db.conn.execute(
                """SELECT total_plays, total_likes
                   FROM daily_account_metrics
                   WHERE kuaishou_uid = ? AND metric_date < ?
                   ORDER BY metric_date DESC LIMIT 1""",
                (uid, today),
            ).fetchone()
            plays_delta = total_plays - (prev_row[0] if prev_row and prev_row[0] else 0)
            # fans = not in profile/feed; best we can do without CP login API

            try:
                self.db.conn.execute(
                    """INSERT INTO daily_account_metrics
                         (metric_date, kuaishou_uid, account_name,
                          fans, fans_delta, total_plays, plays_delta,
                          total_likes, captured_at, raw_json)
                       VALUES (?, ?, ?, NULL, NULL, ?, ?, ?,
                               datetime('now','localtime'), ?)
                       ON CONFLICT(metric_date, kuaishou_uid) DO UPDATE SET
                         total_plays = excluded.total_plays,
                         plays_delta = excluded.plays_delta,
                         total_likes = excluded.total_likes,
                         captured_at = excluded.captured_at""",
                    (today, uid, name,
                     total_plays, plays_delta, total_likes,
                     json.dumps({
                         "works_visible": works_visible,
                         "first_photo": photos[0]["photo_encrypt_id"] if photos else "",
                     }, ensure_ascii=False)),
                )
            except Exception as exc:
                log.error("[DataCollector] daily_account_metrics save %s: %s", uid, exc)

            # Per-work metrics
            saved_works = 0
            total_comments = 0
            total_shares = 0
            for p in photos:
                pid = p.get("photo_encrypt_id", "")
                if not pid:
                    continue
                v = _as_int(p.get("view_count"))
                lk = _as_int(p.get("like_count"))
                cm = _as_int(p.get("comment_count"))
                sh = _as_int(p.get("share_count"))
                fv = _as_int(p.get("favorite_count"))
                total_comments += cm
                total_shares += sh
                try:
                    # 老表: work_metrics (保留向后兼容)
                    self.db.conn.execute(
                        """INSERT INTO work_metrics
                             (metric_date, photo_id, kuaishou_uid,
                              drama_name, plays, likes, comments,
                              captured_at)
                           VALUES (?, ?, ?, ?, ?, ?, ?, datetime('now','localtime'))
                           ON CONFLICT(metric_date, photo_id) DO UPDATE SET
                             plays = excluded.plays,
                             likes = excluded.likes,
                             comments = excluded.comments,
                             captured_at = excluded.captured_at""",
                        (today, pid, uid,
                         (p.get("caption") or "")[:100],
                         v, lk, cm),
                    )
                    # 新表: content_performance_daily (规划标准, AI 用)
                    self.db.conn.execute(
                        """INSERT INTO content_performance_daily
                             (photo_id, account_id, snapshot_date,
                              view_count, like_count, comment_count,
                              share_count, favorite_count,
                              status)
                           VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'active')
                           ON CONFLICT(photo_id, snapshot_date) DO UPDATE SET
                             view_count = excluded.view_count,
                             like_count = excluded.like_count,
                             comment_count = excluded.comment_count,
                             share_count = excluded.share_count,
                             favorite_count = excluded.favorite_count""",
                        (pid, str(uid), today, v, lk, cm, sh, fv),
                    )
                    saved_works += 1
                except Exception as exc:
                    log.error("[DataCollector] work_metrics save %s: %s", pid, exc)

            # Compute health_score + write account_health_snapshots.
            # Rough heuristic (0-100):
            #   base 60 if logged in
            #   + up to 20 for works_visible (saturates at 10)
            #   + up to 15 for plays_delta growth (log scale)
            #   + up to 5 for comment/like engagement
            import math as _m
            health_score = 60.0 if acct.get("login_status") == "logged_in" else 20.0
            health_score += min(works_visible, 10) * 2.0
            if plays_delta > 0:
                health_score += min(_m.log10(plays_delta + 1) * 3.0, 15.0)
            if total_plays and total_likes:
                engage = (total_likes / max(total_plays, 1)) * 100
                health_score += min(engage, 5.0)
            health_score = round(min(health_score, 100.0), 2)

            login_status = acct.get("login_status", "unknown")
            publish_status = "active" if works_visible > 0 else "idle"
            risk_score = round(max(0, 100 - health_score) / 2.0, 2)

            try:
                self.db.conn.execute(
                    """INSERT INTO account_health_snapshots
                         (account_id, snapshot_date, login_status, publish_status,
                          last_publish_success, publish_fail_count_1d, publish_fail_count_7d,
                          channel_a_fail_rate, channel_b_fail_rate,
                          risk_score, health_score, notes, created_at)
                       VALUES (?, ?, ?, ?, ?, 0, 0, 0, 0, ?, ?, ?,
                               datetime('now','localtime'))
                       ON CONFLICT(account_id, snapshot_date) DO UPDATE SET
                         login_status = excluded.login_status,
                         publish_status = excluded.publish_status,
                         risk_score = excluded.risk_score,
                         health_score = excluded.health_score,
                         notes = excluded.notes""",
                    (str(uid), today, login_status, publish_status,
                     1 if works_visible > 0 else 0,
                     risk_score, health_score,
                     f"works={works_visible} plays={total_plays} likes={total_likes}"),
                )
            except Exception as exc:
                log.error("[DataCollector] health snapshot %s: %s", uid, exc)

            # 新表: account_performance_daily (规划标准, AI 用)
            # 从 publish_results 查当日发布数 + 成功数
            try:
                pub_row = self.db.conn.execute(
                    """SELECT COUNT(*) AS total,
                              SUM(CASE WHEN publish_status='success' THEN 1 ELSE 0 END) AS ok
                       FROM publish_results
                       WHERE account_id=? AND DATE(created_at)=?""",
                    (str(uid), today),
                ).fetchone()
                publish_count = pub_row[0] if pub_row else 0
                success_count = pub_row[1] if pub_row and pub_row[1] else 0
            except Exception:
                publish_count = success_count = 0

            try:
                self.db.conn.execute(
                    """INSERT INTO account_performance_daily
                         (account_id, snapshot_date,
                          publish_count, success_publish_count,
                          total_views, total_likes, total_comments, total_shares,
                          followers_delta, revenue_amount, avg_cpm, health_score)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, 0, 0, 0, ?)
                       ON CONFLICT(account_id, snapshot_date) DO UPDATE SET
                         publish_count = excluded.publish_count,
                         success_publish_count = excluded.success_publish_count,
                         total_views = excluded.total_views,
                         total_likes = excluded.total_likes,
                         total_comments = excluded.total_comments,
                         total_shares = excluded.total_shares,
                         health_score = excluded.health_score""",
                    (str(uid), today,
                     publish_count, success_count,
                     total_plays, total_likes, total_comments, total_shares,
                     health_score),
                )
            except Exception as exc:
                log.error("[DataCollector] account_performance_daily %s: %s", uid, exc)

            self.db.conn.commit()
            stats["accounts_processed"] += 1
            stats["total_works_captured"] += saved_works
            stats["per_account"][uid] = {
                "name": name,
                "works": works_visible,
                "total_plays": total_plays,
                "plays_delta": plays_delta,
                "total_likes": total_likes,
                "saved_works": saved_works,
                "health_score": health_score,
            }
            log.info("[DataCollector] %s: works=%d plays=%d (Δ%+d) likes=%d health=%.1f",
                     name, works_visible, total_plays, plays_delta, total_likes, health_score)
            time.sleep(0.5)

        return stats
