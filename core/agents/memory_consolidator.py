# -*- coding: utf-8 -*-
"""Memory consolidator — extract structured wisdom from daily operations.

Per PRODUCTION_EVOLUTION_PLAN.md §7.4:
  Daily: consolidate last 1 day into strategy_memories
  Weekly: 7-day rollup
  Monthly: 30-day rollup + pruning

A "memory" is a high-level claim like
  "剧A + mode6 + 晚间发布 = 播放 +31%"
with confidence + impact + valid_from/to.

v1: rule-based consolidation. v2 will call LLM to synthesize.
"""
from __future__ import annotations

import json
from datetime import date, datetime, timedelta
from typing import Any


class MemoryConsolidator:
    def __init__(self, db_manager):
        self.db = db_manager

    # ------------------------------------------------------------------
    # Daily: extract last-day insights
    # ------------------------------------------------------------------

    def daily(self) -> dict[str, Any]:
        """Extract memories from the last 24h of agent_runs + publish_results."""
        since = (datetime.now() - timedelta(days=1)).isoformat()
        new_memories = 0

        # M1: genre heat memory — keyword with the top avg_score yesterday
        try:
            rows = self.db.conn.execute(
                """SELECT keyword, AVG(hot_score) AS avg_score, SUM(view_count) AS total
                   FROM drama_hot_rankings
                   WHERE platform = 'kuaishou_search'
                     AND snapshot_date >= DATE('now','-1 day')
                   GROUP BY keyword
                   ORDER BY avg_score DESC LIMIT 1"""
            ).fetchall()
        except Exception:
            rows = []
        if rows:
            kw, avg_score, total = rows[0]
            new_memories += self._upsert_memory(
                memory_type="genre_heat_daily",
                drama_genre=kw,
                title=f"{kw} 赛道今日最热",
                description=f"在 15 个跟踪关键词中, {kw} 赛道 avg_score={avg_score:.2f}, "
                            f"累计播放 {total:,}",
                recommendation=f"优先投放 {kw} 赛道短剧",
                confidence=min(0.5 + avg_score / 10, 0.95),
                impact=min(total / 10_000_000, 1.0) if total else 0,
                valid_days=3,
            )

        # M2: best matrix account today
        today = date.today().isoformat()
        try:
            row = self.db.conn.execute(
                """SELECT kuaishou_uid, account_name, total_plays
                   FROM daily_account_metrics
                   WHERE metric_date = ? AND total_plays > 0
                   ORDER BY total_plays DESC LIMIT 1""",
                (today,),
            ).fetchone()
        except Exception:
            row = None
        if row:
            uid, name, plays = row
            new_memories += self._upsert_memory(
                memory_type="top_account_daily",
                drama_genre="",
                title=f"今日最佳: {name}",
                description=f"账号 {name} (uid {uid}) 今日播放 {plays}",
                recommendation=f"分析 {name} 的发布策略作为模板",
                confidence=0.7,
                impact=min(plays / 100_000, 1.0) if plays else 0,
                valid_days=1,
            )

        # M3: weakest idle accounts → warning memory
        try:
            weak = self.db.conn.execute(
                """SELECT COUNT(*) FROM account_health_snapshots
                   WHERE snapshot_date = (SELECT MAX(snapshot_date) FROM account_health_snapshots)
                     AND health_score < 70"""
            ).fetchone()[0]
        except Exception:
            weak = 0
        if weak >= 5:
            new_memories += self._upsert_memory(
                memory_type="health_warning",
                title=f"{weak} 个账号健康度偏低",
                description=f"有 {weak} 个账号 health_score<70",
                recommendation="优先检查 cookie / MCN 绑定状态",
                confidence=0.9,
                impact=0.5,
                valid_days=1,
            )

        return {"new_memories": new_memories, "since": since}

    # ------------------------------------------------------------------

    def _upsert_memory(
        self,
        *,
        memory_type: str,
        title: str,
        description: str = "",
        recommendation: str = "",
        drama_genre: str = "",
        strategy_name: str = "",
        publish_window: str = "",
        confidence: float = 0.5,
        impact: float = 0.0,
        valid_days: int = 7,
    ) -> int:
        # Skip if an identical-title active memory already exists
        existing = self.db.conn.execute(
            """SELECT id FROM strategy_memories
               WHERE title = ?
                 AND (valid_to IS NULL OR valid_to > datetime('now'))""",
            (title,),
        ).fetchone()
        if existing:
            # bump hit_count instead
            self.db.conn.execute(
                """UPDATE strategy_memories
                   SET hit_count = hit_count + 1,
                       updated_at = datetime('now','localtime')
                   WHERE id = ?""",
                (existing[0],),
            )
            self.db.conn.commit()
            return 0

        valid_to = (datetime.now() + timedelta(days=valid_days)).isoformat()
        try:
            self.db.conn.execute(
                """INSERT INTO strategy_memories
                     (memory_type, drama_genre, strategy_name, publish_window,
                      title, description, recommendation,
                      confidence_score, impact_score,
                      valid_from, valid_to,
                      source_agent)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?,
                           datetime('now','localtime'), ?,
                           'memory_consolidator')""",
                (memory_type, drama_genre, strategy_name, publish_window,
                 title, description, recommendation,
                 float(confidence), float(impact), valid_to),
            )
            self.db.conn.commit()
            return 1
        except Exception:
            return 0

    # ------------------------------------------------------------------

    def list_active(self) -> list[dict]:
        rows = self.db.conn.execute(
            """SELECT id, memory_type, title, description, recommendation,
                      confidence_score, impact_score, hit_count,
                      valid_from, valid_to
               FROM strategy_memories
               WHERE valid_to IS NULL OR valid_to > datetime('now')
               ORDER BY confidence_score DESC, impact_score DESC"""
        ).fetchall()
        cols = ["id","type","title","desc","rec","conf","impact","hits","from","to"]
        return [dict(zip(cols, r)) for r in rows]
