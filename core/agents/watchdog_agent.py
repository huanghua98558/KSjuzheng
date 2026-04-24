# -*- coding: utf-8 -*-
"""WatchdogAgent — 每 5-10min 跑, 实时监控 + 自动冻结异常账号.

检查:
  1. 近 1h 总失败率 > 阈值 → 通知
  2. 单账号连续 N 次失败 → 冻结账号 (tier=frozen)
  3. task_queue 里 running 超过 1h → 视为 stuck, 取消
  4. 同步 daily_plan_items 状态 (从 task_queue 回传)
"""
from __future__ import annotations

import logging
import sqlite3
from datetime import datetime, timedelta
from typing import Any

from core.account_tier import transition
from core.agents.task_scheduler_agent import sync_plan_item_status
from core.app_config import get as cfg_get
from core.notifier import notify

log = logging.getLogger(__name__)


def _connect():
    from core.config import DB_PATH
    c = sqlite3.connect(DB_PATH, timeout=30)
    c.execute("PRAGMA busy_timeout=30000")
    c.execute("PRAGMA journal_mode=WAL")
    c.execute("PRAGMA synchronous=NORMAL")
    c.row_factory = sqlite3.Row
    return c


def _check_fail_rate_1h() -> dict:
    """近 1 小时总失败率."""
    threshold = cfg_get("ai.watchdog.fail_rate_threshold", 0.4)
    with _connect() as c:
        stats = c.execute("""
            SELECT
              COUNT(*) AS n,
              SUM(CASE WHEN status='success'      THEN 1 ELSE 0 END) AS succ,
              SUM(CASE WHEN status='failed'       THEN 1 ELSE 0 END) AS fail,
              SUM(CASE WHEN status='dead_letter'  THEN 1 ELSE 0 END) AS dead
            FROM task_queue
            WHERE finished_at IS NOT NULL
              AND datetime(finished_at) >= datetime('now', '-1 hour')
        """).fetchone()
    n = stats["n"] or 0
    fail = (stats["fail"] or 0) + (stats["dead"] or 0)
    rate = fail / n if n else 0.0
    alert = n >= 5 and rate > threshold
    if alert:
        notify(
            title=f"⚠️ 1h 失败率 {rate:.0%}",
            body=f"近 1h task_queue: 总 {n}, 成功 {stats['succ']}, 失败 {fail}. "
                 f"阈值 {threshold:.0%}",
            level="warning", source="watchdog",
            extra={"n": n, "fail_rate": rate, "threshold": threshold},
        )
    return {"n": n, "succ": stats["succ"] or 0, "fail": fail,
            "rate": round(rate, 3), "alert": alert}


