# -*- coding: utf-8 -*-
"""Hot drama rankings — dual-source.

Two sources flow into the same drama_hot_rankings table (differentiated
by ``platform`` column):

  1. EXTERNAL — Kuaishou-platform-wide search results (visionSearchPhoto
                GraphQL). Per keyword ranking reflects what Kuaishou is
                currently pushing to the public.  platform='kuaishou_search'

  2. INTERNAL — Our own 13 matrix accounts' published works ranked by
                their real performance. Gives us a feedback loop:
                "what did we publish → how did it perform".
                platform='internal_matrix'

Both run on snapshot semantics: (date, hour, keyword, photo_id) UNIQUE
so re-runs don't duplicate but later hours build a time series.
"""
from __future__ import annotations

import json
import logging
import math
import time
from datetime import date, datetime
from typing import Any

from core.drama_collector import DramaCollector

log = logging.getLogger(__name__)


def _as_int(v) -> int:
    """Coerce any numeric-ish value (int / str / None) to int."""
    try:
        if v is None: return 0
        if isinstance(v, bool): return int(v)
        if isinstance(v, int): return v
        if isinstance(v, float): return int(v)
        # Strings may be "1234", "1.2万", or null
        s = str(v).strip()
        if not s: return 0
        # Handle Chinese 万/千/亿 suffix just in case
        if s.endswith("万"):
            return int(float(s[:-1]) * 10000)
        if s.endswith("千"):
            return int(float(s[:-1]) * 1000)
        if s.endswith("亿"):
            return int(float(s[:-1]) * 100_000_000)
        return int(float(s))
    except Exception:
        return 0


def compute_hot_score(view, like, comment, duration_sec=60) -> float:
    """Composite score — emphasizes engagement over raw views.

    Formula:
        score = log10(views+1)*0.5 + log10(likes+1)*0.3 + log10(comments+1)*0.2
              + duration_bonus  (dramas >= 60s get +0.1)
    Robust to str/int mix that Kuaishou sometimes returns.
    """
    v = math.log10(_as_int(view) + 1) * 0.5
    l = math.log10(_as_int(like) + 1) * 0.3
    c = math.log10(_as_int(comment) + 1) * 0.2
    try:
        dur_bonus = 0.1 if float(duration_sec) >= 60 else 0
    except Exception:
        dur_bonus = 0
    return round(v + l + c + dur_bonus, 4)


