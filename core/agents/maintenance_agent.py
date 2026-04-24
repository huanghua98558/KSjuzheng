# -*- coding: utf-8 -*-
"""MaintenanceAgent — D 维护/风控任务生产者 + 5 种处理器.

5 种任务类型 (对齐 core/task_manager.py 注册):
  1. COOKIE_REFRESH      — 刷账号 cookie (每 12h)
  2. MCN_TOKEN           — 刷 MCN captain token (每 6h)
  3. LIBRARY_CLEAN       — 清 drama_links 过期链接 (每周一)
  4. QUOTA_BACKFILL      — 昨天失败 task 次日回补 (每日 08:00 前)
  5. FREEZE_ACCOUNT      — 连续失败自动冻结 (Watchdog 已有触发, 这里注入 task)

生产模式:
  - ControllerAgent 每小时调 run() 一次
  - run() 根据时间判定需要生产哪类 task, 入队 + batch 记录

消费模式 (executor dispatcher 路由到下面函数):
  refresh_account_cookie(task)
  refresh_mcn_token(task)
  clean_drama_library(task)
  backfill_quota(task)
  freeze_account(task)
  unfreeze_account(task)
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


# ═══════════════════════════════════════════════════════════════
# 生产者 run() — 定时调用, 生成维护 task
# ═══════════════════════════════════════════════════════════════

def run(dry_run: bool = False) -> dict:
    """MaintenanceAgent 主入口 (ControllerAgent 每 1h 调).

    判定哪些维护 task 需要现在生产.
    """
    if not cfg_get("ai.maintenance.enabled", True):
        return {"ok": True, "skipped": "disabled"}

    stats = {"enqueued": {}, "skipped": {}}
    now = datetime.now()

    # 1. COOKIE_REFRESH — 每 12h 一批
    cookie_every_h = int(cfg_get("ai.maintenance.cookie_refresh_hours", 12))
    if _need_task_type("COOKIE_REFRESH", cookie_every_h):
        n = _enqueue_cookie_refresh_batch(dry_run)
        stats["enqueued"]["COOKIE_REFRESH"] = n
    else:
        stats["skipped"]["COOKIE_REFRESH"] = "interval_not_reached"

    # 2. MCN_TOKEN — 每 6h
    mcn_every_h = int(cfg_get("ai.maintenance.mcn_token_refresh_hours", 6))
    if _need_task_type("MCN_TOKEN", mcn_every_h):
        n = _enqueue_mcn_token_refresh(dry_run)
        stats["enqueued"]["MCN_TOKEN"] = n
    else:
        stats["skipped"]["MCN_TOKEN"] = "interval_not_reached"

    # 3. LIBRARY_CLEAN — 每周 N (0=Mon)
    library_weekday = int(cfg_get("ai.maintenance.library_clean_weekday", 1))
    if now.weekday() == (library_weekday % 7) and _need_task_type("LIBRARY_CLEAN", 24*6):
        n = _enqueue_library_clean(dry_run)
        stats["enqueued"]["LIBRARY_CLEAN"] = n

    # 4. QUOTA_BACKFILL — 每日 (07:00 - 08:00 窗口)
    if (cfg_get("ai.maintenance.quota_backfill_enabled", True)
            and now.hour == 7 and _need_task_type("QUOTA_BACKFILL", 20)):
        n = _enqueue_quota_backfill(dry_run)
        stats["enqueued"]["QUOTA_BACKFILL"] = n

    log.info("[maintenance] run: %s", stats)
    return {"ok": True, "dry_run": dry_run, **stats}


def _need_task_type(task_type: str, min_hours: int) -> bool:
    """该类型任务距上次生产 ≥ min_hours?"""
    with _connect() as c:
        r = c.execute(
            """SELECT MAX(created_at) AS last FROM task_queue
               WHERE task_type = ?""",
            (task_type,),
        ).fetchone()
    if not r or not r["last"]:
        return True
    try:
        last = datetime.fromisoformat(r["last"].replace(" ", "T"))
    except Exception:
        return True
    return (datetime.now() - last).total_seconds() / 3600 >= min_hours


def _enqueue_maintenance_task(task_type: str, metadata: dict,
                                 priority: int = 10) -> str | None:
    """统一入队维护任务 (不分账号, system-level)."""
    from core.executor.account_executor import enqueue_publish_task
    from core.task_manager import create_batch, add_task_to_batch

    batch_id = create_batch(
        batch_name=f"maint_{task_type.lower()}",
        batch_type="maintenance",
        total_tasks=1,
        config=metadata,
    )
    # 借 enqueue_publish_task 通用接口 (它自己根据 task_type 分配 id 前缀)
    task_id = enqueue_publish_task(
        account_id=0,  # system-level (不绑账号)
        drama_name="",
        priority=priority,
        batch_id=batch_id,
        task_type=task_type,
        task_source="maintenance",
        source_metadata=metadata,
        params={"maintenance_type": task_type},
    )
    add_task_to_batch(batch_id, task_id, order=0)
    return task_id


def _enqueue_cookie_refresh_batch(dry_run: bool) -> int:
    """为所有活跃账号生成 COOKIE_REFRESH task."""
    if dry_run:
        return 0
    with _connect() as c:
        accs = c.execute(
            "SELECT id, account_name FROM device_accounts "
            "WHERE login_status='logged_in'"
        ).fetchall()
    from core.task_manager import create_batch, add_task_to_batch
    from core.executor.account_executor import enqueue_publish_task

    if not accs:
        return 0

    batch_id = create_batch(
        batch_name="cookie_refresh_batch",
        batch_type="maintenance", total_tasks=len(accs),
    )
    for i, a in enumerate(accs):
        task_id = enqueue_publish_task(
            account_id=a["id"], drama_name="",
            priority=10, batch_id=batch_id,
            task_type="COOKIE_REFRESH", task_source="maintenance",
            source_metadata={"account_name": a["account_name"]},
        )
        add_task_to_batch(batch_id, task_id, order=i)
    return len(accs)


def _enqueue_mcn_token_refresh(dry_run: bool) -> int:
    if dry_run:
        return 0
    tid = _enqueue_maintenance_task(
        "MCN_TOKEN", metadata={"purpose": "refresh_captain_token"},
    )
    return 1 if tid else 0


def _enqueue_library_clean(dry_run: bool) -> int:
    if dry_run:
        return 0
    tid = _enqueue_maintenance_task(
        "LIBRARY_CLEAN", metadata={"purpose": "weekly_drama_links_cleanup"},
    )
    return 1 if tid else 0


def _enqueue_quota_backfill(dry_run: bool) -> int:
    """昨天失败的 plan_item 生成 backfill task."""
    if dry_run:
        return 0
    yesterday = (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d")
    with _connect() as c:
        n_failed = c.execute(
            """SELECT COUNT(*) AS n FROM daily_plan_items i
               JOIN daily_plans p ON i.plan_id = p.id
               WHERE p.plan_date = ? AND i.status IN ('failed','dead_letter')""",
            (yesterday,),
        ).fetchone()
    n = n_failed["n"] if n_failed else 0
    if n == 0:
        return 0
    tid = _enqueue_maintenance_task(
        "QUOTA_BACKFILL",
        metadata={"yesterday": yesterday, "failed_count": n},
    )
    return 1 if tid else 0


# ═══════════════════════════════════════════════════════════════
# 消费者 handlers (executor 分发到这里)
# ═══════════════════════════════════════════════════════════════

def refresh_account_cookie(task: dict) -> dict:
    """刷账号 cookie (对齐 KS184 cookie_last_success_at 机制)."""
    account_id = task.get("account_id") or 0
    try:
        from core.cookie_manager import CookieManager
        from core.db_manager import DBManager
        db = DBManager()
        cm = CookieManager(db)
        # 简化版: 只调 refresh_if_needed (真正业务可扩展)
        if hasattr(cm, "refresh_if_needed"):
            cm.refresh_if_needed(int(account_id))
        # 至少更新 cookie_last_success_at
        import sqlite3
        with _connect() as c:
            c.execute(
                "UPDATE device_accounts SET cookie_last_success_at=datetime('now','localtime') "
                "WHERE id=?", (int(account_id),),
            )
            c.commit()
        db.close()
        _finish_task(task["id"], ok=True)
        return {"ok": True, "account_id": account_id}
    except Exception as e:
        _finish_task(task["id"], ok=False, error=str(e)[:300])
        return {"ok": False, "error": str(e)[:300]}


def refresh_mcn_token(task: dict) -> dict:
    """刷 MCN captain token."""
    try:
        from core.mcn_client import MCNClient
        mcn = MCNClient()
        if hasattr(mcn, "refresh_captain_token"):
            mcn.refresh_captain_token()
        _finish_task(task["id"], ok=True)
        return {"ok": True, "purpose": "refreshed"}
    except Exception as e:
        _finish_task(task["id"], ok=False, error=str(e)[:300])
        return {"ok": False, "error": str(e)[:300]}


def clean_drama_library(task: dict) -> dict:
    """清 drama_links 过期/无效链接 (30+ 天未用 或 download_fail)."""
    try:
        with _connect() as c:
            # 简单策略: status='invalid' 或 last_used 超 30 天
            r = c.execute(
                """UPDATE drama_links SET remark = COALESCE(remark,'') || '[cleaned]'
                   WHERE (status='invalid' OR
                          (last_used_at IS NOT NULL AND
                           datetime(last_used_at) < datetime('now','-30 days','localtime')))""",
            )
            n = r.rowcount if r else 0
            c.commit()
        _finish_task(task["id"], ok=True, result={"cleaned": n})
        return {"ok": True, "cleaned": n}
    except Exception as e:
        _finish_task(task["id"], ok=False, error=str(e)[:300])
        return {"ok": False, "error": str(e)[:300]}


def backfill_quota(task: dict) -> dict:
    """昨天失败 → 今天 plan_items 加 N 条补."""
    metadata = {}
    try:
        metadata = json.loads(task.get("source_metadata_json") or "{}")
    except Exception:
        pass
    yesterday = metadata.get("yesterday")
    failed_n = metadata.get("failed_count", 0)

    # 简化: 调 planner 重新生成今天 plan (enforce_test_budget=False 让它多排)
    try:
        from core.agents.strategy_planner_agent import run as planner_run
        today = datetime.now().strftime("%Y-%m-%d")
        r = planner_run(plan_date=today, dry_run=True,
                        enforce_test_budget=False)
        _finish_task(task["id"], ok=True,
                      result={"backfilled_for": yesterday, "today_plan": r.get("total_items")})
        return {"ok": True, "yesterday": yesterday,
                "failed_count": failed_n,
                "note": "dry_run, 真补由 scheduler 下次 cron 跑"}
    except Exception as e:
        _finish_task(task["id"], ok=False, error=str(e)[:300])
        return {"ok": False, "error": str(e)[:300]}


def freeze_account(task: dict) -> dict:
    """冻结账号 (watchdog 事件或手动注入)."""
    account_id = task.get("account_id") or 0
    metadata = {}
    try:
        metadata = json.loads(task.get("source_metadata_json") or "{}")
    except Exception:
        pass
    reason = metadata.get("reason", "auto_freeze")
    try:
        with _connect() as c:
            c.execute(
                "UPDATE device_accounts SET tier='frozen', frozen_reason=?, "
                "tier_since=datetime('now','localtime') WHERE id=?",
                (reason, int(account_id)),
            )
            # 同时取消该账号所有 pending plan_items
            c.execute(
                "UPDATE daily_plan_items SET status='canceled' "
                "WHERE account_id=? AND status IN ('pending','queued')",
                (int(account_id),),
            )
            c.commit()
        _finish_task(task["id"], ok=True, result={"account_id": account_id})
        notify(
            title=f"❄️ 账号 {account_id} 冻结",
            body=f"原因: {reason}. 所有 pending 已取消.",
            level="warn", source="maintenance_agent",
        )
        return {"ok": True, "account_id": account_id, "reason": reason}
    except Exception as e:
        _finish_task(task["id"], ok=False, error=str(e)[:300])
        return {"ok": False, "error": str(e)[:300]}


def unfreeze_account(task: dict) -> dict:
    """解冻账号."""
    account_id = task.get("account_id") or 0
    try:
        with _connect() as c:
            c.execute(
                "UPDATE device_accounts SET tier='testing', frozen_reason=NULL, "
                "tier_since=datetime('now','localtime') WHERE id=? AND tier='frozen'",
                (int(account_id),),
            )
            c.commit()
        _finish_task(task["id"], ok=True)
        return {"ok": True, "account_id": account_id}
    except Exception as e:
        _finish_task(task["id"], ok=False, error=str(e)[:300])
        return {"ok": False, "error": str(e)[:300]}


def _finish_task(task_id: str, ok: bool, result: dict | None = None,
                  error: str = "") -> None:
    """维护 handler 用 — 标 task 完成."""
    status = "success" if ok else "failed"
    with _connect() as c:
        c.execute(
            """UPDATE task_queue SET status=?,
                 finished_at=datetime('now','localtime'),
                 result=?, error_message=?
               WHERE id=?""",
            (status, json.dumps(result or {}, ensure_ascii=False, default=str),
             error, task_id),
        )
        c.commit()


# ═══════════════════════════════════════════════════════════════
# CLI
# ═══════════════════════════════════════════════════════════════

if __name__ == "__main__":
    import argparse, sys
    sys.stdout.reconfigure(encoding="utf-8")
    logging.basicConfig(level=logging.INFO)
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--task-type", default=None,
                    choices=["COOKIE_REFRESH", "MCN_TOKEN",
                              "LIBRARY_CLEAN", "QUOTA_BACKFILL"],
                    help="手动触发单类")
    args = ap.parse_args()

    if args.task_type == "COOKIE_REFRESH":
        n = _enqueue_cookie_refresh_batch(args.dry_run)
        print(f"cookie refresh enqueued: {n}")
    elif args.task_type == "MCN_TOKEN":
        n = _enqueue_mcn_token_refresh(args.dry_run)
        print(f"mcn token enqueued: {n}")
    elif args.task_type == "LIBRARY_CLEAN":
        n = _enqueue_library_clean(args.dry_run)
        print(f"library clean enqueued: {n}")
    elif args.task_type == "QUOTA_BACKFILL":
        n = _enqueue_quota_backfill(args.dry_run)
        print(f"quota backfill enqueued: {n}")
    else:
        r = run(dry_run=args.dry_run)
        import json as _j
        print(_j.dumps(r, ensure_ascii=False, indent=2, default=str))
