# -*- coding: utf-8 -*-
"""任务体系统一管理 — Phase 2 核心.

职责:
  1. batch 创建/更新/查询 (batches + batch_tasks)
  2. task_type 注册表 (哪些 type → 哪个 handler)
  3. 批次进度聚合

用法:

    # 创建 batch (planner / burst / experiment / maintenance 都用)
    batch_id = create_batch(
        batch_name="plan_42",
        batch_type="planner",      # planner / burst / experiment / maintenance
        total_tasks=39,
        config={"plan_date": "2026-04-20"},
    )

    # 批次关联 task
    add_task_to_batch(batch_id, task_id, order=0)

    # 进度更新 (pipeline 跑完自动调)
    mark_task_complete(batch_id, task_id, success=True)

    # 查询
    progress = get_batch_progress(batch_id)
    # → {total, completed, failed, cancelled, percent, status}

任务类型注册 (executor 用):

    TASK_HANDLERS = {
        "PUBLISH":          "core.executor.pipeline.run_publish_pipeline",
        "COOKIE_REFRESH":   "core.maintenance.refresh_account_cookie",
        "FREEZE_ACCOUNT":   "core.maintenance.freeze_account",
        "QUOTA_BACKFILL":   "core.maintenance.backfill_quota",
        "LIBRARY_CLEAN":    "core.maintenance.clean_drama_library",
        "MCN_TOKEN":        "core.maintenance.refresh_mcn_token",
    }
"""
from __future__ import annotations

import json
import logging
import sqlite3
import time
from datetime import datetime
from typing import Any

log = logging.getLogger(__name__)


def _connect() -> sqlite3.Connection:
    from core.config import DB_PATH
    c = sqlite3.connect(DB_PATH, timeout=30)
    c.execute("PRAGMA busy_timeout=30000")
    c.execute("PRAGMA journal_mode=WAL")
    c.execute("PRAGMA synchronous=NORMAL")
    c.row_factory = sqlite3.Row
    return c


# ═══════════════════════════════════════════════════════════════
# Task Type 注册表 (Phase 2 ABCD)
# ═══════════════════════════════════════════════════════════════

# 格式: task_type → (handler_module.fn, description)
# 注: 所有维护 handler 都在 core.agents.maintenance_agent 里, publish 走 pipeline
TASK_HANDLERS: dict[str, tuple[str, str]] = {
    # A/B/C: 发布类 (共享 pipeline)
    "PUBLISH":         ("core.executor.pipeline.run_publish_pipeline",
                         "常规发布任务 (planner/burst/experiment 共用)"),
    "PUBLISH_BURST":   ("core.executor.pipeline.run_publish_pipeline",
                         "爆款响应发布 (priority=99)"),
    # D: 维护类 (均在 core.agents.maintenance_agent 中)
    "COOKIE_REFRESH":  ("core.agents.maintenance_agent.refresh_account_cookie",
                         "刷新账号 cookie (防过期)"),
    "FREEZE_ACCOUNT":  ("core.agents.maintenance_agent.freeze_account",
                         "冻结账号 (风控紧急)"),
    "UNFREEZE_ACCOUNT": ("core.agents.maintenance_agent.unfreeze_account",
                         "解冻账号 (冷却期结束)"),
    "QUOTA_BACKFILL":  ("core.agents.maintenance_agent.backfill_quota",
                         "失败任务次日回补配额"),
    "LIBRARY_CLEAN":   ("core.agents.maintenance_agent.clean_drama_library",
                         "清洗 drama_links 过期/失效链接"),
    "MCN_TOKEN":       ("core.agents.maintenance_agent.refresh_mcn_token",
                         "刷新 MCN captain token"),
    # Legacy (保留兼容)
    "PUBLISH_DRAMA":   ("core.executor.pipeline.run_publish_pipeline",
                         "legacy alias for PUBLISH"),
    "PUBLISH_A":       ("core.executor.pipeline.run_publish_pipeline",
                         "legacy alias"),
}


def get_handler_for(task_type: str) -> str | None:
    """返回 task_type 对应的 handler 函数路径. None = 不认识."""
    entry = TASK_HANDLERS.get(task_type.upper())
    return entry[0] if entry else None


