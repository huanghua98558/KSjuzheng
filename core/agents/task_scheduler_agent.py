# -*- coding: utf-8 -*-
"""TaskSchedulerAgent — 每 2h 从 daily_plan_items 拉到期批次, 入 task_queue.

职责:
  1. 查 daily_plan_items status='pending' 且 scheduled_at <= now()
  2. 批量入队 (enqueue_publish_task), 传 recipe / banner_task_id
  3. 更新 plan_items.status='queued' + task_id 关联
  4. Watchdog 检测 task 完成后, 更新 plan_items.status='success/failed'
"""
from __future__ import annotations

import json
import logging
import sqlite3
from datetime import datetime
from typing import Any

from core.app_config import get as cfg_get
from core.executor.account_executor import enqueue_publish_task

log = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────────────
# Week 3 B-3 动态优先级 — tier 基础分 + 超期时间加成 + 失败账号降权
# ─────────────────────────────────────────────────────────────────

_TIER_WEIGHT = {
    "viral": 90, "established": 70,
    "warming_up": 50, "testing": 30, "new": 20,
}


def _compute_dynamic_priority(item: dict, now: datetime) -> int:
    """入队时按 item 当前状态重算 priority (比 planner 写的更智能).

    公式:
      base = tier_weight           (20-90)
      + overdue_bonus              (0-20, 每超期 10min +1)
      - recent_fail_penalty        (0-30, 账号近 1h 失败次数 × 10)
      clamp 到 [0, 100]
    """
    # 1. Tier 基础分
    base = _TIER_WEIGHT.get(item.get("account_tier", ""), 30)

    # 2. Overdue 加成: scheduled_at 超期越久越优先
    overdue_bonus = 0
    if item.get("scheduled_at"):
        try:
            sched_dt = datetime.fromisoformat(item["scheduled_at"])
            overdue_min = (now - sched_dt).total_seconds() / 60
            if overdue_min > 0:
                overdue_bonus = min(20, int(overdue_min / 10))
        except (ValueError, TypeError):
            pass

    # 3. Recent fail penalty: 账号近 1h 失败越多 → 降低优先级 (让别的账号先跑)
    recent_fail_penalty = 0
    try:
        with _connect() as c:
            row = c.execute(
                """SELECT COUNT(*) AS n FROM task_queue
                   WHERE account_id = ?
                     AND status = 'failed'
                     AND finished_at >= datetime('now', '-1 hour', 'localtime')""",
                (str(item["account_id"]),),
            ).fetchone()
            recent_fails = row["n"] if row else 0
            recent_fail_penalty = min(30, recent_fails * 10)
    except Exception:
        pass

    final = base + overdue_bonus - recent_fail_penalty
    return max(0, min(100, final))


def _connect():
    from core.config import DB_PATH
    c = sqlite3.connect(DB_PATH, timeout=30)
    c.execute("PRAGMA busy_timeout=30000")
    c.execute("PRAGMA journal_mode=WAL")
    c.execute("PRAGMA synchronous=NORMAL")
    c.row_factory = sqlite3.Row
    return c


def _due_items(now: datetime, limit: int = 100) -> list[dict]:
    """今天的 pending + 到期的 plan items."""
    today = now.strftime("%Y-%m-%d")
    with _connect() as c:
        rows = c.execute("""
            SELECT i.* FROM daily_plan_items i
            JOIN daily_plans p ON i.plan_id = p.id
            WHERE p.plan_date = ?
              AND i.status = 'pending'
              AND (i.scheduled_at IS NULL OR i.scheduled_at <= ?)
            ORDER BY i.priority DESC, i.scheduled_at ASC
            LIMIT ?
        """, (today, now.strftime("%Y-%m-%d %H:%M:%S"), limit)).fetchall()
    return [dict(r) for r in rows]


# ─────────────────────────────────────────────────────────────────
# ★ Path 2 (2026-04-20): scheduler 入队前最后一道闸 — blacklist 拦截
# 防御纵深: planner 早 8:00 跑过, 但 sync_mcn_full 04:00 之后任意时刻可能新增黑名单,
# scheduler 每 2h 跑, 是任务进 queue 之前最后一次校验.
# ─────────────────────────────────────────────────────────────────