def _freeze_consecutive_fail_accounts() -> list[dict]:
    """连续 N 次同账号失败 → 冻结. 但 download:* 错误不计 (是 drama 问题不是号问题).

    2026-04-21 fix: URL 过期级联冻号问题根因 — 改为只算 "账号侧" 错误.
                    download:no_urls / download:all_urls_failed → 不计, 由 drama
                    cooldown 机制处理. 阈值也从 5 提到 10 加宽容度.

    ★ 2026-04-22 §28_C: 细化阈值 — Session/Auth 错误 (result=109/112) 用严格 3 次阈值
                        (cookie 刷新明显无效 → 尽快冻, 避免 self_healing 无限循环).
                        其他账号级错误保留 10 次.
    """
    n_fail_general = int(cfg_get("ai.watchdog.consecutive_fail_pause", 10))
    n_fail_session = int(cfg_get("ai.watchdog.session_fail_threshold", 3))
    # ★ 2026-04-23 修 4: 80004 "无作者变现权限" 独立阈值 (3 次就冻, 30 天)
    # 本质: 账号未在快手开通萤光作者变现 → 任何发布必 80004 (协议 OK 业务拒)
    # 方案: 冻结 30 天等账号主去 cp.kuaishou.com 人工申请萤光后手动 unfreeze
    n_fail_monetization = int(cfg_get("ai.watchdog.monetization_fail_threshold", 3))
    exclude_dl = bool(cfg_get("ai.watchdog.exclude_download_errors", True))

    # 过滤条件: 排除非账号侧错误
    base_filter = ""
    if exclude_dl:
        base_filter = (
            "AND (error_message IS NULL OR "
            "     (error_message NOT LIKE 'download:%' "
            "      AND error_message NOT LIKE 'process:%' "
            "      AND error_message NOT LIKE 'mcn_preflight:already_frozen:%'))"
        )

    # session/auth 错误模式 (更严格)
    session_err_pattern = (
        "error_message LIKE '%result=109%' OR "
        "error_message LIKE '%result=112%' OR "
        "error_message LIKE '%result=120%' OR "
        "error_message LIKE '%auth_expired%' OR "
        "error_message LIKE '%loginUrl%passToken%'"
    )

    # ★ 2026-04-23 修 4: 80004 "无作者变现权限" 模式 (需账号主手工开通萤光)
    monetization_err_pattern = (
        "error_message LIKE '%80004%' OR "
        "error_message LIKE '%无作者变现权限%'"
    )

    frozen = []
    with _connect() as c:
        # ── Path A: session 类严重错误, 3 次就冻 ──
        rows_session = c.execute(f"""
            SELECT account_id, COUNT(*) AS n,
                   GROUP_CONCAT(SUBSTR(error_message,1,50), ' | ') AS samples
            FROM task_queue
            WHERE status IN ('failed', 'dead_letter')
              AND datetime(finished_at) >= datetime('now', '-2 hours')
              AND ({session_err_pattern})
              {base_filter}
            GROUP BY account_id
            HAVING n >= {n_fail_session}
        """).fetchall()

        # ── Path B: 其他账号级错误, 10 次阈值 ──
        rows_general = c.execute(f"""
            SELECT account_id, COUNT(*) AS n
            FROM task_queue
            WHERE status IN ('failed', 'dead_letter')
              AND datetime(finished_at) >= datetime('now', '-2 hours')
              {base_filter}
            GROUP BY account_id
            HAVING n >= {n_fail_general}
        """).fetchall()

        # ── Path C: 80004 无变现权限, 3 次就冻 30 天 ──
        # ★ 2026-04-23 修 4: 账号没开通萤光变现, 要账号主手工去快手申请
        rows_monetization = c.execute(f"""
            SELECT account_id, COUNT(*) AS n,
                   GROUP_CONCAT(SUBSTR(error_message,1,60), ' | ') AS samples
            FROM task_queue
            WHERE status IN ('failed', 'dead_letter')
              AND datetime(finished_at) >= datetime('now', '-24 hours')
              AND ({monetization_err_pattern})
              {base_filter}
            GROUP BY account_id
            HAVING n >= {n_fail_monetization}
        """).fetchall()

    # 合并 — session + monetization 类优先, 避免同账号双冻
    session_aids = {int(r["account_id"]) for r in rows_session
                     if r["account_id"] and str(r["account_id"]).isdigit()}
    monetization_aids = {int(r["account_id"]) for r in rows_monetization
                         if r["account_id"] and str(r["account_id"]).isdigit()}

    # ── Path C: 80004 冻结 30 天 (等账号主手工开通萤光) ──
    for r in rows_monetization:
        aid_str = r["account_id"]
        try:
            aid = int(aid_str)
        except Exception:
            continue
        acc = None
        with _connect() as c:
            acc = c.execute(
                "SELECT tier, account_name FROM device_accounts WHERE id=?",
                (aid,)).fetchone()
        if not acc or acc["tier"] == "frozen":
            continue
        reason = (f"80004 无作者变现权限 {r['n']} 次 (≥{n_fail_monetization}, 近 24h). "
                  f"账号主需登录 cp.kuaishou.com → 创作者中心 → 萤光计划 申请变现. "
                  f"30 天后自动回 testing, 或人工 unfreeze.")
        transition(aid, "frozen",
                    reason=reason,
                    metrics={"consecutive_80004": r["n"], "trigger": "monetization_locked",
                             "freeze_hours": 720})
        frozen.append({"account_id": aid, "account_name": acc["account_name"],
                        "n_fail": r["n"], "reason_type": "monetization_locked"})
        notify(
            title=f"🔒 账号冻结 (未开通变现): {acc['account_name']}",
            body=(f"24h 内 80004 错误 {r['n']} 次, 已迁 tier=frozen 30 天.\n"
                  f"请账号主登录快手 cp.kuaishou.com 申请萤光作者变现后手工 unfreeze."),
            level="warn", source="watchdog",
            extra={"account_id": aid, "n_fail": r["n"], "type": "monetization_locked"},
        )

    for r in rows_session:
        aid_str = r["account_id"]
        try:
            aid = int(aid_str)
        except Exception:
            continue
        acc = None
        with _connect() as c:
            acc = c.execute(
                "SELECT tier, account_name FROM device_accounts WHERE id=?",
                (aid,)).fetchone()
        if not acc or acc["tier"] == "frozen":
            continue
        reason = f"Session 错误 {r['n']} 次 (≥{n_fail_session}, 近 2h): {(r['samples'] or '')[:100]}"
        transition(aid, "frozen",
                    reason=reason,
                    metrics={"consecutive_session_failures": r["n"], "trigger": "session_fail_threshold"})
        frozen.append({"account_id": aid, "account_name": acc["account_name"],
                        "n_fail": r["n"], "reason_type": "session"})
        notify(
            title=f"🚨 账号冻结 (Session): {acc['account_name']}",
            body=f"近 2h session 错误 {r['n']} 次 (result=109/112/auth_expired), 已迁 tier=frozen",
            level="error", source="watchdog",
            extra={"account_id": aid, "n_fail": r["n"], "type": "session"},
        )

    # 通用失败 — 跳过已因 session 冻结的
    for r in rows_general:
        aid_str = r["account_id"]
        try:
            aid = int(aid_str)
        except Exception:
            continue
        if aid in session_aids or aid in monetization_aids:
            continue   # 已冻 (session 或 monetization 类优先)
        acc = None
        with _connect() as c:
            acc = c.execute(
                "SELECT tier, account_name FROM device_accounts WHERE id=?",
                (aid,)).fetchone()
        if not acc or acc["tier"] == "frozen":
            continue
        transition(aid, "frozen",
                    reason=f"连续 {r['n']} 次账号级失败 (近 2h, 已排除 download:*)",
                    metrics={"consecutive_failures": r["n"], "excluded_download": exclude_dl})
        frozen.append({"account_id": aid, "account_name": acc["account_name"],
                        "n_fail": r["n"], "reason_type": "general"})
        notify(
            title=f"🚨 账号冻结: {acc['account_name']}",
            body=f"近 2h 连续 {r['n']} 次账号级失败 ≥ {n_fail_general}, 已迁 tier=frozen",
            level="error", source="watchdog",
            extra={"account_id": aid, "n_fail": r["n"]},
        )
    return frozen