def is_publish_type(task_type: str) -> bool:
    """是否是发布类 task (共用 pipeline)."""
    return task_type.upper() in (
        "PUBLISH", "PUBLISH_BURST", "PUBLISH_DRAMA", "PUBLISH_A"
    )


# ═══════════════════════════════════════════════════════════════
# Batch 管理 (batches + batch_tasks)
# ═══════════════════════════════════════════════════════════════

def create_batch(
    batch_name: str,
    batch_type: str,
    total_tasks: int,
    config: dict | None = None,
    notes: str = "",
) -> str:
    """创建 batch. batch_type ∈ planner/burst/experiment/maintenance.

    Returns: batch_id (文本, 格式: {type}_{ts}_{hash})
    """
    import secrets
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    batch_id = f"{batch_type}_{ts}_{secrets.token_hex(3)}"

    with _connect() as c:
        c.execute(
            """INSERT INTO batches
                 (batch_id, batch_name, batch_type, total_tasks,
                  completed_tasks, failed_tasks, cancelled_tasks,
                  status, created_at, config, notes)
               VALUES (?, ?, ?, ?, 0, 0, 0, 'running',
                       datetime('now','localtime'), ?, ?)""",
            (batch_id, batch_name, batch_type, total_tasks,
             json.dumps(config or {}, ensure_ascii=False), notes),
        )
        c.commit()
    log.info("[batch] created %s type=%s total=%d", batch_id, batch_type, total_tasks)
    return batch_id


def add_task_to_batch(batch_id: str, task_id: str, order: int = 0) -> None:
    """task 关联到 batch."""
    try:
        with _connect() as c:
            c.execute(
                """INSERT INTO batch_tasks (batch_id, task_id, task_order, created_at)
                   VALUES (?, ?, ?, datetime('now','localtime'))""",
                (batch_id, task_id, order),
            )
            # 更新 task_queue.batch_id (冗余保证)
            c.execute(
                "UPDATE task_queue SET batch_id=? WHERE id=?",
                (batch_id, task_id),
            )
            c.commit()
    except sqlite3.IntegrityError:
        pass  # 已关联


def mark_task_complete(batch_id: str, task_id: str, *,
                         success: bool, cancelled: bool = False) -> None:
    """pipeline 跑完调这个, 更新 batch 进度."""
    try:
        with _connect() as c:
            if cancelled:
                c.execute(
                    "UPDATE batches SET cancelled_tasks=cancelled_tasks+1 "
                    "WHERE batch_id=?", (batch_id,),
                )
            elif success:
                c.execute(
                    "UPDATE batches SET completed_tasks=completed_tasks+1 "
                    "WHERE batch_id=?", (batch_id,),
                )
            else:
                c.execute(
                    "UPDATE batches SET failed_tasks=failed_tasks+1 "
                    "WHERE batch_id=?", (batch_id,),
                )
            # 若全 done 则 status=completed
            row = c.execute(
                """SELECT total_tasks, completed_tasks, failed_tasks, cancelled_tasks
                   FROM batches WHERE batch_id=?""", (batch_id,),
            ).fetchone()
            if row:
                total = row["total_tasks"]
                done = (row["completed_tasks"] + row["failed_tasks"]
                        + row["cancelled_tasks"])
                if done >= total:
                    c.execute(
                        "UPDATE batches SET status='completed', "
                        "end_time=datetime('now','localtime') WHERE batch_id=?",
                        (batch_id,),
                    )
            c.commit()
    except Exception as e:
        log.debug("[batch] mark_task_complete failed: %s", e)


def get_batch_progress(batch_id: str) -> dict | None:
    """查 batch 进度."""
    with _connect() as c:
        r = c.execute("SELECT * FROM batches WHERE batch_id=?", (batch_id,)).fetchone()
    if not r:
        return None
    d = dict(r)
    total = d.get("total_tasks") or 0
    done = (d.get("completed_tasks", 0) + d.get("failed_tasks", 0)
            + d.get("cancelled_tasks", 0))
    d["percent"] = round(100 * done / total, 1) if total else 0
    d["remaining"] = max(0, total - done)
    return d


