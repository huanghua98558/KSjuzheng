# -*- coding: utf-8 -*-
"""BurstAgent — 爆款响应 (Phase 2 B).

触发: 每 30min / 事件驱动 (analyzer 跑完后 / 外部 notify)

检测: 近 24h 内 publish_results 中任意视频:
  - 播放 ≥ ai.burst.threshold_views (默认 50000)
  - 或点赞 ≥ ai.burst.threshold_likes (5000)
  - 或收益 delta ≥ ai.burst.threshold_income (¥20)

行动: 如果该剧未在 24h 冷却期内被触发过:
  1. 查**全矩阵未发过该剧的账号** (diversity + non-cooldown)
  2. 为 top N (默认 13) 账号生成 PUBLISH_BURST task (priority=99)
  3. 所有 task 进 1 个 batch (batch_type='burst')
  4. 写 decision_history + 通知

⚠️ 爆款 task 不走 daily_plan_items, 直接进 task_queue.
   对齐用户原话 "矩阵放大高转化曝光".

Config:
  ai.burst.enabled                = true
  ai.burst.threshold_views        = 50000  (AI 可动态调)
  ai.burst.threshold_likes        = 5000
  ai.burst.threshold_income       = 20
  ai.burst.replicate_accounts     = 13  (最多 N 账号)
  ai.burst.cooldown_hours         = 24
  ai.burst.priority               = 99
"""
from __future__ import annotations

import json
import logging
import sqlite3
from datetime import datetime, timedelta
from typing import Any

from core.app_config import get as cfg_get
from core.notifier import notify

log = logging.getLogger(__name__)


def _connect() -> sqlite3.Connection:
    from core.config import DB_PATH
    c = sqlite3.connect(DB_PATH, timeout=30)
    c.execute("PRAGMA busy_timeout=30000")
    c.execute("PRAGMA journal_mode=WAL")
    c.execute("PRAGMA synchronous=NORMAL")
    c.row_factory = sqlite3.Row
    return c


def _fetch_thresholds() -> dict:
    return {
        "views":   int(cfg_get("ai.burst.threshold_views", 50000)),
        "likes":   int(cfg_get("ai.burst.threshold_likes", 5000)),
        "income":  float(cfg_get("ai.burst.threshold_income", 20.0)),
    }


def detect_burst_candidates(lookback_hours: int = 24) -> list[dict]:
    """找近 N 小时达到爆款阈值的 drama+account+photo.

    数据源: 优先 publish_daily_metrics + mcn_member_snapshots,
            fallback publish_results (如果上游没聚合).

    Returns:
        list[{drama_name, photo_id, account_id, views, likes, income}]
    """
    th = _fetch_thresholds()
    candidates = []

    with _connect() as c:
        # 主路径: publish_daily_metrics (analyzer 聚合过的)
        rows = c.execute(
            """SELECT pm.account_id, pm.metric_date,
                      pm.total_views, pm.total_likes, pm.income_delta,
                      pm.publishes_success
               FROM publish_daily_metrics pm
               WHERE pm.metric_date >= date('now', ?, 'localtime')
                 AND (
                   COALESCE(pm.total_views, 0) >= ? OR
                   COALESCE(pm.total_likes, 0) >= ? OR
                   COALESCE(pm.income_delta, 0) >= ?
                 )""",
            (f"-{lookback_hours//24 or 1} days",
             th["views"], th["likes"], th["income"]),
        ).fetchall()

        for r in rows:
            # 找该账号当天发的剧 (join publish_results)
            pubs = c.execute(
                """SELECT pr.drama_name, pr.photo_id, pr.created_at
                   FROM publish_results pr
                   WHERE pr.account_id = ?
                     AND date(pr.created_at) = ?
                     AND pr.publish_status = 'success'""",
                (str(r["account_id"]), r["metric_date"]),
            ).fetchall()
            for p in pubs:
                if not p["drama_name"]:
                    continue
                candidates.append({
                    "account_id": r["account_id"],
                    "drama_name": p["drama_name"],
                    "photo_id": p["photo_id"],
                    "views": r["total_views"] or 0,
                    "likes": r["total_likes"] or 0,
                    "income": r["income_delta"] or 0,
                    "discovered_at": r["metric_date"],
                })

    return candidates


def _is_drama_in_cooldown(drama_name: str, hours: int = 24) -> bool:
    """该剧是否刚刚触发过爆款响应 (cooldown)."""
    with _connect() as c:
        r = c.execute(
            """SELECT COUNT(*) AS n FROM task_queue
               WHERE task_type = 'PUBLISH_BURST'
                 AND drama_name = ?
                 AND datetime(created_at) >= datetime('now', ?, 'localtime')""",
            (drama_name, f"-{hours} hours"),
        ).fetchone()
    return (r["n"] or 0) > 0


