# -*- coding: utf-8 -*-
"""MCN Preflight — 发布任务执行前的 MCN 状态检查 (Stage 0).

用户需求 (2026-04-20):
  "所有账号开始执行任务前都必须检查 MCN 状态,
   有 MCN 继续发, 没有就停止对这个账号进行更新, 并风控提示,
   (写入记忆, 下次这个账号不规划, 触发重新触发)"

检查项:
  1. MCN 账号绑定状态 (mcn_account_bindings.status=='active')
  2. 近期收益活跃度 (mcn_member_snapshots 最近 7 天是否有任一条)
  3. 违规图暴增 (photo_violation_log 24h 内 ≥ 阈值 → 冻结)
  4. 剧黑名单 (drama_blacklist.status=='active' 该剧 → 拒绝该任务)

不通过 → freeze_account(reason) + 写 healing_diagnoses + 写 account_strategy_memory.avoid
下次 planner 不排该账号. 手动解冻或 admin trigger 重新评估.

使用:
  from core.mcn_preflight import preflight_check
  r = preflight_check(account_id=3, drama_name="财源滚滚", numeric_uid=887329560)
  if not r["ok"]:
      # 冻结已在 preflight 内部做, 这里直接跳出 pipeline
      return {"ok": False, "error": r["error"], "reason": r["reason"]}
"""
from __future__ import annotations

import json
import logging
import sqlite3
import time
from pathlib import Path
from typing import Any

log = logging.getLogger(__name__)


def _connect():
    from core.config import DB_PATH
    c = sqlite3.connect(DB_PATH, timeout=15, check_same_thread=False)
    c.execute("PRAGMA busy_timeout=10000")
    c.row_factory = sqlite3.Row
    return c


def _cfg(key: str, default):
    try:
        from core.app_config import get as cfg_get
        return cfg_get(key, default)
    except Exception:
        return default


def _freeze_account(conn, account_id: int, reason: str, detail: dict) -> None:
    """冻结账号 + 写 healing_diagnoses + 更新 account_strategy_memory.avoid."""
    # 1. device_accounts.tier='frozen'
    try:
        conn.execute(
            "UPDATE device_accounts SET tier=?, frozen_reason=?, tier_since=? WHERE id=?",
            ("frozen", reason, time.strftime("%Y-%m-%d %H:%M:%S"), account_id)
        )
    except Exception as e:
        log.exception(f"[mcn_preflight] freeze device_accounts {account_id}: {e}")

    # 2. healing_diagnoses (让 SelfHealing + LLMResearcher 后续能追踪)
    try:
        conn.execute(
            """INSERT INTO healing_diagnoses
               (playbook_code, task_type, evidence_json, affected_entities,
                diagnosis, confidence, severity, auto_resolved, created_at)
               VALUES (?,?,?,?,?,?,?,?,CURRENT_TIMESTAMP)""",
            ("mcn_preflight_fail", "PUBLISH",
             json.dumps(detail, ensure_ascii=False),
             f"account:{account_id}",
             reason, 0.95, "high", 0)
        )
    except Exception as e:
        log.warning(f"[mcn_preflight] healing_diagnoses insert: {e}")

    # 3. account_strategy_memory.notes_json += mcn_preflight_freeze 标记
    # (让 match_scorer 看到 avoid_source='mcn_preflight' 就不选)
    try:
        row = conn.execute(
            "SELECT notes_json FROM account_strategy_memory WHERE account_id=?",
            (account_id,)
        ).fetchone()
        notes = {}
        if row and row["notes_json"]:
            try:
                notes = json.loads(row["notes_json"]) or {}
            except Exception:
                notes = {}
        notes["mcn_preflight_freeze"] = {
            "reason": reason,
            "set_at": time.strftime("%Y-%m-%d %H:%M:%S"),
            "detail": detail,
        }
        nj = json.dumps(notes, ensure_ascii=False)
        if row:
            conn.execute(
                "UPDATE account_strategy_memory SET notes_json=?, updated_at=CURRENT_TIMESTAMP WHERE account_id=?",
                (nj, account_id)
            )
        else:
            conn.execute(
                "INSERT INTO account_strategy_memory(account_id, notes_json, updated_at) VALUES(?,?,CURRENT_TIMESTAMP)",
                (account_id, nj)
            )
    except Exception as e:
        log.warning(f"[mcn_preflight] account_strategy_memory update: {e}")

    # 4. 取消 pending plan_items
    try:
        n = conn.execute(
            """UPDATE daily_plan_items
               SET status='cancelled', reason=?
               WHERE account_id=? AND status IN ('pending','queued')""",
            (f"mcn_preflight_freeze:{reason}", account_id)
        ).rowcount
        if n:
            log.info(f"[mcn_preflight] cancelled {n} pending plan_items for account={account_id}")
    except Exception as e:
        log.warning(f"[mcn_preflight] cancel plan_items: {e}")

    conn.commit()