def list_recent_batches(
    limit: int = 20,
    batch_type: str | None = None,
    status: str | None = None,
) -> list[dict]:
    """最近 N 个 batch (for Dashboard)."""
    where = []
    params: list[Any] = []
    if batch_type:
        where.append("batch_type = ?")
        params.append(batch_type)
    if status:
        where.append("status = ?")
        params.append(status)
    sql = "SELECT * FROM batches"
    if where:
        sql += " WHERE " + " AND ".join(where)
    sql += " ORDER BY id DESC LIMIT ?"
    params.append(int(limit))

    with _connect() as c:
        rows = c.execute(sql, params).fetchall()
    return [dict(r) for r in rows]


def list_batch_tasks(batch_id: str) -> list[dict]:
    """某 batch 的所有 task (for Dashboard detail)."""
    with _connect() as c:
        rows = c.execute(
            """SELECT bt.task_order, bt.task_id,
                      t.task_type, t.account_id, t.drama_name,
                      t.status, t.priority, t.created_at, t.finished_at,
                      SUBSTR(t.error_message, 1, 100) AS error
               FROM batch_tasks bt
               LEFT JOIN task_queue t ON bt.task_id = t.id
               WHERE bt.batch_id = ?
               ORDER BY bt.task_order ASC""",
            (batch_id,),
        ).fetchall()
    return [dict(r) for r in rows]


# ═══════════════════════════════════════════════════════════════
# 并行度检查 (给 executor 用)
# ═══════════════════════════════════════════════════════════════

def count_active_by_type(task_type: str) -> int:
    """当前 running+queued 的 task_type 数量."""
    with _connect() as c:
        r = c.execute(
            "SELECT COUNT(*) AS n FROM task_queue "
            "WHERE task_type = ? AND status IN ('queued', 'running')",
            (task_type,),
        ).fetchone()
    return r["n"] if r else 0


def task_type_slot_available(task_type: str) -> bool:
    """当前 task_type 是否还有并发槽位."""
    from core.app_config import get as cfg_get
    # 按 task_type 读 limit
    if task_type == "PUBLISH" or task_type == "PUBLISH_BURST":
        limit = int(cfg_get("executor.per_task_type_publish", 3))
    elif task_type in ("COOKIE_REFRESH", "MCN_TOKEN", "LIBRARY_CLEAN",
                        "FREEZE_ACCOUNT", "UNFREEZE_ACCOUNT", "QUOTA_BACKFILL"):
        limit = int(cfg_get("executor.per_task_type_maintenance", 1))
    else:
        limit = int(cfg_get("executor.per_task_type_default", 2))

    active = count_active_by_type(task_type)
    return active < limit


# ═══════════════════════════════════════════════════════════════
# CLI (for dev testing)
# ═══════════════════════════════════════════════════════════════

if __name__ == "__main__":
    import argparse, sys
    sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser()
    ap.add_argument("--list", action="store_true", help="列最近 batch")
    ap.add_argument("--batch-type", default=None)
    ap.add_argument("--detail", default=None, help="查 batch_id 的 task 列表")
    ap.add_argument("--handlers", action="store_true", help="列所有 task_type")
    args = ap.parse_args()

    if args.handlers:
        print(f"注册的 task_type 及 handler:")
        for t, (h, desc) in TASK_HANDLERS.items():
            print(f"  {t:22s} → {h}")
            print(f"    {desc}")
    elif args.list:
        batches = list_recent_batches(batch_type=args.batch_type)
        print(f"最近 {len(batches)} 个 batch:")
        for b in batches:
            total = b.get('total_tasks', 0)
            done = b.get('completed_tasks', 0) + b.get('failed_tasks', 0)
            pct = 100 * done / total if total else 0
            print(f"  {b['batch_id']:40s} {b['batch_type']:12s} "
                  f"{done}/{total} ({pct:.0f}%) {b['status']}")
    elif args.detail:
        tasks = list_batch_tasks(args.detail)
        print(f"batch {args.detail} 含 {len(tasks)} tasks:")
        for t in tasks:
            print(f"  [{t['task_order']}] {t['task_id'][:30]:32s} "
                  f"{t.get('task_type','?'):12s} {t.get('status','?'):10s} "
                  f"{t.get('drama_name','')[:20]}")
    else:
        ap.print_help()