def _check_blacklist(drama_name: str) -> tuple[bool, str | None]:
    """检查 drama 是否在 active 黑名单. Returns (blocked, reason)."""
    if not cfg_get("ai.scheduler.blacklist.enforce", True):
        return False, None
    try:
        with _connect() as c:
            r = c.execute(
                "SELECT status, violation_type, violation_reason FROM drama_blacklist "
                "WHERE drama_name = ? AND status = 'active' LIMIT 1",
                (drama_name,)
            ).fetchone()
            if r:
                reason = (r["violation_reason"] or r["violation_type"]
                          or "active blacklist")[:200]
                return True, reason
    except Exception as e:
        log.warning("[scheduler] blacklist check failed: %s", e)
    return False, None


def _record_blacklist_diagnosis(item: dict, reason: str) -> None:
    """命中 active 黑名单 → 写 healing_diagnoses + 标 plan_item.status='blacklisted'."""
    try:
        with _connect() as c:
            # 1. 标 plan_item
            c.execute(
                """UPDATE daily_plan_items
                   SET status='blacklisted',
                       reason=COALESCE(reason,'') || ' | BLOCKED: ' || ?
                   WHERE id=?""",
                (reason[:100], item["id"]),
            )
            # 2. 写 healing_diagnoses (playbook_code='mcn_blacklist_hit')
            try:
                c.execute(
                    """INSERT INTO healing_diagnoses
                       (playbook_code, task_type, evidence_json,
                        affected_entities, diagnosis, confidence, severity)
                       VALUES (?,?,?,?,?,?,?)""",
                    (
                        "mcn_blacklist_hit",
                        "scheduler.enqueue",
                        json.dumps({
                            "plan_item_id": item["id"],
                            "account_id": item["account_id"],
                            "drama_name": item["drama_name"],
                            "blacklist_reason": reason,
                        }, ensure_ascii=False),
                        json.dumps([
                            f"drama:{item['drama_name']}",
                            f"plan_item:{item['id']}",
                            f"account:{item['account_id']}",
                        ], ensure_ascii=False),
                        f"drama '{item['drama_name']}' MCN active blacklist hit, "
                        f"plan_item blocked before enqueue. reason={reason[:80]}",
                        0.95,            # confidence (MCN 直接信号)
                        "warning",
                    )
                )
            except Exception as _e:
                # healing_diagnoses 表结构可能不同 (老 schema), 不阻塞主流程
                log.debug("[scheduler] healing_diagnoses insert skipped: %s", _e)
            c.commit()
    except Exception as e:
        log.warning("[scheduler] record_blacklist_diagnosis failed: %s", e)


