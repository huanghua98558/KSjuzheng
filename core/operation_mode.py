# -*- coding: utf-8 -*-
"""自适应运营模式 — 根据可用账号数动态选档位 + 输出完整 policy.

Week 1 Day 2 落地. v6 路线图 B1 核心.

★ 背景:
  用户原话 "要系统依据可用账号数量进行合理的运行方式. 先 SQLite 跑到 300 号, 再迁..."
  之前所有策略常量 (worker_count=4, burst=True, explore=0.10, ...) 都散落在
  agent 内部硬编码或 app_config 散列. 今天起统一用 OperationPolicy.

★ 5 档 mode ladder (按可用账号数):
  startup  [0, 10)    少量尝试, 人工观察, 不跑 burst
  growth   [10, 50)   AI 起势, 规则优化, 不跑 burst
  volume   [50, 100)  规模化, 多 recipe, burst 保守 (threshold=100k)
  matrix   [100, 300) 矩阵化, burst 进取 (50k), 8 worker
  scale    [300, +∞)  集群化, burst 激进 (30k), 准备 PG 迁移

★ 职责:
  1. _available_account_count() — 查可用账号 (signed + logged_in + not frozen)
  2. current_mode() — 映射 n → mode (支持 config force override)
  3. get_policy(mode) — 返 OperationPolicy NamedTuple (11 轴)
  4. apply_policy(mode) — 把 policy 写回 app_config (让现有 agents 自动读)
  5. log_transition(old, new) — mode 切换时写 system_events + operation_mode_history

★ 消费方 (Day 3+ 接入):
  strategy_planner_agent — budget from planner_daily_budget()
  burst_agent            — 查 should_burst() + burst_threshold_views()
  executor Executor      — worker_count from get_policy().worker_count
  scheduler              — per-account daily cap from posts_per_account_per_day

用法:
  from core.operation_mode import current_mode, get_policy, planner_daily_budget
  mode = current_mode()                    # 'startup'
  policy = get_policy()                    # 完整 policy
  budget = planner_daily_budget()          # 9 * 1 = 9 items

CLI:
  python -m core.operation_mode --show     # 当前状态
  python -m core.operation_mode --apply    # 把当前 policy 写回 config
  python -m core.operation_mode --force scale --apply   # 强制 scale
"""
from __future__ import annotations

import json
import logging
import sqlite3
import time
from typing import NamedTuple

log = logging.getLogger(__name__)


# ──────────────────────────────────────────────────────────────────────────
# 策略字典: mode → 完整参数
# ──────────────────────────────────────────────────────────────────────────
# 注意: 这是"默认值". 任何项都可被 app_config.operation.policy.{mode}.{key} override.
# 如: 设 operation.policy.matrix.worker_count=16, get_policy("matrix").worker_count 就返 16
_MODE_POLICIES: dict[str, dict] = {
    "startup": {
        # 账号规模: 0-10
        "posts_per_account_per_day": 1,
        "max_daily_items": 15,
        "worker_count": 2,
        "burst_enabled": False,
        "burst_threshold_views": 999_999,   # 不触发
        "burst_priority": 99,
        "experiment_explore_rate": 0.20,    # 高探索
        "planner_min_items_per_account": 1,
        "planner_max_accounts_per_drama": 3,
        "cooldown_after_fail_hours": 12,
        "description": "少量尝试, 人工观察, 不开 burst",
    },
    "growth": {
        # 账号规模: 10-50
        "posts_per_account_per_day": 2,
        "max_daily_items": 100,
        "worker_count": 4,
        "burst_enabled": False,
        "burst_threshold_views": 200_000,
        "burst_priority": 99,
        "experiment_explore_rate": 0.15,
        "planner_min_items_per_account": 1,
        "planner_max_accounts_per_drama": 3,
        "cooldown_after_fail_hours": 6,
        "description": "AI 起势, 规则优化, burst off",
    },
    "volume": {
        # 账号规模: 50-100
        "posts_per_account_per_day": 3,
        "max_daily_items": 400,
        "worker_count": 8,
        "burst_enabled": True,
        "burst_threshold_views": 100_000,   # 保守
        "burst_priority": 99,
        "experiment_explore_rate": 0.10,
        "planner_min_items_per_account": 2,
        "planner_max_accounts_per_drama": 5,
        "cooldown_after_fail_hours": 3,
        "description": "规模化, 多 recipe, burst 保守 (100k)",
    },
    "matrix": {
        # 账号规模: 100-300
        "posts_per_account_per_day": 5,
        "max_daily_items": 2000,
        "worker_count": 12,
        "burst_enabled": True,
        "burst_threshold_views": 50_000,    # 进取
        "burst_priority": 99,
        "experiment_explore_rate": 0.08,
        "planner_min_items_per_account": 3,
        "planner_max_accounts_per_drama": 8,
        "cooldown_after_fail_hours": 2,
        "description": "矩阵化, burst 进取 (50k), 12 worker",
    },
    "scale": {
        # 账号规模: 300+
        "posts_per_account_per_day": 6,
        "max_daily_items": 10000,
        "worker_count": 16,
        "burst_enabled": True,
        "burst_threshold_views": 30_000,    # 激进
        "burst_priority": 99,
        "experiment_explore_rate": 0.05,
        "planner_min_items_per_account": 4,
        "planner_max_accounts_per_drama": 13,
        "cooldown_after_fail_hours": 1,
        "description": "集群化, burst 激进 (30k), 准备 PG",
    },
}


