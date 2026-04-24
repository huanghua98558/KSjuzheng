# -*- coding: utf-8 -*-
"""Hot Hunter Agent — 爆款雷达定时扫作者.

★ 2026-04-24 v6 Week 2 Day 8+ Day 3

职责:
  ControllerAgent step 26 每 N 秒触发一次 (默认 2h):
    - 从 drama_authors 选 batch (按 priority / 老化时间)
    - 调 ks_trending_hunter.scan_batch() 扫
    - 返回统计给 controller 打 log
    - 每 6h 做一次"作者池升级" (按 burst_count_30d 调 scrape_priority)

数据链路:
  作者池 → scan → hot_photos → 副产品: drama_links CDN + drama_authors 扩池

用法:
  python -m core.agents.hot_hunter_agent --dry-run
  python -m core.agents.hot_hunter_agent --run
"""
from __future__ import annotations

import logging
import sqlite3
import sys
import time
from typing import Optional

log = logging.getLogger(__name__)


def _connect():
    from core.config import DB_PATH
    c = sqlite3.connect(DB_PATH, timeout=30)
    c.execute("PRAGMA busy_timeout=30000")
    c.row_factory = sqlite3.Row
    return c


def _cfg(key: str, default):
    try:
        from core.app_config import get as _g
        return _g(key, default)
    except Exception:
        return default


def run(dry_run: bool = False) -> dict:
    """触发一次扫描. 返 stats.

    Returns:
        {
          'scanned': N, 'photos_inserted': M, 'cdns_saved': K,
          'authors_ok': O, 'authors_fail': F,
          'dry_run': bool, 'elapsed_sec': T,
        }
    """
    if not _cfg("ai.trending_hunter.enabled", True):
        return {"skipped": True, "reason": "disabled_by_config"}

    if dry_run:
        # dry-run 只统计要扫多少作者
        from core.ks_trending_hunter import _pick_authors_to_scan
        batch_size = int(_cfg("ai.trending_hunter.max_authors_per_batch", 30))
        authors = _pick_authors_to_scan(batch_size)
        log.info("[hot_hunter] dry-run — 本次会扫 %d 个作者", len(authors))
        return {
            "dry_run": True, "would_scan": len(authors),
            "authors_preview": [{"uid": a["kuaishou_uid"],
                                  "name": (a.get("nickname") or "")[:20],
                                  "priority": a.get("scrape_priority")}
                                 for a in authors[:5]],
        }

    t0 = time.time()
    from core.ks_trending_hunter import scan_batch
    try:
        stats = scan_batch()
    except Exception as e:
        log.exception("[hot_hunter] scan_batch 异常: %s", e)
        return {"error": str(e)[:200], "elapsed_sec": round(time.time() - t0, 1)}

    stats["elapsed_sec"] = round(time.time() - t0, 1)
    log.info("[hot_hunter] 完成 — %s", _fmt_stats(stats))
    return stats


def _fmt_stats(s: dict) -> str:
    return (f"扫 {s.get('scanned',0)} 作者 "
            f"→ 入池 {s.get('photos_inserted',0)} 新 + {s.get('photos_updated',0)} 更新 "
            f"| CDN 副产品 {s.get('cdns_saved',0)} 条 "
            f"| ok={s.get('authors_ok',0)} fail={s.get('authors_fail',0)} "
            f"| {s.get('elapsed_sec',0)}s")


def maintenance_update_author_priority() -> dict:
    """每 6h 跑一次: 按 burst_count_30d 自动调 scrape_priority.

    Priority 规则:
      burst_count_30d >= 5  → priority = 1 (最高, 每 2h 扫)
      burst_count_30d >= 2  → priority = 2
      近 7 天有更新          → priority = 3
      近 30 天有更新         → priority = 4
      其他                   → priority = 5
    """
    with _connect() as c:
        # 1. 从 hot_photos 按作者统计近 30 天 "爆款数"
        #   爆款定义 (初期简单): vph > 3000 AND age < 48h AND view_count > 10000
        author_stats = c.execute("""
            SELECT author_id,
                COUNT(*) AS burst_count,
                MAX(first_seen_at) AS last_burst_at,
                AVG(view_count) AS avg_views
            FROM hot_photos
            WHERE first_seen_at > datetime('now','-30 days','localtime')
              AND views_per_hour > 3000
              AND age_hours_at_discover < 48
              AND view_count > 10000
              AND author_id IS NOT NULL AND author_id != ''
            GROUP BY author_id
        """).fetchall()

        updated = 0
        for row in author_stats:
            uid = row["author_id"]
            cnt = row["burst_count"]
            last_at = row["last_burst_at"]
            avg_v = row["avg_views"] or 0

            if cnt >= 5:
                new_pri = 1
            elif cnt >= 2:
                new_pri = 2
            else:
                new_pri = 3

            c.execute("""UPDATE drama_authors SET
                burst_count_30d = ?,
                last_burst_found_at = ?,
                avg_views_per_photo = ?,
                scrape_priority = MIN(scrape_priority, ?)
                WHERE kuaishou_uid = ?""",
                (cnt, last_at, avg_v, new_pri, uid))
            updated += c.execute(
                "SELECT changes()").fetchone()[0]

        # 2. 无爆款的降级 (近 30 天无 hot_photos 记录)
        c.execute("""UPDATE drama_authors SET
            scrape_priority = CASE
                WHEN last_scraped_at IS NULL OR last_scraped_at < datetime('now','-30 days','localtime') THEN 5
                WHEN last_scraped_at < datetime('now','-7 days','localtime') THEN 4
                ELSE scrape_priority
            END,
            status = CASE
                WHEN last_scraped_at < datetime('now','-60 days','localtime') THEN 'dormant'
                ELSE status
            END
            WHERE kuaishou_uid NOT IN (
                SELECT DISTINCT author_id FROM hot_photos
                WHERE first_seen_at > datetime('now','-30 days','localtime')
                  AND author_id IS NOT NULL
            )
            AND (is_active = 1 OR is_active IS NULL)""")
        downgraded = c.execute("SELECT changes()").fetchone()[0]

        c.commit()

        # 分布统计
        dist = dict(c.execute(
            "SELECT scrape_priority, COUNT(*) FROM drama_authors GROUP BY scrape_priority"
        ).fetchall())

    result = {
        "updated_promoted": updated,
        "downgraded": downgraded,
        "priority_distribution": dist,
    }
    log.info("[hot_hunter] author priority update: %s", result)
    return result


def main():
    import argparse
    ap = argparse.ArgumentParser(description="Hot Hunter Agent")
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--dry-run", action="store_true")
    g.add_argument("--run", action="store_true")
    g.add_argument("--update-priority", action="store_true",
                    help="只跑作者池 priority 调整")
    args = ap.parse_args()

    logging.basicConfig(level=logging.INFO,
                         format="%(asctime)s [%(levelname)s] %(message)s",
                         datefmt="%H:%M:%S")
    try: sys.stdout.reconfigure(encoding="utf-8")
    except Exception: pass

    import json
    if args.update_priority:
        r = maintenance_update_author_priority()
    else:
        r = run(dry_run=args.dry_run)
    print(json.dumps(r, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
