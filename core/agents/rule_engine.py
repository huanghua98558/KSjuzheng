# -*- coding: utf-8 -*-
"""Rule engine — hard business rules applied BEFORE plan execution.

Per PRODUCTION_EVOLUTION_PLAN.md §11, three insertion points:
  1. After Agent decision, before task creation
  2. Before task enters execution
  3. Before the publish step

Rules output a dict:
    {"allowed": True}  OR
    {"allowed": False, "reason": "...", "rule_code": "..."}
"""
from __future__ import annotations

from datetime import datetime
from typing import Any

from core.switches import is_enabled
from core.config_center import cfg


class RuleEngine:
    """Centralized read-only gatekeeper."""

    def __init__(self, db_manager):
        self.db = db_manager

    # ------------------------------------------------------------------
    # Global
    # ------------------------------------------------------------------

    def global_publish_allowed(self) -> dict[str, Any]:
        if not is_enabled("publish_enabled"):
            return {"allowed": False, "rule_code": "PUBLISH_DISABLED",
                    "reason": "feature switch publish_enabled = OFF"}
        return {"allowed": True}

    def global_ai_allowed(self) -> dict[str, Any]:
        if not is_enabled("ai_decision_enabled"):
            return {"allowed": False, "rule_code": "AI_DISABLED",
                    "reason": "feature switch ai_decision_enabled = OFF"}
        return {"allowed": True}

    def global_auto_scale_allowed(self) -> dict[str, Any]:
        if not is_enabled("auto_scale_enabled"):
            return {"allowed": False, "rule_code": "AUTO_SCALE_DISABLED",
                    "reason": "feature switch auto_scale_enabled = OFF"}
        return {"allowed": True}

    # ------------------------------------------------------------------
    # Publish-time rules
    # ------------------------------------------------------------------

    def can_publish_now(
        self,
        account_id: str,
        *,
        daily_limit: int | None = None,
        window_hour_start: int | None = None,
        window_hour_end: int | None = None,
        drama_category: str | None = None,   # 本次要发的剧赛道 (可选, 触发垂直校验)
    ) -> dict[str, Any]:
        # 1. 按 account_level 差异化配额 (思维导图规则)
        if daily_limit is None:
            daily_limit = self._resolve_daily_limit(account_id)
        if window_hour_start is None:
            window_hour_start = int(cfg.get("rule", "publish_window_start", 6))
        if window_hour_end is None:
            window_hour_end = int(cfg.get("rule", "publish_window_end", 23))
        circuit_threshold = int(cfg.get("rule", "circuit_breaker_threshold", 3))

        # 0) Global publish switch
        g = self.global_publish_allowed()
        if not g["allowed"]:
            return g

        # 1) Hour window
        h = datetime.now().hour
        if h < window_hour_start or h >= window_hour_end:
            return {"allowed": False, "rule_code": "OUTSIDE_WINDOW",
                    "reason": f"当前小时 {h} 超出 [{window_hour_start}, {window_hour_end})"}

        # 2) Daily limit for this account
        try:
            today_count = self.db.conn.execute(
                """SELECT COUNT(*) FROM publish_results
                   WHERE account_id = ?
                     AND DATE(created_at) = DATE('now','localtime')
                     AND publish_status = 'success'""",
                (account_id,),
            ).fetchone()[0]
            if today_count >= daily_limit:
                return {"allowed": False, "rule_code": "DAILY_LIMIT_REACHED",
                        "reason": f"账号 {account_id} 今日已达 {daily_limit} 条上限"}
        except Exception:
            pass

        # 3) 熔断 - 连续 N 次失败
        try:
            recent = self.db.conn.execute(
                """SELECT publish_status FROM publish_results
                   WHERE account_id = ?
                   ORDER BY id DESC LIMIT ?""",
                (account_id, circuit_threshold + 2),
            ).fetchall()
            if len(recent) >= circuit_threshold and all(
                r[0] == "failed" for r in recent[:circuit_threshold]
            ):
                return {"allowed": False, "rule_code": "CIRCUIT_BREAKER",
                        "reason": f"连续 {circuit_threshold} 次发布失败, 触发熔断"}
        except Exception:
            pass

        # 4) 垂直发布校验
        vertical_check = self.vertical_check(account_id, drama_category)
        if not vertical_check["allowed"]:
            return vertical_check

        return {"allowed": True,
                "daily_limit": daily_limit,
                "today_used": self._today_published(account_id)}

    # ------------------------------------------------------------------
    # 差异化配额 (思维导图规则)
    # ------------------------------------------------------------------

    def _resolve_daily_limit(self, account_id: str) -> int:
        """按 account_level 决定今日配额."""
        # 取账号等级
        level = ""
        try:
            row = self.db.conn.execute(
                """SELECT account_level, lifecycle_stage, account_age_days
                   FROM device_accounts
                   WHERE kuaishou_uid=? OR account_name=? OR id=? LIMIT 1""",
                (account_id, account_id,
                 int(account_id) if str(account_id).isdigit() else -1),
            ).fetchone()
            if row:
                level, lifecycle, age_days = row[0], row[1], row[2]
                startup_days = int(cfg.get("rule", "startup_days", 3))
                # 起号期特殊: V1 + 年龄 <= startup_days → V1_new
                if level == "V1" and (age_days or 0) <= startup_days:
                    level = "V1_new"
                # 爆款号 / 沉睡号特殊
                if lifecycle == "viral":
                    level = "VIRAL"
                elif lifecycle == "dormant":
                    level = "DORMANT"
        except Exception:
            pass

        # 从 system_config 读配额表
        quota_map = cfg.get("rule", "quota_by_level", {}) or {}
        if isinstance(quota_map, str):
            try:
                import json as _json
                quota_map = _json.loads(quota_map)
            except Exception:
                quota_map = {}
        # 兜底: 老 daily_publish_limit
        default = int(cfg.get("rule", "daily_publish_limit", 10))
        return int(quota_map.get(level, default))

    def _today_published(self, account_id: str) -> int:
        try:
            return self.db.conn.execute(
                """SELECT COUNT(*) FROM publish_results
                   WHERE account_id = ?
                     AND DATE(created_at) = DATE('now','localtime')
                     AND publish_status = 'success'""",
                (account_id,),
            ).fetchone()[0] or 0
        except Exception:
            return 0

    # ------------------------------------------------------------------
    # 垂直发布校验
    # ------------------------------------------------------------------

    def vertical_check(self, account_id: str,
                       drama_category: str | None) -> dict[str, Any]:
        """检查本次要发的剧赛道是否符合账号的垂直限制."""
        if not drama_category:
            # 调用方未指定赛道 → 跳过 (但不推荐, 建议总是指定)
            return {"allowed": True, "vertical": "(skipped)"}
        enforce = bool(cfg.get("rule", "vertical_enforce", True))
        if not enforce:
            return {"allowed": True, "vertical": "disabled"}
        try:
            row = self.db.conn.execute(
                """SELECT vertical_category, vertical_locked
                   FROM device_accounts
                   WHERE kuaishou_uid=? OR account_name=? OR id=? LIMIT 1""",
                (account_id, account_id,
                 int(account_id) if str(account_id).isdigit() else -1),
            ).fetchone()
        except Exception:
            row = None
        if not row:
            return {"allowed": True}
        acct_cat, locked = row
        # 账号还没定赛道 → 允许, 并在首次发布后锁定
        if not acct_cat:
            return {"allowed": True, "vertical": "first_publish",
                    "set_category": drama_category}
        # 账号已有赛道, 要发的剧同赛道 → OK
        if acct_cat == drama_category:
            return {"allowed": True, "vertical": acct_cat}
        # 跨赛道
        if locked:
            return {"allowed": False, "rule_code": "VERTICAL_MISMATCH",
                    "reason": f"账号绑定 {acct_cat}, 但剧属于 {drama_category}",
                    "suggested_action": "换一个同赛道的剧, 或解锁赛道 (vertical_locked=0)"}
        # 未锁, 警告但放行
        return {"allowed": True, "vertical": acct_cat,
                "warning": f"跨赛道发布 {acct_cat} → {drama_category}"}

    # ------------------------------------------------------------------
    # MCN pre-gate (publish must have valid binding + verify)
    # ------------------------------------------------------------------

    def mcn_binding_ok(self, kuaishou_uid: str) -> dict[str, Any]:
        """Check account is bound to firefly with non-zero commission.
        If cfg rule.mcn_rate_required=False, 允许 rate=0 的账号.
        """
        rate_required = bool(cfg.get("rule", "mcn_rate_required", True))
        try:
            row = self.db.conn.execute(
                """SELECT commission_rate, plan_type, last_verified_at
                   FROM mcn_account_bindings WHERE kuaishou_uid = ?""",
                (kuaishou_uid,),
            ).fetchone()
        except Exception:
            row = None
        if not row:
            return {"allowed": False, "rule_code": "MCN_BIND_REQUIRED",
                    "reason": f"账号 {kuaishou_uid} 不在 mcn_account_bindings"}
        rate, plan, last_verified = row
        if rate_required and (not rate or rate <= 0):
            return {"allowed": False, "rule_code": "MCN_BIND_REQUIRED",
                    "reason": f"账号 {kuaishou_uid} 无 commission_rate"}
        return {"allowed": True, "rule_code": "MCN_BOUND",
                "plan_type": plan, "rate": rate, "last_verified_at": last_verified}

    # ------------------------------------------------------------------
    # Merge recommendations — filter by rules
    # ------------------------------------------------------------------

    def filter_recommendations(self, recommendations: list[dict],
                               context: dict | None = None) -> tuple[list[dict], list[dict]]:
        """Return (allowed_recommendations, rule_rejections).

        context may contain 'account_id', 'kuaishou_uid', etc. — not all
        recommendations need gating (just the risky-publishing ones).
        """
        ctx = context or {}
        allowed = []
        rejected = []
        for rec in recommendations:
            action = rec.get("action", "")
            # Publish-style actions need full gate
            if action in ("publish", "publish_drama", "bootstrap"):
                g = self.global_publish_allowed()
                if not g["allowed"]:
                    rejected.append({**rec, **g})
                    continue
                if "account_id" in rec:
                    p = self.can_publish_now(rec["account_id"])
                    if not p["allowed"]:
                        rejected.append({**rec, **p})
                        continue
            # Scale actions need auto-scale switch
            elif action in ("scale_pattern",):
                g = self.global_auto_scale_allowed()
                if not g["allowed"]:
                    rejected.append({**rec, **g})
                    continue
            allowed.append(rec)
        return allowed, rejected