# 档位 → 账号数下限
_MODE_THRESHOLDS: list[tuple[str, int]] = [
    ("scale", 300),
    ("matrix", 100),
    ("volume", 50),
    ("growth", 10),
    ("startup", 0),
]


class OperationPolicy(NamedTuple):
    """当前运营策略 — 不可变 snapshot, 可直接传给 agent."""
    mode: str
    account_count: int
    posts_per_account_per_day: int
    max_daily_items: int
    worker_count: int
    burst_enabled: bool
    burst_threshold_views: int
    burst_priority: int
    experiment_explore_rate: float
    planner_min_items_per_account: int
    planner_max_accounts_per_drama: int
    cooldown_after_fail_hours: int
    description: str


# ──────────────────────────────────────────────────────────────────────────
# 内部 helpers
# ──────────────────────────────────────────────────────────────────────────
_CACHE: dict = {
    "policy": None,        # OperationPolicy or None
    "loaded_at": 0.0,
    "ttl_sec": 60.0,       # 60s cache — mode 不会频繁变
}


def _connect() -> sqlite3.Connection:
    from core.config import DB_PATH
    c = sqlite3.connect(DB_PATH, timeout=30)
    c.execute("PRAGMA busy_timeout=30000")
    c.execute("PRAGMA journal_mode=WAL")
    c.execute("PRAGMA synchronous=NORMAL")
    c.row_factory = sqlite3.Row
    return c


def _cfg_get(key: str, default):
    """Thin wrapper — 避免 top-level import 循环."""
    try:
        from core.app_config import get as _g
        return _g(key, default)
    except Exception:
        return default


def _available_account_count() -> int:
    """可用账号数 = signed + logged_in + 非 frozen.

    ★ 不 filter is_active — 大部分历史账号 is_active=0 但实际可用,
    尤其是旧的 mode2 account (KS184 只给 mode1 账号设 is_active=1).
    """
    try:
        with _connect() as c:
            row = c.execute(
                """SELECT COUNT(*) FROM device_accounts
                   WHERE signed_status='signed'
                     AND login_status='logged_in'
                     AND (tier IS NULL OR tier != 'frozen')"""
            ).fetchone()
            return int(row[0]) if row else 0
    except Exception as e:
        log.warning("[operation_mode] _available_account_count failed: %s", e)
        return 0


# ──────────────────────────────────────────────────────────────────────────
# 公共 API
# ──────────────────────────────────────────────────────────────────────────
def current_mode() -> str:
    """根据 available_account_count 返回当前档位.

    支持人工 override: 设 app_config `operation.mode.force = "scale"`,
    会无视账号数直接返 scale (用于故意预热 / 压测).
    """
    forced = (_cfg_get("operation.mode.force", "") or "").strip()
    if forced in _MODE_POLICIES:
        return forced

    n = _available_account_count()
    for mode, threshold in _MODE_THRESHOLDS:
        if n >= threshold:
            return mode
    return "startup"   # defensive


