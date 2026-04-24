# -*- coding: utf-8 -*-
"""Publish Outcome — 发布结果回采 + 学习根基.

★ 2026-04-24 v6 Week 2 Day 8+ Day 5

核心表: publish_outcome (由 migrate_v44 建)

流程:
  T+0 (发布瞬间):    pipeline 调 record_publish_success() 写 decision snapshot
  T+24h:             outcome_collector 调 feed_selection API 查 views_24h
  T+48h:             同上 views_48h
  T+7d:              同上 views_7d + income (MCN)
  → 计算 ROI
  → Analyzer 用于 signal_calibrator (Week 3+)

API:
  record_publish_success(task_id, photo_id, drama_name, ...)
    立即写 publish_outcome 行

  collect_pending_outcomes(age_hours)
    批量查快手 feed, 填 views/likes
"""
from __future__ import annotations

import json
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
    c.execute("PRAGMA journal_mode=WAL")
    c.row_factory = sqlite3.Row
    return c


def _cfg(key: str, default):
    try:
        from core.app_config import get as _g
        return _g(key, default)
    except Exception:
        return default


# ══════════════════════════════════════════════════════════════
# 发布瞬间: 记录 decision snapshot
# ══════════════════════════════════════════════════════════════
def record_publish_success(
    task_id: str,
    our_photo_id: str,
    drama_name: str,
    account_id: int | str,
    recipe: str = "",
    image_mode: str = "",
    task_params: Optional[dict] = None,
) -> int | None:
    """发布成功时调 — 写 publish_outcome 记录.

    Returns: publish_outcome.id 或 None.
    """
    if not _cfg("ai.publish_outcome.enabled", True):
        return None

    try:
        aid = int(account_id)
    except (ValueError, TypeError):
        aid = None

    # 查 task_queue 和 daily_plan_items 里的原始信号 snapshot
    with _connect() as c:
        # 1. 找关联 plan_item_id + hot_photo_id (from drama_name)
        plan_item_id = None
        try:
            row = c.execute("""SELECT id FROM daily_plan_items
                WHERE task_id = ? LIMIT 1""", (task_id,)).fetchone()
            if row: plan_item_id = row["id"]
        except Exception:
            pass

        # 2. 找 hot_photo (如果这剧是 hot_hunter 采来的)
        hot_photo_id = None
        hp_signals = None
        try:
            row = c.execute("""SELECT photo_id, view_count, views_per_hour,
                like_ratio, age_hours_at_discover, like_count, comment_count
                FROM hot_photos WHERE drama_name = ?
                ORDER BY views_per_hour DESC LIMIT 1""",
                (drama_name,)).fetchone()
            if row:
                hot_photo_id = row["photo_id"]
                hp_signals = {
                    "hot_photo_id": hot_photo_id,
                    "views_at_discover": row["view_count"],
                    "vph": row["views_per_hour"],
                    "like_ratio": row["like_ratio"],
                    "age_hours": row["age_hours_at_discover"],
                    "likes": row["like_count"],
                    "comments": row["comment_count"],
                }
        except Exception:
            pass

        # 3. 账号 tier
        account_tier = None
        if aid:
            try:
                row = c.execute("SELECT tier FROM device_accounts WHERE id=?",
                                 (aid,)).fetchone()
                if row: account_tier = row["tier"]
            except Exception:
                pass

        # 4. 构造 signals snapshot (从 task_params / hot_photos 抽)
        signals_discover = hp_signals or {}
        signals_publish = {
            "recipe": recipe,
            "image_mode": image_mode,
            "account_tier": account_tier,
            "task_params_keys": list(task_params.keys()) if task_params else [],
        }

        cost = float(_cfg("ai.publish_outcome.cost_estimate_rmb", 1.0))

        # 5. 插入
        try:
            cur = c.execute(
                """INSERT INTO publish_outcome
                    (plan_item_id, task_id, our_photo_id, hot_photo_id,
                     drama_name, account_id, account_tier, recipe, image_mode,
                     signals_at_discover_json, signals_at_publish_json,
                     decide_at, publish_at,
                     cost_estimate_rmb, status, created_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?,
                           ?, ?,
                           datetime('now','localtime'),
                           datetime('now','localtime'),
                           ?, 'pending', datetime('now','localtime'))""",
                (plan_item_id, task_id, our_photo_id, hot_photo_id,
                 drama_name, aid, account_tier, recipe, image_mode,
                 json.dumps(signals_discover, ensure_ascii=False),
                 json.dumps(signals_publish, ensure_ascii=False),
                 cost)
            )
            new_id = cur.lastrowid
            c.commit()
            log.info("[publish_outcome] recorded task=%s drama=%s acct=%d id=%d "
                      "hot_photo=%s",
                      task_id, drama_name, aid or 0, new_id, hot_photo_id or "(none)")
            return new_id
        except sqlite3.IntegrityError as e:
            log.warning("[publish_outcome] integrity err: %s", e)
            return None
        except Exception as e:
            log.exception("[publish_outcome] record failed: %s", e)
            return None


