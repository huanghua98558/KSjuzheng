# -*- coding: utf-8 -*-
"""Unified analytics read layer — feeds the AI decision engine.

Exposes a single ``build_feature_vector()`` that joins data from:
  - drama_hot_rankings      (what's hot in the market, keyword-indexed)
  - daily_account_metrics   (how our 13 accounts are performing)
  - work_metrics            (per-photo daily stats)
  - mcn_income_snapshots    (firefly income per member)
  - drama_banner_tasks      (cached bannerTaskId per drama)
  - keyword_watch_list      (tracked genres)

All outputs are plain dicts/lists, ready for LLM prompt or rule engine.
"""
from __future__ import annotations

import json
from datetime import date, timedelta


class DataInsights:
    def __init__(self, db_manager):
        self.db = db_manager

    # ------------------------------------------------------------------
    # Market snapshot (EXTERNAL)
    # ------------------------------------------------------------------

    def market_top_by_keyword(self, limit_per_kw: int = 5) -> dict:
        """Latest top photos per keyword (kuaishou_search)."""
        out = {}
        kws = self.db.conn.execute(
            """SELECT DISTINCT keyword FROM drama_hot_rankings
               WHERE platform = 'kuaishou_search'
                 AND snapshot_date = (SELECT MAX(snapshot_date)
                                      FROM drama_hot_rankings
                                      WHERE platform = 'kuaishou_search')"""
        ).fetchall()
        for (kw,) in kws:
            rows = self.db.conn.execute(
                """SELECT rank, author_name, caption, view_count, like_count,
                          hot_score, photo_encrypt_id
                   FROM drama_hot_rankings
                   WHERE platform = 'kuaishou_search' AND keyword = ?
                     AND snapshot_date = (SELECT MAX(snapshot_date)
                                          FROM drama_hot_rankings WHERE keyword = ?)
                   ORDER BY rank LIMIT ?""",
                (kw, kw, limit_per_kw),
            ).fetchall()
            out[kw] = [
                {"rank": r[0], "author": r[1], "caption": (r[2] or "")[:80],
                 "view": r[3], "like": r[4], "score": r[5], "photo_id": r[6]}
                for r in rows
            ]
        return out

    def keyword_heat_index(self) -> list[dict]:
        """Aggregate hot_score per keyword → which genres are trending."""
        rows = self.db.conn.execute(
            """SELECT keyword, COUNT(*) as n,
                      AVG(hot_score) as avg_score,
                      SUM(view_count) as total_views,
                      MAX(view_count) as peak_views
               FROM drama_hot_rankings
               WHERE platform = 'kuaishou_search'
                 AND snapshot_date = (SELECT MAX(snapshot_date)
                                      FROM drama_hot_rankings
                                      WHERE platform = 'kuaishou_search')
               GROUP BY keyword
               ORDER BY avg_score DESC"""
        ).fetchall()
        return [{"keyword": r[0], "samples": r[1], "avg_score": round(r[2], 3),
                 "total_views": r[3], "peak_views": r[4]} for r in rows]

    # ------------------------------------------------------------------
    # Matrix snapshot (INTERNAL)
    # ------------------------------------------------------------------

    def matrix_today_summary(self) -> dict:
        """Our 13 accounts' performance today."""
        today = date.today().isoformat()
        rows = self.db.conn.execute(
            """SELECT kuaishou_uid, account_name, total_plays, plays_delta,
                      total_likes
               FROM daily_account_metrics
               WHERE metric_date = ?
               ORDER BY total_plays DESC""",
            (today,),
        ).fetchall()
        accounts = []
        total_plays = 0
        total_likes = 0
        for r in rows:
            accounts.append({
                "uid": r[0], "name": r[1],
                "plays": r[2] or 0, "delta": r[3] or 0, "likes": r[4] or 0,
            })
            total_plays += r[2] or 0
            total_likes += r[4] or 0
        return {
            "date": today, "accounts": len(accounts),
            "total_plays": total_plays, "total_likes": total_likes,
            "by_account": accounts,
        }

    def matrix_top_works(self, limit: int = 10) -> list[dict]:
        rows = self.db.conn.execute(
            """SELECT photo_id, kuaishou_uid, drama_name, plays, likes, comments
               FROM work_metrics
               WHERE metric_date = (SELECT MAX(metric_date) FROM work_metrics)
               ORDER BY plays DESC LIMIT ?""",
            (limit,),
        ).fetchall()
        return [{"photo_id": r[0], "uid": r[1], "name": r[2] or "",
                 "plays": r[3], "likes": r[4], "comments": r[5]}
                for r in rows]

    # ------------------------------------------------------------------
    # Income (MCN)
    # ------------------------------------------------------------------

    def income_snapshot(self) -> list[dict]:
        rows = self.db.conn.execute(
            """SELECT snapshot_date, member_id, kuaishou_uid,
                      total_amount, commission_amount, commission_rate
               FROM mcn_income_snapshots
               WHERE snapshot_date = (SELECT MAX(snapshot_date)
                                      FROM mcn_income_snapshots)
               ORDER BY commission_amount DESC"""
        ).fetchall()
        return [{"date": r[0], "member_id": r[1], "uid": r[2],
                 "total_amount": r[3], "commission": r[4], "rate": r[5]}
                for r in rows]

    # ------------------------------------------------------------------
    # One-shot AI-ready feature vector
    # ------------------------------------------------------------------

    def build_feature_vector(self) -> dict:
        """Everything an AI strategy prompt needs in one dict."""
        return {
            "as_of": date.today().isoformat(),
            "market": {
                "keyword_heat": self.keyword_heat_index(),
                "top_per_keyword": self.market_top_by_keyword(limit_per_kw=3),
            },
            "matrix": {
                "summary": self.matrix_today_summary(),
                "top_works": self.matrix_top_works(limit=10),
            },
            "income": {
                "today": self.income_snapshot(),
            },
            "counts": {
                "authors_pool": self.db.conn.execute(
                    "SELECT COUNT(*) FROM drama_authors WHERE is_active=1"
                ).fetchone()[0],
                "drama_links_pending": self.db.conn.execute(
                    "SELECT COUNT(*) FROM drama_links WHERE status='pending'"
                ).fetchone()[0],
                "banner_tasks_cached": self.db.conn.execute(
                    "SELECT COUNT(*) FROM drama_banner_tasks"
                ).fetchone()[0],
                "accounts_active": self.db.conn.execute(
                    "SELECT COUNT(*) FROM device_accounts WHERE login_status='logged_in'"
                ).fetchone()[0],
            },
        }