def get_policy(mode: str | None = None, use_cache: bool = True) -> OperationPolicy:
    """返回完整策略 snapshot. 每项 app_config 可 override.

    Args:
        mode: 指定 mode (默认用 current_mode())
        use_cache: True 时 60s 内返 cache (默认), False 强刷
    """
    now = time.time()
    if use_cache and mode is None and _CACHE["policy"] is not None:
        if (now - _CACHE["loaded_at"]) < _CACHE["ttl_sec"]:
            return _CACHE["policy"]

    if mode is None:
        mode = current_mode()
    base = _MODE_POLICIES.get(mode) or _MODE_POLICIES["startup"]
    n = _available_account_count()

    def _o(key, default):
        """读 operation.policy.{mode}.{key} 的 override, 缺则用 base."""
        return _cfg_get(f"operation.policy.{mode}.{key}", default)

    policy = OperationPolicy(
        mode=mode,
        account_count=n,
        posts_per_account_per_day=int(_o("posts_per_account_per_day", base["posts_per_account_per_day"])),
        max_daily_items=int(_o("max_daily_items", base["max_daily_items"])),
        worker_count=int(_o("worker_count", base["worker_count"])),
        burst_enabled=bool(_o("burst_enabled", base["burst_enabled"])),
        burst_threshold_views=int(_o("burst_threshold_views", base["burst_threshold_views"])),
        burst_priority=int(_o("burst_priority", base["burst_priority"])),
        experiment_explore_rate=float(_o("experiment_explore_rate", base["experiment_explore_rate"])),
        planner_min_items_per_account=int(_o("planner_min_items_per_account", base["planner_min_items_per_account"])),
        planner_max_accounts_per_drama=int(_o("planner_max_accounts_per_drama", base["planner_max_accounts_per_drama"])),
        cooldown_after_fail_hours=int(_o("cooldown_after_fail_hours", base["cooldown_after_fail_hours"])),
        description=str(base["description"]),
    )

    if use_cache and mode == current_mode():
        _CACHE["policy"] = policy
        _CACHE["loaded_at"] = now

    return policy


def invalidate_cache() -> None:
    """mode 切换或 config 改时调."""
    _CACHE["policy"] = None
    _CACHE["loaded_at"] = 0.0


# ─── 常用便利函数 (agent 直接调, 不用构造 policy) ────────────────────────
def planner_daily_budget() -> int:
    """全矩阵每日总 item 硬顶. = min(max_daily_items, account_count * posts_per_account)."""
    p = get_policy()
    return min(p.max_daily_items, p.account_count * p.posts_per_account_per_day)


def should_burst() -> bool:
    return get_policy().burst_enabled


def burst_threshold_views() -> int:
    return get_policy().burst_threshold_views


def worker_count() -> int:
    return get_policy().worker_count


# ──────────────────────────────────────────────────────────────────────────
# ★ 2026-04-24 v6 Day 4: MCN mode A/B 实时信号
# ──────────────────────────────────────────────────────────────────────────
def mcn_mode() -> str:
    """当前 MCN 模式.

    A = healthy (所有 MCN-touching breaker CLOSED)
    B = degraded (任一 MCN breaker OPEN)

    消费方:
      - planner: mode B 时降低预期 / 优先本地备份剧
      - burst:   mode B 时 skip (不要雪上加霜)
      - dashboard: 实时显示
    """
    try:
        from core.circuit_breaker import any_mcn_open
        return "B" if any_mcn_open() else "A"
    except Exception:
        return "A"   # 模块加载失败 → 默认乐观


def mcn_status_detail() -> dict:
    """完整 MCN 状态 (给 dashboard / debug 用)."""
    try:
        from core.circuit_breaker import mcn_snapshot
        snap = mcn_snapshot()
        snap["healthy"] = snap["mode"] == "A"
        return snap
    except Exception as e:
        return {"mode": "A", "breakers": [], "healthy": True, "error": str(e)}


def circuit_breaker_snapshot() -> list[dict]:
    """所有 breaker 状态 (不限 MCN)."""
    try:
        from core.circuit_breaker import snapshot_all
        return snapshot_all()
    except Exception:
        return []