def run(dry_run: bool = False, limit: int = 100) -> dict[str, Any]:
    """主入口. 把到期 plan_items 入队.

    可重入 (pending → queued 是原子的).
    """
    now = datetime.now()
    items = _due_items(now, limit=limit)
    log.info("[scheduler] %d 条到期 plan_items", len(items))

    enqueued = 0
    errors = 0
    blacklisted = 0   # ★ Path 2: 命中 active 黑名单被拦截的数量
    frozen_skipped = 0  # ★ 2026-04-22 §28_D: 账号 enqueue 时已冻结, 跳过
    enqueued_tasks = []
    blacklisted_items = []
    frozen_items = []

    # 预加载当前 tier=frozen 账号集合 (避免每 item 查一次 DB)
    with _connect() as c:
        frozen_ids = {r[0] for r in c.execute(
            "SELECT id FROM device_accounts WHERE tier='frozen'"
        ).fetchall()}
    log.info("[scheduler] %d frozen accounts pre-filter", len(frozen_ids))

    for item in items:
        # ★ 2026-04-22 §28_D: 账号在 planner 之后被冻结 → 跳过不入队
        # 背景: 今日 acct=5 早 03:20 planner 分任务, 04:45 被 sync_account_health 冻结,
        #       scheduler 入队后被 mcn_preflight 拒 dead_letter (3 次重试浪费).
        acct_id_int = None
        try:
            acct_id_int = int(item.get("account_id"))
        except Exception:
            pass
        if acct_id_int is not None and acct_id_int in frozen_ids:
            frozen_skipped += 1
            frozen_items.append({
                "item_id": item["id"],
                "account_id": acct_id_int,
                "drama_name": item.get("drama_name"),
            })
            if not dry_run:
                with _connect() as c:
                    c.execute(
                        """UPDATE daily_plan_items
                           SET status='account_frozen',
                               reason=COALESCE(reason,'') || ' [scheduler: account frozen after plan]'
                           WHERE id=?""",
                        (item["id"],),
                    )
                    c.commit()
            log.warning(
                "[scheduler] FROZEN-SKIP plan_item %s acct=%s drama=%s",
                item["id"], acct_id_int, item.get("drama_name")
            )
            continue

        # ★ Path 2 (2026-04-20): active 黑名单最后一道闸 (defense-in-depth)
        is_bl, bl_reason = _check_blacklist(item["drama_name"])
        if is_bl:
            blacklisted += 1
            blacklisted_items.append({
                "item_id": item["id"],
                "account_id": item["account_id"],
                "drama_name": item["drama_name"],
                "reason": bl_reason,
            })
            if not dry_run:
                _record_blacklist_diagnosis(item, bl_reason or "")
            log.warning(
                "[scheduler] BLOCKED plan_item %s drama=%s reason=%s",
                item["id"], item["drama_name"], (bl_reason or "")[:80]
            )
            continue   # 跳过, 不入队

        if dry_run:
            enqueued += 1
            enqueued_tasks.append({"item_id": item["id"],
                                    "account_id": item["account_id"],
                                    "drama_name": item["drama_name"]})
            continue

        try:
            # B-3 动态优先级 (入队时重算, 比 planner 写的更智能)
            dyn_priority = _compute_dynamic_priority(item, now)
            # ★ E-3: recipe_config 从 plan_item 读 (migrate_v23 加的字段)
            recipe_config = None
            rc_json = item.get("recipe_config_json")
            if rc_json:
                try:
                    import json as _j
                    recipe_config = _j.loads(rc_json)
                except Exception:
                    pass

            # ★ P2-7: 识别实验 item, 改 task_source + 传 experiment_group
            exp_group = item.get("experiment_group")
            task_source = "experiment" if exp_group else "planner"

            task_id = enqueue_publish_task(
                account_id=item["account_id"],
                drama_name=item["drama_name"],
                banner_task_id=item.get("banner_task_id") or None,
                priority=dyn_priority,
                batch_id=f"plan_{item['plan_id']}",
                task_source=task_source,                # ★ P2-7
                experiment_group=exp_group,              # ★ P2-7
                params={
                    "process_recipe": item.get("recipe"),
                    # ★ E-3 硬断修复: 把 image_mode 和 recipe_config 真传下去
                    "image_mode": item.get("image_mode") or None,
                    "recipe_config": recipe_config,
                    "account_tier": item.get("account_tier"),
                    "plan_item_id": item["id"],
                    "planner_priority": item.get("priority") or 50,
                    "dynamic_priority": dyn_priority,
                    "experiment_group": exp_group,        # ★ P2-7
                },
            )
            # 标 plan_item 为 queued
            with _connect() as c:
                c.execute("""
                    UPDATE daily_plan_items
                    SET status='queued', task_id=?
                    WHERE id=?
                """, (task_id, item["id"]))
                # ★ E-3 硬断修复: 回写 decision_history.task_id (Layer 1 记忆链)
                # 之前 planner 写入时 task_id=None, 现在 scheduler 入队后填上,
                # analyzer verdict 回路才能 JOIN 到对应的 decision 记录.
                try:
                    c.execute("""
                        UPDATE account_decision_history
                        SET task_id = ?
                        WHERE plan_item_id = ?
                          AND (task_id IS NULL OR task_id = '')
                    """, (task_id, item["id"]))
                except Exception as _e:
                    log.debug("[scheduler] update decision_history.task_id failed: %s", _e)
                # ★ P2-7: 回写 experiment_assignments.task_id (JOIN 用)
                if exp_group:
                    try:
                        c.execute("""
                            UPDATE experiment_assignments
                            SET task_id = ?,
                                updated_at = datetime('now','localtime')
                            WHERE account_id = ? AND drama_name = ?
                              AND group_name = ?
                              AND (task_id IS NULL OR task_id = '')
                        """, (task_id, str(item["account_id"]),
                              item["drama_name"], exp_group))
                    except Exception as _e:
                        log.debug("[scheduler] update experiment_assignments.task_id failed: %s", _e)
                c.commit()
            enqueued += 1
            enqueued_tasks.append({"item_id": item["id"],
                                    "task_id": task_id,
                                    "account_id": item["account_id"],
                                    "drama_name": item["drama_name"],
                                    "image_mode": item.get("image_mode"),
                                    "experiment_group": exp_group})
        except Exception as e:
            log.warning("[scheduler] enqueue item %s failed: %s", item["id"], e)
            errors += 1

    return {
        "now": now.isoformat(timespec="seconds"),
        "due_items": len(items),
        "enqueued": enqueued,
        "errors": errors,
        "blacklisted": blacklisted,                      # ★ Path 2
        "frozen_skipped": frozen_skipped,                # ★ §28_D
        "dry_run": dry_run,
        "enqueued_tasks_preview": enqueued_tasks[:5],
        "blacklisted_items_preview": blacklisted_items[:5],   # ★ Path 2
        "frozen_items_preview": frozen_items[:5],        # ★ §28_D
    }