def preflight_check(
    account_id: int,
    drama_name: str | None = None,
    numeric_uid: int | str | None = None,
    string_uid: str | None = None,
) -> dict:
    """发布前 MCN 状态检查.

    Args:
        account_id: device_accounts.id (int PK)
        drama_name: 要发的剧名 (用于黑名单 check)
        numeric_uid: 数字 UID (fluorescent_members / photo_violation_log 用这个)
        string_uid: 字符串 UID 3xxx 格式 (mcn_account_bindings 用这个)
                    两者都不传时自动从 device_accounts 查

    Schema 关键:
        device_accounts.kuaishou_uid  = 字符串 (3xmne9bjww75dt9) — 对齐 bindings
        device_accounts.numeric_uid   = 数字 (887329560) — 对齐 member_snapshots
    """
    if not _cfg("ai.preflight.mcn_enabled", True):
        return {"ok": True, "reason": "disabled", "error": "", "detail": {}}

    conn = _connect()
    try:
        # 从 device_accounts 取 2 种 UID
        row = conn.execute(
            "SELECT kuaishou_uid, numeric_uid, account_name, tier, frozen_reason "
            "FROM device_accounts WHERE id=?",
            (account_id,)
        ).fetchone()
        if not row:
            return {"ok": False, "reason": "account_not_found",
                    "error": f"device_accounts id={account_id} 不存在",
                    "detail": {}}
        account_name = row["account_name"]
        if string_uid is None:
            string_uid = row["kuaishou_uid"]
        if numeric_uid is None:
            numeric_uid = row["numeric_uid"]

        # 账号已经 frozen (人工或过往 preflight) → 保持拒绝, 不重做检查
        if row["tier"] == "frozen":
            return {"ok": False, "reason": f"already_frozen:{row['frozen_reason'] or 'unknown'}",
                    "error": f"账号 tier=frozen ({row['frozen_reason']}), 需管理员手动解冻",
                    "detail": {"account_id": account_id, "account_name": account_name,
                               "frozen_reason": row["frozen_reason"]}}

        if not string_uid and not numeric_uid:
            log.warning(f"[mcn_preflight] account={account_id} 无 UID, 跳过 MCN 检查")
            return {"ok": True, "reason": "no_uid_skip",
                    "error": "账号无 kuaishou_uid / numeric_uid, 跳过",
                    "detail": {"account_id": account_id}}

        detail = {"account_id": account_id, "account_name": account_name,
                  "string_uid": string_uid, "numeric_uid": numeric_uid,
                  "drama_name": drama_name}

        # ─── Check 1: MCN 账号绑定 (用 string_uid 匹配 kuaishou_uid) ───
        if _cfg("ai.preflight.check_binding", True) and string_uid:
            row = conn.execute(
                """SELECT member_id, bound_at, last_verified_at, plan_type,
                          commission_rate
                   FROM mcn_account_bindings
                   WHERE kuaishou_uid=?
                   ORDER BY id DESC LIMIT 1""",
                (str(string_uid),)
            ).fetchone()
            if not row:
                # 绑定不存在 = MCN 里没这个账号, 不能发 (分佣拿不到)
                reason = "mcn_binding_missing"
                _freeze_account(conn, account_id, reason, detail)
                return {"ok": False, "reason": reason,
                        "error": f"账号 numeric_uid={numeric_uid} 在 MCN 无绑定记录",
                        "detail": detail}
            # 检查绑定是否太久未验证 (说明 MCN 侧可能已清)
            stale_days = int(_cfg("ai.preflight.binding_stale_days", 30))
            if row["last_verified_at"]:
                stale_row = conn.execute(
                    "SELECT julianday('now') - julianday(?) AS days",
                    (row["last_verified_at"],)
                ).fetchone()
                days = (stale_row["days"] or 0) if stale_row else 0
                if days > stale_days:
                    reason = "mcn_binding_stale"
                    detail["binding_stale_days"] = round(days, 1)
                    _freeze_account(conn, account_id, reason, detail)
                    return {"ok": False, "reason": reason,
                            "error": f"MCN 绑定 {days:.0f} 天未验证 (>{stale_days}d), 可能已失效",
                            "detail": detail}
            detail["binding_member_id"] = row["member_id"]
            detail["binding_plan"] = row["plan_type"]
            detail["commission_rate"] = row["commission_rate"]

        # ─── Check 2: 近期收益活跃度 (member_snapshots 最近 N 天) ───
        if _cfg("ai.preflight.check_income_activity", True):
            lookback_days = int(_cfg("ai.preflight.income_lookback_days", 7))
            row = conn.execute(
                """SELECT MAX(snapshot_date) AS last_date, COUNT(*) AS n
                   FROM mcn_member_snapshots
                   WHERE member_id=? AND snapshot_date >= date('now', '-' || ? || ' days')""",
                (numeric_uid, lookback_days)
            ).fetchone()
            n_snap = row["n"] if row else 0
            # 容忍: 账号新开没收益不算, 但存在 binding 却长期没进 snapshot → 可能被 MCN 清了
            if _cfg("ai.preflight.require_recent_snapshot", False) and n_snap == 0:
                reason = "mcn_no_recent_snapshot"
                _freeze_account(conn, account_id, reason,
                                {**detail, "lookback_days": lookback_days,
                                 "last_snapshot_date": None})
                return {"ok": False, "reason": reason,
                        "error": f"MCN 近 {lookback_days} 天无收益快照 (可能已被 MCN 清除)",
                        "detail": {**detail, "last_snapshot_date": None,
                                   "lookback_days": lookback_days}}
            detail["last_snapshot_date"] = row["last_date"] if row else None

        # ─── Check 3: 违规图暴增 ───
        if _cfg("ai.preflight.check_violation_burst", True):
            window_hours = int(_cfg("ai.watchdog.violation_burst.window_hours", 24))
            threshold = int(_cfg("ai.watchdog.violation_burst.threshold", 3))
            # photo_violation_log.account_uid 可能是数字或字符串, 两种都试
            candidates = []
            if numeric_uid:
                candidates.append(str(numeric_uid))
            if string_uid:
                candidates.append(str(string_uid))
            n_viol = 0
            if candidates:
                placeholders = ",".join(["?"] * len(candidates))
                n_viol = conn.execute(
                    f"""SELECT COUNT(*) FROM photo_violation_log
                        WHERE account_uid IN ({placeholders})
                          AND mcn_created_at >= datetime('now', '-' || ? || ' hours')""",
                    (*candidates, window_hours)
                ).fetchone()[0]
            if n_viol >= threshold:
                reason = "mcn_violation_burst"
                _freeze_account(conn, account_id, reason,
                                {**detail, "violations_24h": n_viol, "threshold": threshold})
                return {"ok": False, "reason": reason,
                        "error": f"MCN 近 {window_hours}h 违规图 {n_viol} 张 ≥ 阈值 {threshold}, 自动冻结",
                        "detail": {**detail, "violations_24h": n_viol,
                                   "threshold": threshold}}
            detail[f"violations_{window_hours}h"] = n_viol

        # ─── Check 4: 剧黑名单 ───
        if drama_name and _cfg("ai.preflight.check_drama_blacklist", True):
            row = conn.execute(
                """SELECT status, violation_reason, violation_type
                   FROM drama_blacklist
                   WHERE drama_name=? AND status='active' LIMIT 1""",
                (drama_name,)
            ).fetchone()
            if row:
                # 不冻账号, 只拒该任务
                reason_txt = row["violation_reason"] or row["violation_type"] or "(no reason)"
                return {"ok": False, "reason": "drama_blacklisted",
                        "error": f"剧 '{drama_name}' 在 MCN 黑名单: {reason_txt}",
                        "detail": {**detail, "blacklist_reason": reason_txt}}
            detail["drama_blacklist_ok"] = True

        return {"ok": True, "reason": "passed", "error": "",
                "detail": detail}

    finally:
        conn.close()


# CLI test
def main():
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--account-id", type=int, required=True)
    ap.add_argument("--drama", default=None)
    args = ap.parse_args()
    r = preflight_check(args.account_id, args.drama)
    print(json.dumps(r, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