# ──────────────────────────────────────────────────────────────────────────
# Apply — 把 policy 写回 app_config 让现有 agents 读
# ──────────────────────────────────────────────────────────────────────────
_CONFIG_MAPPING = {
    # policy field → config key (现有 agent 用的)
    "worker_count":              "executor.worker_count",
    "experiment_explore_rate":   "ai.experiment.explore_rate",
    "burst_enabled":             "ai.burst.enabled",
    "burst_threshold_views":     "ai.burst.threshold_views",
    "burst_priority":            "ai.burst.priority",
    "planner_min_items_per_account": "ai.planner.min_items_per_account",
    "planner_max_accounts_per_drama": "ai.planner.max_accounts_per_drama",
    # 新 key (operation_mode 独有)
    "posts_per_account_per_day": "operation.current.posts_per_day",
    "max_daily_items":           "operation.current.max_daily_items",
    "cooldown_after_fail_hours": "operation.current.cooldown_hours",
}


def apply_policy(mode: str | None = None, dry_run: bool = False,
                  reason: str = "") -> dict:
    """把当前 mode 的 policy 值写回 app_config.

    ★ 如果 mode 跟上次 apply 不同, 自动 log_transition.

    Args:
        mode: 指定 mode (默认用 current_mode())
        dry_run: True 只返 diff 不写
        reason: 传给 log_transition 的 reason

    Returns:
        {'mode', 'account_count', 'changed' [(key, old, new), ...],
         'unchanged' [...], 'transitioned': bool, 'old_mode' (只在 transition 时有),
         'description'}
    """
    policy = get_policy(mode, use_cache=False)

    from core.app_config import get as _cg, set_ as _cs

    # ★ 先读旧 mode (必须 BEFORE 下面的 _cs 写新 operation.current.mode)
    old_mode_applied = (_cg("operation.current.mode", "") or "").strip() or "startup"

    changed, unchanged = [], []
    for field, cfgkey in _CONFIG_MAPPING.items():
        new = getattr(policy, field)
        old = _cg(cfgkey, None)
        # 类型归一化比较 (bool vs str 'true')
        same = False
        if old is not None:
            try:
                if isinstance(new, bool):
                    same = bool(old) == new
                elif isinstance(new, int):
                    same = int(old) == new
                elif isinstance(new, float):
                    same = abs(float(old) - new) < 1e-6
                else:
                    same = str(old) == str(new)
            except Exception:
                same = False
        if same:
            unchanged.append((cfgkey, old))
        else:
            changed.append((cfgkey, old, new))
            if not dry_run:
                _cs(cfgkey, new)

    transitioned = False
    if not dry_run:
        # 存 current mode snapshot
        _cs("operation.current.mode", policy.mode)
        _cs("operation.current.account_count", policy.account_count)
        _cs("operation.current.applied_at",
            time.strftime("%Y-%m-%d %H:%M:%S"))

        # ★ mode 真变了 → 写 transition
        if old_mode_applied != policy.mode:
            log_transition(old_mode_applied, policy.mode,
                           reason=(reason or "apply_policy"))
            transitioned = True

    invalidate_cache()
    return {"mode": policy.mode, "changed": changed, "unchanged": unchanged,
            "account_count": policy.account_count,
            "description": policy.description,
            "transitioned": transitioned,
            "old_mode": old_mode_applied}


# ──────────────────────────────────────────────────────────────────────────
# Transition 记录 + system_events
# ──────────────────────────────────────────────────────────────────────────
def log_transition(old_mode: str, new_mode: str, reason: str = "") -> None:
    """mode 切换时写 operation_mode_history + system_events (SSE 推送)."""
    if old_mode == new_mode:
        return
    policy = get_policy(new_mode, use_cache=False)
    try:
        with _connect() as c:
            # 1. operation_mode_history
            c.execute(
                """INSERT INTO operation_mode_history
                     (old_mode, new_mode, account_count, reason, transitioned_at,
                      snapshot_policy_json)
                   VALUES (?, ?, ?, ?, datetime('now','localtime'), ?)""",
                (old_mode, new_mode, policy.account_count, reason or "auto",
                 json.dumps(policy._asdict(), ensure_ascii=False)),
            )
            # 2. system_events (已有表)
            try:
                c.execute(
                    """INSERT INTO system_events (event_type, event_data, severity, created_at)
                       VALUES ('operation_mode_transition', ?, 'info',
                               datetime('now','localtime'))""",
                    (json.dumps({
                        "old_mode": old_mode, "new_mode": new_mode,
                        "account_count": policy.account_count,
                        "reason": reason,
                    }, ensure_ascii=False),),
                )
            except sqlite3.OperationalError:
                pass   # system_events 可能还没建
            c.commit()
        log.info("[operation_mode] transition %s → %s (n=%d reason=%s)",
                 old_mode, new_mode, policy.account_count, reason or "auto")
    except Exception as e:
        log.exception("[operation_mode] log_transition failed: %s", e)