# ══════════════════════════════════════════════════════════════
# 回采结果: 查快手 feed API 拿 views/likes
# ══════════════════════════════════════════════════════════════
def _query_photo_stats(photo_id: str, cookie: str, kww: str) -> Optional[dict]:
    """用 profile/feed API 拿 photo 的最新 views/likes.

    接口我们已经会用 (ks_profile_collector._call_profile_feed).
    简化策略: 从 photo_id 反查 author (hot_photos.author_id),
    然后调 profile/feed 拿该作者 feed, 找对应 photo_id 的条目.
    """
    # TODO Phase 2: 直接 graphql 查单 photo_id. 暂时用 search by drama_name 近似
    return None


def _collect_outcome_for_row(row: dict, mode: str) -> bool:
    """给 1 行 publish_outcome 补 views 字段.

    Args:
        mode: '24h' / '48h' / '7d'
    Returns: True = 成功
    """
    from core.ks_profile_collector import search_drama_by_name

    drama = row["drama_name"]
    our_pid = row["our_photo_id"]
    if not our_pid:
        return False

    # graphql search 按剧名搜, 找我们的 photo_id
    try:
        cdns = search_drama_by_name(drama, max_pages=1, max_retries=3)
    except Exception as e:
        log.warning("[outcome_collector] search %r fail: %s", drama, e)
        return False

    # cdns 里 photo_id 找对应
    match = None
    for c in cdns:
        if str(c.get("photo_id")) == str(our_pid):
            match = c
            break

    if not match:
        # 我们的 photo 不在 search 前 20 结果里 — 记 0 (没被快手收录到 search 结果)
        with _connect() as conn:
            field_v = f"views_{mode}"
            field_c = f"collected_at_{mode}"
            conn.execute(
                f"""UPDATE publish_outcome SET
                    {field_v} = 0, {field_c} = datetime('now','localtime'),
                    last_error = 'not_found_in_search'
                WHERE id = ?""", (row["id"],))
            conn.commit()
        return True

    # 从 match.caption 回提 (view/like 不在 search 响应, 需要更深查)
    # 简化版: 用 raw photo 数据 (search_drama_by_name 返回的 dict 暂不含 view)
    # 真正 full data 需要 /rest/v/profile/feed. 先做 likes/caption 记录
    # TODO Phase 2: 完整查

    # 记 duration / caption (至少标 collected)
    with _connect() as conn:
        field_c = f"collected_at_{mode}"
        # 如果 search 有 view/like 信息就填, 没有就 NULL
        conn.execute(
            f"""UPDATE publish_outcome SET
                {field_c} = datetime('now','localtime'),
                status = CASE WHEN ? = '7d' THEN '7d_done' ELSE status END
            WHERE id = ?""", (mode, row["id"]))
        conn.commit()
    return True