# ─────────────────────────────────────────────────────────────────
# 2026-04-21 ★ drama-level cooldown: URL 级联失败冷却 drama 而非冻号
# 逻辑: 如果一个 drama 在近 N 小时内被 ≥ M 个账号 download 失败,
# 就给这个 drama 冷却 K 小时 (写 drama_links.cooldown_until).
# planner/match_scorer 会跳过冷却中的 drama, 从而避免反复给失败剧派任务.
# ─────────────────────────────────────────────────────────────────

def _detect_drama_url_cooldown() -> list[dict]:
    """检测 URL 级联失败的 drama → 写 cooldown_until."""
    if not cfg_get("ai.watchdog.drama_cooldown.enabled", True):
        return []
    threshold = int(cfg_get("ai.watchdog.drama_cooldown.threshold", 3))
    window_hours = int(cfg_get("ai.watchdog.drama_cooldown.window_hours", 2))
    cooldown_hours = int(cfg_get("ai.watchdog.drama_cooldown.hours", 48))
    min_accounts = int(cfg_get("ai.watchdog.drama_cooldown.min_accounts", 2))

    cooled = []
    try:
        with _connect() as c:
            # 找 download 失败的剧: 近 window_hours 内失败数 >= threshold 且涉及 >= min_accounts 个账号
            rows = c.execute(f"""
                SELECT drama_name,
                       COUNT(*) AS n_fail,
                       COUNT(DISTINCT account_id) AS n_acc
                FROM task_queue
                WHERE status IN ('failed','dead_letter')
                  AND drama_name IS NOT NULL AND drama_name != ''
                  AND (error_message LIKE 'download:%' OR error_message LIKE 'process:%')
                  AND datetime(finished_at) >= datetime('now', '-{window_hours} hours')
                GROUP BY drama_name
                HAVING n_fail >= {threshold} AND n_acc >= {min_accounts}
            """).fetchall()

            for r in rows:
                dname = r["drama_name"]
                n_fail = r["n_fail"]
                n_acc = r["n_acc"]

                # 检查是否已在冷却期 (跳过)
                cd = c.execute(
                    "SELECT MAX(cooldown_until) FROM drama_links WHERE drama_name=?",
                    (dname,)
                ).fetchone()
                if cd and cd[0]:
                    try:
                        from datetime import datetime as _dt
                        cd_until = _dt.fromisoformat(str(cd[0]).replace("Z", "+00:00").split(".")[0])
                        if cd_until.replace(tzinfo=None) > datetime.now():
                            continue   # 还在冷却中, 不重复处理
                    except Exception:
                        pass

                # 写 cooldown_until (rowcount 只在 cursor 上, 不在 connection 上)
                cur = c.execute(f"""
                    UPDATE drama_links
                    SET cooldown_until = datetime('now', '+{cooldown_hours} hours'),
                        cooldown_reason = ?,
                        cooldown_hit_count = COALESCE(cooldown_hit_count, 0) + 1,
                        updated_at = datetime('now')
                    WHERE drama_name=?
                """, (f"URL 级联失败: {n_fail} 次, {n_acc} 账号 (近 {window_hours}h)", dname))
                updated = cur.rowcount

                # 写 healing_diagnoses
                try:
                    import json as _j
                    c.execute("""
                        INSERT INTO healing_diagnoses
                        (playbook_code, task_type, evidence_json, affected_entities,
                         diagnosis, confidence, severity)
                        VALUES (?,?,?,?,?,?,?)
                    """, (
                        "drama_url_cooldown",
                        "PUBLISH",
                        _j.dumps({
                            "drama_name": dname,
                            "n_fail": n_fail,
                            "n_accounts": n_acc,
                            "window_hours": window_hours,
                            "cooldown_hours": cooldown_hours,
                        }, ensure_ascii=False),
                        _j.dumps([f"drama:{dname}"], ensure_ascii=False),
                        f"剧《{dname}》URL 级联失败 ({n_fail} 次/{n_acc} 账号), "
                        f"触发 {cooldown_hours}h 冷却 (更新 {updated} 条 drama_links)",
                        0.9,
                        "warning",
                    ))
                except Exception as _e:
                    log.debug("[watchdog] drama_cooldown diagnosis insert fail: %s", _e)
            c.commit()

            for r in rows:
                dname = r["drama_name"]
                cooled.append({
                    "drama_name": dname,
                    "n_fail": r["n_fail"],
                    "n_accounts": r["n_acc"],
                    "cooldown_hours": cooldown_hours,
                })
    except Exception as e:
        log.exception("[watchdog] _detect_drama_url_cooldown failed")
    return cooled