def maybe_auto_transition() -> dict:
    """按当前 account_count 检测是否应切 mode.

    策略:
        - 读上次 applied mode (operation.current.mode)
        - 对比 current_mode()
        - 不同 → apply_policy (内部自己 log_transition, 不重复)
        - 同 → 什么都不做

    Returns dict: {'transitioned': bool, 'old_mode', 'new_mode', 'reason'}
    """
    from core.app_config import get as _cg
    old = (_cg("operation.current.mode", "") or "").strip() or "startup"
    new = current_mode()
    if old == new:
        return {"transitioned": False, "old_mode": old, "new_mode": new,
                "reason": "no_change"}
    # 切 — apply_policy 会自己调 log_transition (传同 reason 保持一致)
    result = apply_policy(new, dry_run=False, reason="auto_by_account_count")
    return {"transitioned": True, "old_mode": old, "new_mode": new,
            "reason": "auto_by_account_count",
            "changed_configs": len(result["changed"])}


# ──────────────────────────────────────────────────────────────────────────
# CLI
# ──────────────────────────────────────────────────────────────────────────
def _format_policy(policy: OperationPolicy) -> str:
    lines = [
        f"═══ Operation Policy — mode={policy.mode}  accounts={policy.account_count} ═══",
        f"  {policy.description}",
        f"",
        f"  posts_per_account/day         : {policy.posts_per_account_per_day}",
        f"  max_daily_items (全矩阵)       : {policy.max_daily_items}",
        f"  worker_count                   : {policy.worker_count}",
        f"  burst_enabled                  : {policy.burst_enabled}",
        f"  burst_threshold_views          : {policy.burst_threshold_views:,}",
        f"  burst_priority                 : {policy.burst_priority}",
        f"  experiment_explore_rate        : {policy.experiment_explore_rate:.2f}",
        f"  planner_min_items_per_account  : {policy.planner_min_items_per_account}",
        f"  planner_max_accounts_per_drama : {policy.planner_max_accounts_per_drama}",
        f"  cooldown_after_fail_hours      : {policy.cooldown_after_fail_hours}",
    ]
    return "\n".join(lines)


def main():
    import argparse
    ap = argparse.ArgumentParser(description="Operation Mode CLI")
    ap.add_argument("--show", action="store_true", help="显示当前策略 (默认)")
    ap.add_argument("--force", choices=list(_MODE_POLICIES.keys()),
                    help="强制选 mode (不 apply)")
    ap.add_argument("--apply", action="store_true",
                    help="把当前策略写回 app_config")
    ap.add_argument("--dry-run", action="store_true",
                    help="apply 时只看 diff 不写")
    ap.add_argument("--transition", action="store_true",
                    help="做一次 auto_transition 检测")
    args = ap.parse_args()

    mode = args.force or current_mode()
    policy = get_policy(mode, use_cache=False)
    print(_format_policy(policy))

    if args.transition:
        res = maybe_auto_transition()
        print(f"\n[transition] {res}")

    if args.apply:
        print(f"\n── Apply policy (dry_run={args.dry_run}) ──")
        res = apply_policy(mode, dry_run=args.dry_run, reason="manual_cli_apply")
        if res["changed"]:
            print(f"  CHANGED ({len(res['changed'])} keys):")
            for k, old, new in res["changed"]:
                print(f"    {k:<45} {old!r}  →  {new!r}")
        if res["unchanged"]:
            print(f"  UNCHANGED: {len(res['unchanged'])} keys (already same)")
        if args.dry_run:
            print("  (dry-run, 未写入)")
        elif res.get("transitioned"):
            print(f"  🔄 TRANSITION: {res['old_mode']} → {res['mode']} (logged)")


if __name__ == "__main__":
    import sys
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
    main()