def trigger_next_for_account(account_id: str | int) -> dict:
    """★ Week 3 B-2 事件驱动补排.

    任何 worker 跑完一个 task 后立即调用, 看同账号是否还有 pending plan_item 可入队.
    不等定时 cron (每 2h 扫), 让账号 "一条完就立即排下一条" 提升吞吐.

    幂等:
      - 如果同账号还有 running task → 什么都不做 (账号忙)
      - 如果没 pending plan_item 到期 → 什么都不做
      - 否则挑最高优先级的一条入队 + 更新 plan_item.status=queued
    """
    now = datetime.now()
    today = now.strftime("%Y-%m-%d")

    with _connect() as c:
        # 先查账号是否还有 active task (双重校验, 避免并发重排)
        active = c.execute(
            """SELECT COUNT(*) AS n FROM task_queue
               WHERE account_id=? AND status IN ('queued', 'running')""",
            (str(account_id),),
        ).fetchone()
        if active["n"] > 0:
            return {"triggered": False, "reason": "account_still_busy",
                    "active_tasks": active["n"]}

        # 挑同账号最高优先级的 pending plan_item (最早 scheduled)
        row = c.execute(
            """SELECT i.* FROM daily_plan_items i
               JOIN daily_plans p ON i.plan_id = p.id
               WHERE p.plan_date = ?
                 AND i.status = 'pending'
                 AND i.account_id = ?
                 AND (i.scheduled_at IS NULL OR i.scheduled_at <= ?)
               ORDER BY i.priority DESC, i.scheduled_at ASC
               LIMIT 1""",
            (today, str(account_id),
             now.strftime("%Y-%m-%d %H:%M:%S")),
        ).fetchone()
        if not row:
            return {"triggered": False, "reason": "no_pending_plan_item",
                    "account_id": account_id}

        item = dict(row)

    # 出锁块后入队 (enqueue 自己连自己 DB)
    try:
        dyn_priority = _compute_dynamic_priority(item, now)
        # ★ E-3: recipe_config + image_mode 与 run() 逻辑保持一致
        recipe_config = None
        rc_json = item.get("recipe_config_json")
        if rc_json:
            try:
                import json as _j
                recipe_config = _j.loads(rc_json)
            except Exception:
                pass

        # ★ P2-7: event-driven 路径同样支持 experiment_group
        exp_group = item.get("experiment_group")
        task_source = "experiment" if exp_group else "planner"

        task_id = enqueue_publish_task(
            account_id=item["account_id"],
            drama_name=item["drama_name"],
            banner_task_id=item.get("banner_task_id") or None,
            priority=dyn_priority,
            batch_id=f"plan_{item['plan_id']}",
            task_source=task_source,            # ★ P2-7
            experiment_group=exp_group,          # ★ P2-7
            params={
                "process_recipe": item.get("recipe"),
                "image_mode": item.get("image_mode") or None,  # ★ E-3
                "recipe_config": recipe_config,                # ★ E-3
                "account_tier": item.get("account_tier"),
                "plan_item_id": item["id"],
                "trigger": "event_driven",
                "planner_priority": item.get("priority") or 50,
                "dynamic_priority": dyn_priority,
                "experiment_group": exp_group,                 # ★ P2-7
            },
        )
        with _connect() as c:
            c.execute(
                "UPDATE daily_plan_items SET status='queued', task_id=? WHERE id=?",
                (task_id, item["id"]),
            )
            # ★ E-3: 回写 decision_history.task_id
            try:
                c.execute("""
                    UPDATE account_decision_history
                    SET task_id = ?
                    WHERE plan_item_id = ?
                      AND (task_id IS NULL OR task_id = '')
                """, (task_id, item["id"]))
            except Exception as _e:
                log.debug("[scheduler/event] update decision_history.task_id failed: %s", _e)
            # ★ P2-7: 回写 experiment_assignments.task_id
            if exp_group:
                try:
                    c.execute("""
                        UPDATE experiment_assignments
                        SET task_id = ?,
                            updated_at = datetime('now','localtime')
                        WHERE account_id = ? AND drama_name = ?
                          AND group_name = ?
                          AND (task_id IS NULL OR task_id = '')
                    """, (task_id, str(item["account_id"]),
                          item["drama_name"], exp_group))
                except Exception as _e:
                    log.debug("[scheduler/event] update experiment_assignments.task_id failed: %s", _e)
            c.commit()
        log.info("[scheduler] event-driven enqueue account=%s drama=%s item=%d task=%s",
                 account_id, item["drama_name"], item["id"], task_id)
        return {"triggered": True, "task_id": task_id,
                "account_id": account_id, "drama_name": item["drama_name"]}
    except Exception as e:
        log.warning("[scheduler] trigger_next_for_account failed: %s", e)
        return {"triggered": False, "reason": "enqueue_exception", "error": str(e)}