# ─────────────────────────────────────────────────────────────────
# ★ Path 3 (2026-04-20): MCN photo_violation_log 暴增 → 冻结账号
# 当一个账号在 24h 内被 MCN 标记 N 张违规图 → 立即冻结, 防 ban.
# ─────────────────────────────────────────────────────────────────

def _detect_violation_burst() -> list[dict]:
    """检测 photo_violation_log 暴增的账号 → enqueue FREEZE_ACCOUNT.

    阈值: ai.watchdog.violation_burst.threshold (默认 3)
    窗口: ai.watchdog.violation_burst.window_hours (默认 24)
    冻结时长: ai.watchdog.violation_burst.freeze_hours (默认 24, 写入 freeze task params)
    """
    if not cfg_get("ai.watchdog.violation_burst.enabled", True):
        return []

    threshold = int(cfg_get("ai.watchdog.violation_burst.threshold", 3))
    window_hours = int(cfg_get("ai.watchdog.violation_burst.window_hours", 24))
    freeze_hours = int(cfg_get("ai.watchdog.violation_burst.freeze_hours", 24))

    burst_accounts = []
    try:
        with _connect() as c:
            # 1. 找近窗口内 violation 数 >= threshold 的账号
            rows = c.execute(
                f"""SELECT account_uid, COUNT(*) AS n,
                           GROUP_CONCAT(DISTINCT violation_type) AS types
                   FROM photo_violation_log
                   WHERE datetime(mcn_created_at) >= datetime('now', '-{window_hours} hours')
                   GROUP BY account_uid
                   HAVING n >= ?""",
                (threshold,)
            ).fetchall()

            for r in rows:
                uid = r["account_uid"]
                if not uid:
                    continue
                # 2. 找对应 device_account (numeric_uid → device_accounts.id)
                acc = c.execute(
                    "SELECT id, account_name, tier FROM device_accounts WHERE numeric_uid = ? LIMIT 1",
                    (int(uid),)
                ).fetchone()
                if not acc:
                    log.debug("[watchdog] burst uid=%s no matching account", uid)
                    continue
                if acc["tier"] == "frozen":
                    continue   # 已冻不重复

                # 3. 已经写过同账号 violation_burst diagnosis? (24h 内)
                recent = c.execute(
                    """SELECT 1 FROM healing_diagnoses
                       WHERE playbook_code='account_violation_burst'
                         AND affected_entities LIKE ?
                         AND datetime(created_at) >= datetime('now','-24 hours')
                       LIMIT 1""",
                    (f'%"account:{acc["id"]}"%',)
                ).fetchone()
                if recent:
                    log.debug("[watchdog] burst acc=%s already handled <24h", acc["id"])
                    continue

                # 4. enqueue FREEZE_ACCOUNT (走 maintenance_agent.freeze_account)
                from core.executor.account_executor import enqueue_publish_task
                freeze_reason = (
                    f"MCN photo_violation_log {r['n']} 张 "
                    f"近 {window_hours}h, 类型: {r['types']}"
                )
                try:
                    task_id = enqueue_publish_task(
                        account_id=acc["id"],
                        drama_name="",
                        banner_task_id=None,
                        priority=95,                     # 高优先级 (仅次于 burst=99)
                        batch_id="watchdog_violation_burst",
                        task_source="watchdog",
                        task_type="FREEZE_ACCOUNT",
                        # ★ freeze_account handler 从 source_metadata_json 读 reason
                        source_metadata={
                            "reason": freeze_reason,
                            "freeze_hours": freeze_hours,
                            "violation_count": r["n"],
                            "violation_types": r["types"],
                            "trigger": "watchdog.violation_burst",
                        },
                        params={
                            "freeze_hours": freeze_hours,
                            "reason": freeze_reason,
                            "violation_count": r["n"],
                            "violation_types": r["types"],
                        },
                    )
                except TypeError as _te:
                    task_id = None
                    log.warning("[watchdog] enqueue FREEZE_ACCOUNT signature error: %s", _te)

                # 5. 写 healing_diagnoses
                try:
                    import json as _j
                    c.execute(
                        """INSERT INTO healing_diagnoses
                           (playbook_code, task_type, evidence_json,
                            affected_entities, diagnosis, confidence, severity)
                           VALUES (?,?,?,?,?,?,?)""",
                        (
                            "account_violation_burst",
                            "watchdog.violation_burst",
                            _j.dumps({
                                "account_id": acc["id"],
                                "account_name": acc["account_name"],
                                "numeric_uid": uid,
                                "violation_count": r["n"],
                                "violation_types": r["types"],
                                "window_hours": window_hours,
                                "freeze_hours": freeze_hours,
                                "freeze_task_id": task_id,
                            }, ensure_ascii=False),
                            _j.dumps([
                                f"account:{acc['id']}",
                                f"numeric_uid:{uid}",
                            ], ensure_ascii=False),
                            f"账号 {acc['account_name']} (uid={uid}) "
                            f"近 {window_hours}h 被 MCN 标记 {r['n']} 张违规图 "
                            f"(类型: {r['types']}) → 触发自动冻结 {freeze_hours}h",
                            0.9,
                            "error",
                        )
                    )
                    c.commit()
                except Exception as _e:
                    log.warning("[watchdog] write violation diagnosis failed: %s", _e)

                burst_accounts.append({
                    "account_id": acc["id"],
                    "account_name": acc["account_name"],
                    "numeric_uid": uid,
                    "violation_count": r["n"],
                    "violation_types": r["types"],
                    "freeze_task_id": task_id,
                })

                # 6. notify
                notify(
                    title=f"🚨 账号违规暴增: {acc['account_name']}",
                    body=(f"近 {window_hours}h 被 MCN 标记 {r['n']} 张违规图\n"
                          f"类型: {r['types']}\n"
                          f"已 enqueue FREEZE_ACCOUNT (task={task_id}), "
                          f"冻结 {freeze_hours}h"),
                    level="error", source="watchdog",
                    extra={
                        "account_id": acc["id"],
                        "violation_count": r["n"],
                        "freeze_task_id": task_id,
                    },
                )
    except Exception as e:
        log.exception("[watchdog] _detect_violation_burst failed")

    return burst_accounts