class HotRankings:
    """Hot-rankings aggregator."""

    def __init__(self, db_manager, cookie_manager):
        self.db = db_manager
        self.cm = cookie_manager
        self.collector = DramaCollector(db_manager, cookie_manager)

    # ==================================================================
    # External — Kuaishou keyword-based hot board
    # ==================================================================

    def refresh_external_kuaishou(
        self,
        browser_account_pk: int,
        keywords: list[str] | None = None,
        pages_per_keyword: int = 2,
        top_n: int = 30,
    ) -> dict[str, Any]:
        """Search each keyword → rank feeds by hot_score → save top N."""
        if keywords is None:
            rows = self.db.conn.execute(
                """SELECT keyword FROM keyword_watch_list
                   WHERE is_active = 1 ORDER BY priority DESC, keyword ASC"""
            ).fetchall()
            keywords = [r[0] for r in rows]
        if not keywords:
            log.warning("[HotRankings] no keywords to refresh")
            return {}

        today = date.today().isoformat()
        hour = datetime.now().hour
        stats = {}

        for kw in keywords:
            try:
                results = self.collector.search_by_keyword(
                    kw, browser_account_pk, max_pages=pages_per_keyword,
                )
            except Exception as exc:
                log.error("[HotRankings] search '%s' failed: %s", kw, exc)
                stats[kw] = {"error": str(exc)}
                continue

            # Score + rank
            scored = []
            for r in results:
                s = compute_hot_score(
                    view=r.get("view_count", 0),
                    like=r.get("like_count", 0),
                    comment=r.get("comment_count", 0),
                    duration_sec=r.get("duration_sec", 0),
                )
                scored.append((s, r))
            scored.sort(key=lambda x: -x[0])
            top = scored[:top_n]

            saved = 0
            for rank, (score, r) in enumerate(top, 1):
                try:
                    self.db.conn.execute(
                        """INSERT INTO drama_hot_rankings
                             (snapshot_date, snapshot_hour, platform, keyword,
                              rank, photo_encrypt_id, author_id, author_name,
                              caption, view_count, like_count, comment_count,
                              duration_sec, hot_score, tags)
                           VALUES (?, ?, 'kuaishou_search', ?, ?, ?, ?, ?, ?,
                                   ?, ?, ?, ?, ?, ?)
                           ON CONFLICT(snapshot_date, snapshot_hour, keyword, photo_encrypt_id)
                           DO UPDATE SET
                             rank = excluded.rank,
                             view_count = excluded.view_count,
                             like_count = excluded.like_count,
                             comment_count = excluded.comment_count,
                             hot_score = excluded.hot_score""",
                        (
                            today, hour, kw, rank,
                            r.get("photo_encrypt_id"),
                            r.get("author_id"),
                            r.get("author_name"),
                            (r.get("caption") or "")[:500],
                            _as_int(r.get("view_count")),
                            _as_int(r.get("like_count")),
                            _as_int(r.get("comment_count")),
                            float(r.get("duration_sec") or 0),
                            score,
                            json.dumps(r.get("tags", []), ensure_ascii=False),
                        ),
                    )
                    saved += 1
                except Exception as exc:
                    log.error("[HotRankings] save %s/%s rank=%d: %s",
                              kw, r.get("photo_encrypt_id"), rank, exc)

            # Update keyword last_used_at
            self.db.conn.execute(
                """UPDATE keyword_watch_list
                   SET last_used_at = datetime('now','localtime')
                   WHERE keyword = ?""", (kw,),
            )
            self.db.conn.commit()
            stats[kw] = {"fetched": len(results), "saved_top_n": saved}
            log.info("[HotRankings] kw='%s' fetched=%d saved=%d",
                     kw, len(results), saved)
            time.sleep(1.0)  # polite pacing

        return stats

    # ==================================================================
    # Internal — our own matrix's performance
    # ==================================================================

    def refresh_internal_matrix(
        self,
        browser_account_pk: int,
        max_accounts: int | None = None,
        pages_per_account: int = 2,
        top_n: int = 50,
    ) -> dict[str, Any]:
        """For each of our logged-in accounts, pull profile/feed → rank."""
        accounts = self.db.get_logged_in_accounts()
        if max_accounts:
            accounts = accounts[:max_accounts]

        today = date.today().isoformat()
        hour = datetime.now().hour
        all_results = []

        for acct in accounts:
            kuaishou_uid = acct.get("kuaishou_uid")
            account_name = acct.get("account_name")
            if not kuaishou_uid:
                continue
            try:
                photos = self.collector.fetch_profile_feed(
                    kuaishou_uid, browser_account_pk,
                    max_pages=pages_per_account,
                )
            except Exception as exc:
                log.error("[HotRankings] internal fetch uid=%s: %s",
                          kuaishou_uid, exc)
                continue

            for p in photos:
                s = compute_hot_score(
                    _as_int(p.get("view_count")),
                    _as_int(p.get("like_count")),
                    _as_int(p.get("comment_count")),
                    float(p.get("duration_sec") or 0),
                )
                p["_score"] = s
                p["_owner_uid"] = kuaishou_uid
                p["_owner_name"] = account_name
                all_results.append(p)
            time.sleep(0.5)

        # Overall matrix ranking (across all 13 accounts)
        all_results.sort(key=lambda x: -x.get("_score", 0))
        top = all_results[:top_n]

        saved = 0
        for rank, r in enumerate(top, 1):
            try:
                self.db.conn.execute(
                    """INSERT INTO drama_hot_rankings
                         (snapshot_date, snapshot_hour, platform, keyword,
                          rank, photo_encrypt_id, author_id, author_name,
                          caption, view_count, like_count, comment_count,
                          duration_sec, hot_score, tags)
                       VALUES (?, ?, 'internal_matrix', '(ALL_MATRIX)', ?, ?, ?, ?, ?,
                               ?, ?, ?, ?, ?, ?)
                       ON CONFLICT(snapshot_date, snapshot_hour, keyword, photo_encrypt_id)
                       DO UPDATE SET
                         rank = excluded.rank,
                         view_count = excluded.view_count,
                         like_count = excluded.like_count,
                         comment_count = excluded.comment_count,
                         hot_score = excluded.hot_score""",
                    (
                        today, hour, rank,
                        r.get("photo_encrypt_id"),
                        r.get("_owner_uid"),
                        r.get("_owner_name"),
                        (r.get("caption") or "")[:500],
                        _as_int(r.get("view_count")),
                        _as_int(r.get("like_count")),
                        _as_int(r.get("comment_count")),
                        float(r.get("duration_sec") or 0),
                        r.get("_score"),
                        json.dumps(r.get("tags", []), ensure_ascii=False),
                    ),
                )
                saved += 1
            except Exception as exc:
                log.error("[HotRankings] save internal rank=%d: %s", rank, exc)
        self.db.conn.commit()

        return {
            "accounts_processed": len(accounts),
            "total_photos": len(all_results),
            "top_saved": saved,
        }

    # ==================================================================
    # Query helpers
    # ==================================================================

    def get_latest(self, platform: str = "kuaishou_search",
                   keyword: str | None = None,
                   limit: int = 30) -> list[dict]:
        q = (
            "SELECT snapshot_date, snapshot_hour, keyword, rank, "
            "       author_name, caption, view_count, like_count, hot_score "
            "FROM drama_hot_rankings "
            "WHERE platform = ? AND snapshot_date = (SELECT MAX(snapshot_date) "
            "  FROM drama_hot_rankings WHERE platform = ?) "
        )
        args = [platform, platform]
        if keyword:
            q += "AND keyword = ? "
            args.append(keyword)
        q += "ORDER BY hot_score DESC LIMIT ?"
        args.append(limit)
        rows = self.db.conn.execute(q, args).fetchall()
        cols = ["date", "hour", "keyword", "rank", "author_name",
                "caption", "view", "like", "score"]
        return [dict(zip(cols, r)) for r in rows]