def sync_plan_item_status() -> dict:
    """从 task_queue 回写 plan_items.status (由 Watchdog 周期调用)."""
    with _connect() as c:
        rows = c.execute("""
            SELECT i.id, i.task_id, t.status AS task_status
            FROM daily_plan_items i
            LEFT JOIN task_queue t ON i.task_id = t.id
            WHERE i.status IN ('queued', 'running')
              AND i.task_id IS NOT NULL
        """).fetchall()

        updates = 0
        for r in rows:
            new_status = r["task_status"]
            if new_status in ("success", "failed", "dead_letter", "canceled"):
                c.execute("UPDATE daily_plan_items SET status=? WHERE id=?",
                          (new_status, r["id"]))
                updates += 1
            elif new_status == "running":
                c.execute("UPDATE daily_plan_items SET status='running' WHERE id=?",
                          (r["id"],))
                updates += 1
        c.commit()
    return {"synced": updates}


if __name__ == "__main__":
    import sys, json as _j
    sys.stdout.reconfigure(encoding="utf-8")
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--sync", action="store_true", help="同步 plan_items status from task_queue")
    args = ap.parse_args()
    if args.sync:
        print(_j.dumps(sync_plan_item_status(), ensure_ascii=False, indent=2))
    else:
        print(_j.dumps(run(dry_run=args.dry_run), ensure_ascii=False, indent=2, default=str))