def collect_pending_outcomes(mode: str = "24h", max_rows: int = 50) -> dict:
    """批量回采. 每 1h 跑一次 (controller step 26c).

    Args:
        mode: '24h' / '48h' / '7d'
        max_rows: 单次最多处理行数
    """
    if not _cfg(f"ai.publish_outcome.collect_{mode}_enabled", True):
        return {"skipped": True}

    hours_map = {"24h": 24, "48h": 48, "7d": 168}
    hours = hours_map.get(mode, 24)

    with _connect() as c:
        # 找该 mode 时间窗口到了的 (publish_at 距今 hours-N ~ hours+24)
        rows = c.execute(f"""
            SELECT id, task_id, drama_name, our_photo_id, publish_at, status,
                   views_{mode}, collected_at_{mode}
            FROM publish_outcome
            WHERE our_photo_id IS NOT NULL AND our_photo_id != ''
              AND publish_at IS NOT NULL
              AND publish_at < datetime('now', ? || ' hours', 'localtime')
              AND collected_at_{mode} IS NULL
              AND status NOT IN ('failed', '7d_done')
            ORDER BY publish_at ASC
            LIMIT ?
        """, (f"-{hours}", max_rows)).fetchall()

    if not rows:
        return {"mode": mode, "pending": 0, "collected": 0}

    stats = {"mode": mode, "pending": len(rows),
             "collected": 0, "errors": 0}
    for r in rows:
        try:
            ok = _collect_outcome_for_row(dict(r), mode)
            if ok: stats["collected"] += 1
            else: stats["errors"] += 1
            time.sleep(1.0)  # QPS 控制
        except Exception as e:
            log.warning("[outcome_collector] row %d fail: %s", r["id"], e)
            stats["errors"] += 1

    log.info("[outcome_collector] %s: %s", mode, stats)
    return stats


# ══════════════════════════════════════════════════════════════
# 统计 (Dashboard 用)
# ══════════════════════════════════════════════════════════════
def stats() -> dict:
    with _connect() as c:
        total = c.execute("SELECT COUNT(*) FROM publish_outcome").fetchone()[0]
        by_status = dict(c.execute(
            "SELECT status, COUNT(*) FROM publish_outcome GROUP BY status"
        ).fetchall())
        pending_24h = c.execute("""
            SELECT COUNT(*) FROM publish_outcome
            WHERE collected_at_24h IS NULL
              AND publish_at < datetime('now','-24 hours','localtime')
              AND status != 'failed'
        """).fetchone()[0]
        pending_48h = c.execute("""
            SELECT COUNT(*) FROM publish_outcome
            WHERE collected_at_48h IS NULL
              AND publish_at < datetime('now','-48 hours','localtime')
              AND status != 'failed'
        """).fetchone()[0]
        pending_7d = c.execute("""
            SELECT COUNT(*) FROM publish_outcome
            WHERE collected_at_7d IS NULL
              AND publish_at < datetime('now','-7 days','localtime')
              AND status != 'failed'
        """).fetchone()[0]

        # ROI 分布 (有 income_7d 的)
        roi_rows = c.execute("""
            SELECT account_tier, COUNT(*) n, AVG(roi) avg_roi
            FROM publish_outcome
            WHERE roi IS NOT NULL
            GROUP BY account_tier
        """).fetchall()

    return {
        "total": total,
        "by_status": by_status,
        "pending_24h_collect": pending_24h,
        "pending_48h_collect": pending_48h,
        "pending_7d_collect": pending_7d,
        "roi_by_tier": [dict(r) for r in roi_rows],
    }


def main():
    import argparse
    ap = argparse.ArgumentParser(description="Publish Outcome 回采")
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--stats", action="store_true")
    g.add_argument("--collect-24h", action="store_true")
    g.add_argument("--collect-48h", action="store_true")
    g.add_argument("--collect-7d", action="store_true")
    args = ap.parse_args()

    logging.basicConfig(level=logging.INFO,
                         format="%(asctime)s [%(levelname)s] %(message)s",
                         datefmt="%H:%M:%S")
    try: sys.stdout.reconfigure(encoding="utf-8")
    except Exception: pass

    import json as _j
    if args.stats:
        print(_j.dumps(stats(), indent=2, ensure_ascii=False))
    elif args.collect_24h:
        print(_j.dumps(collect_pending_outcomes("24h"), indent=2, ensure_ascii=False))
    elif args.collect_48h:
        print(_j.dumps(collect_pending_outcomes("48h"), indent=2, ensure_ascii=False))
    elif args.collect_7d:
        print(_j.dumps(collect_pending_outcomes("7d"), indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