def _pick_replicate_accounts(drama_name: str, max_count: int = 13) -> list[dict]:
    """选**未发过该剧**的账号, 排除冻结 / 无 cookie.

    优先级:
      1. tier=viral > established > warming_up > testing
      2. 近 30 天收益高的优先 (income bonus)
      3. 账号当前无 running task
    """
    with _connect() as c:
        rows = c.execute(
            """SELECT id, account_name, tier, numeric_uid
               FROM device_accounts
               WHERE login_status = 'logged_in'
                 AND tier != 'frozen'
                 AND id NOT IN (
                   SELECT CAST(account_id AS INTEGER)
                   FROM publish_results
                   WHERE drama_name = ?
                     AND publish_status = 'success'
                     AND datetime(created_at) >= datetime('now', '-7 days', 'localtime')
                 )
               ORDER BY CASE tier
                   WHEN 'viral' THEN 1
                   WHEN 'established' THEN 2
                   WHEN 'warming_up' THEN 3
                   WHEN 'testing' THEN 4
                   WHEN 'new' THEN 5
                   ELSE 9 END ASC,
                 id ASC
               LIMIT ?""",
            (drama_name, int(max_count)),
        ).fetchall()
    return [dict(r) for r in rows]


def trigger_burst_replication(
    drama_name: str,
    source_photo_id: str | None = None,
    source_account_id: int | None = None,
    metrics: dict | None = None,
    dry_run: bool = False,
) -> dict:
    """为指定剧触发全矩阵跟发.

    Returns: {triggered: bool, batch_id?, tasks_count, accounts, ...}
    """
    from core.executor.account_executor import enqueue_publish_task
    from core.task_manager import create_batch, add_task_to_batch
    from core.agents.strategy_planner_agent import _pick_recipe, _pick_image_mode

    if not cfg_get("ai.burst.enabled", True):
        return {"triggered": False, "reason": "burst_disabled"}

    # cooldown check
    cooldown_h = int(cfg_get("ai.burst.cooldown_hours", 24))
    if _is_drama_in_cooldown(drama_name, hours=cooldown_h):
        return {"triggered": False, "reason": "drama_in_cooldown",
                "drama": drama_name}

    # 找银矩阵账号
    max_n = int(cfg_get("ai.burst.replicate_accounts", 13))
    accounts = _pick_replicate_accounts(drama_name, max_count=max_n)
    if not accounts:
        return {"triggered": False, "reason": "no_eligible_accounts",
                "drama": drama_name}

    # 查 drama_banner_tasks 取 banner_task_id
    with _connect() as c:
        r = c.execute(
            """SELECT banner_task_id FROM drama_banner_tasks
               WHERE drama_name = ? LIMIT 1""",
            (drama_name,),
        ).fetchone()
        banner_task_id = r["banner_task_id"] if r else None

    priority = int(cfg_get("ai.burst.priority", 99))

    if dry_run:
        log.info("[burst][DRY] would enqueue %d PUBLISH_BURST for drama=%s",
                 len(accounts), drama_name)
        return {"triggered": True, "dry_run": True,
                "drama": drama_name, "accounts": accounts,
                "tasks_count": len(accounts)}

    # 创建 batch
    batch_id = create_batch(
        batch_name=f"burst_{drama_name[:20]}",
        batch_type="burst",
        total_tasks=len(accounts),
        config={
            "drama_name": drama_name,
            "source_photo_id": source_photo_id,
            "source_account_id": source_account_id,
            "metrics": metrics or {},
            "threshold": _fetch_thresholds(),
        },
        notes=f"爆款响应: {drama_name} 播放{(metrics or {}).get('views', 0)}",
    )

    # 为每账号生成 PUBLISH_BURST task
    enqueued = 0
    tasks_enqueued = []
    for i, acc in enumerate(accounts):
        recipe, _ = _pick_recipe(acc["tier"], drama_name)
        image_mode, _ = _pick_image_mode(
            acc["tier"], account_id=acc["id"], recipe=recipe
        )
        try:
            task_id = enqueue_publish_task(
                account_id=acc["id"],
                drama_name=drama_name,
                banner_task_id=banner_task_id,
                priority=priority,
                batch_id=batch_id,
                task_type="PUBLISH_BURST",
                task_source="burst",
                source_metadata={
                    "source_photo_id": source_photo_id,
                    "source_account_id": source_account_id,
                    "metrics": metrics,
                },
                params={
                    "process_recipe": recipe,
                    "image_mode": image_mode,
                    "account_tier": acc["tier"],
                    "burst_priority": priority,
                },
            )
            add_task_to_batch(batch_id, task_id, order=i)
            enqueued += 1
            tasks_enqueued.append({"account_id": acc["id"],
                                     "account_name": acc["account_name"],
                                     "task_id": task_id,
                                     "recipe": recipe,
                                     "image_mode": image_mode})
        except Exception as e:
            log.warning("[burst] enqueue failed acc=%s: %s", acc["id"], e)

    # 通知
    notify(
        title=f"🔥 爆款响应: {drama_name}",
        body=(f"源账号 {source_account_id} 的 {drama_name} 达到爆款阈值 "
              f"(views={(metrics or {}).get('views', 0):,}). "
              f"已触发 {enqueued} 账号跟发, batch={batch_id}"),
        level="info", source="burst_agent",
        extra={"drama": drama_name, "batch_id": batch_id, "accounts": enqueued},
    )

    return {
        "triggered": True,
        "batch_id": batch_id,
        "drama": drama_name,
        "tasks_count": enqueued,
        "accounts": tasks_enqueued[:5],   # preview
        "all_accounts_count": len(accounts),
    }