def _cancel_stuck_tasks(max_minutes: int = 90) -> int:
    """running 超过 N 分钟的任务视为 stuck, 取消."""
    with _connect() as c:
        rows = c.execute(f"""
            UPDATE task_queue
            SET status='canceled',
                error_message='watchdog: stuck > {max_minutes}m',
                finished_at=datetime('now','localtime')
            WHERE status='running'
              AND datetime(started_at) < datetime('now', '-{max_minutes} minutes')
        """)
        n = rows.rowcount
        c.commit()
    return n


def run() -> dict[str, Any]:
    """主入口 (每 5-10min 调用)."""
    log.info("[watchdog] tick")
    result = {"ts": datetime.now().isoformat(timespec="seconds")}

    # 1. 失败率
    try: result["fail_rate"] = _check_fail_rate_1h()
    except Exception as e:
        log.exception("[watchdog] fail_rate")
        result["fail_rate_error"] = str(e)

    # 2. 连续失败冻结 (已排除 download:* 错误, 2026-04-21 fix)
    try:
        frozen = _freeze_consecutive_fail_accounts()
        result["frozen"] = frozen
    except Exception as e:
        log.exception("[watchdog] freeze")
        result["freeze_error"] = str(e)

    # ★ 2026-04-21: drama 级 URL 级联失败 → 冷却 drama (不冻账号)
    try:
        cooled = _detect_drama_url_cooldown()
        result["drama_cooled"] = cooled
    except Exception as e:
        log.exception("[watchdog] drama_cooldown")
        result["drama_cooldown_error"] = str(e)

    # ★ Path 3 (2026-04-20): MCN 违规图暴增 → 冻结
    try:
        burst = _detect_violation_burst()
        result["violation_burst"] = burst
    except Exception as e:
        log.exception("[watchdog] violation_burst")
        result["violation_burst_error"] = str(e)

    # 3. stuck 取消
    try:
        stuck = _cancel_stuck_tasks()
        result["stuck_canceled"] = stuck
    except Exception as e:
        log.exception("[watchdog] stuck")
        result["stuck_error"] = str(e)

    # 4. 同步 plan_items 状态
    try:
        sync = sync_plan_item_status()
        result["plan_items_sync"] = sync
    except Exception as e:
        result["plan_sync_error"] = str(e)

    return result


if __name__ == "__main__":
    import sys, json as _j
    sys.stdout.reconfigure(encoding="utf-8")
    print(_j.dumps(run(), ensure_ascii=False, indent=2, default=str))