def run(dry_run: bool = False, lookback_hours: int = 24) -> dict:
    """BurstAgent 主入口 (ControllerAgent 每 30min 调).

    1. 扫近 N 小时爆款候选
    2. 对每个候选: 去重 + cooldown 检查 + 触发扩散

    ★ 2026-04-24 v6 Day 3: 叠加 operation_mode.should_burst() 检查.
      startup/growth 档 (<50 账号) 自动关 burst, 不依赖 config 手改.
    """
    # ★ operation_mode 门闸 — 先于 config 检查, 信息化 skip 原因
    try:
        from core.operation_mode import current_mode, should_burst, burst_threshold_views
        op_mode = current_mode()
        if not should_burst():
            return {"ok": True, "skipped": f"operation_mode={op_mode}_burst_off",
                    "mode": op_mode}
        # mode 级阈值 (若未单独设 ai.burst.threshold_views)
        mode_threshold = burst_threshold_views()
    except Exception as _e:
        log.warning("[burst] operation_mode 不可用: %s", _e)
        op_mode = "unknown"
        mode_threshold = int(cfg_get("ai.burst.threshold_views", 50000))

    if not cfg_get("ai.burst.enabled", True):
        return {"ok": True, "skipped": "config_disabled"}

    candidates = detect_burst_candidates(lookback_hours=lookback_hours)
    log.info("[burst] mode=%s threshold_views=%d → %d candidates detected",
             op_mode, mode_threshold, len(candidates))

    # 按 drama 去重 (每 drama 只触发 1 次, 取最高 views)
    by_drama: dict[str, dict] = {}
    for c in candidates:
        d = c["drama_name"]
        if d not in by_drama or (c["views"] or 0) > (by_drama[d]["views"] or 0):
            by_drama[d] = c

    triggered = 0
    results = []
    for drama, cand in by_drama.items():
        r = trigger_burst_replication(
            drama_name=drama,
            source_photo_id=cand.get("photo_id"),
            source_account_id=cand.get("account_id"),
            metrics={
                "views": cand.get("views"),
                "likes": cand.get("likes"),
                "income": cand.get("income"),
            },
            dry_run=dry_run,
        )
        if r.get("triggered"):
            triggered += 1
        results.append(r)

    log.info("[burst] run done: %d candidates → %d triggered",
             len(candidates), triggered)
    return {
        "ok": True,
        "dry_run": dry_run,
        "candidates_count": len(candidates),
        "dramas_unique": len(by_drama),
        "triggered": triggered,
        "results": results[:5],   # preview
    }


if __name__ == "__main__":
    import argparse, sys
    sys.stdout.reconfigure(encoding="utf-8")
    logging.basicConfig(level=logging.INFO)
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--lookback", type=int, default=24)
    ap.add_argument("--drama", default=None, help="手动触发某剧")
    args = ap.parse_args()

    if args.drama:
        r = trigger_burst_replication(args.drama, dry_run=args.dry_run)
    else:
        r = run(dry_run=args.dry_run, lookback_hours=args.lookback)
    import json as _j
    print(_j.dumps(r, ensure_ascii=False, indent=2, default=str))
