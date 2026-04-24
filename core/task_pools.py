# -*- coding: utf-8 -*-
"""三池预算 — burst / steady / maintenance worker 隔离.

Week 1 Day 5-B 落地. v6 阶段 1 核心.

★ 背景:
  Day 3 之前, Executor 是 flat queue + 共享 worker. task_type 只在
  dispatch 时分流, worker 本身抢同一锁. 后果:
    - 维护任务 (cookie refresh) 可能塞住主力 worker, 压着 PUBLISH 排队
    - burst 爆款跟发没独立并发, 高优先级只决定"谁先跑" 不能"同时跑 N 个"
    - 冷启动 mode=startup (worker=2) 时, 14 个 maintenance task 入队会把
      2 worker 全占满 3-10 分钟, 期间 PUBLISH 零进展

★ 设计:
  3 个独立 pool, 每池单独一组 worker 线程, 只消费自己关心的 task_type.

    burst      — PUBLISH_BURST (priority=99)
    steady     — PUBLISH, PUBLISH_DRAMA, PUBLISH_A (planner / experiment)
    maintenance— COOKIE_REFRESH, MCN_TOKEN, LIBRARY_CLEAN, QUOTA_BACKFILL,
                 FREEZE_ACCOUNT, UNFREEZE_ACCOUNT

  worker 数按 operation_mode 分配:
    startup (2):   steady=1, maintenance=1    (burst off, 0 worker)
    growth (4):    steady=3, maintenance=1    (burst off, 0 worker)
    volume (8):    burst=2, steady=5, maintenance=1
    matrix (12):   burst=3, steady=7, maintenance=2
    scale (16):    burst=4, steady=10, maintenance=2

  burst off 时, burst quota → 直接合并到 steady (不浪费 worker).

★ 消费方 (Executor.start 内部):
  from core.task_pools import allocate_workers, POOL_MAP
  allocation = allocate_workers(total=12, burst_enabled=True)
  # → {"burst": 3, "steady": 7, "maintenance": 2}
  for pool, n in allocation.items():
      for i in range(n):
          threading.Thread(target=_worker_loop,
              args=(f"worker-{pool}-{i}", stop, POOL_MAP[pool]))

★ 运维可覆盖:
  app_config `executor.pool.{pool}.worker_count` = 数字 — 固定该池 worker 数
  app_config `executor.pool.{pool}.task_types` = 'PUBLISH,PUBLISH_A' — 覆盖 task_type 集
"""
from __future__ import annotations

import logging
from typing import NamedTuple

log = logging.getLogger(__name__)


# ──────────────────────────────────────────────────────
# Pool → task_type 映射 (可被 config override)
# ──────────────────────────────────────────────────────
POOL_MAP: dict[str, list[str]] = {
    "burst": [
        "PUBLISH_BURST",
    ],
    "steady": [
        "PUBLISH",          # 主力
        "PUBLISH_DRAMA",    # legacy alias
        "PUBLISH_A",        # legacy alias (Channel A)
    ],
    "maintenance": [
        "COOKIE_REFRESH",
        "MCN_TOKEN",
        "LIBRARY_CLEAN",
        "QUOTA_BACKFILL",
        "FREEZE_ACCOUNT",
        "UNFREEZE_ACCOUNT",
    ],
}

ALL_POOLS = ("burst", "steady", "maintenance")


# ──────────────────────────────────────────────────────
# Worker 分配算法
# ──────────────────────────────────────────────────────
class WorkerAllocation(NamedTuple):
    burst: int
    steady: int
    maintenance: int
    total: int
    strategy: str    # 'strict' / 'burst_merged' / 'config_override'


# 每档默认比例 (必须 sum ≤ 1.0, 剩余给 steady 兜底)
# 下限 (每池至少 N worker, 若 total 够)
_DEFAULT_SHARES = {
    # mode_name_or_default: (burst_pct, maint_pct)
    "startup":  (0.00, 0.50),
    "growth":   (0.00, 0.25),
    "volume":   (0.25, 0.13),
    "matrix":   (0.25, 0.17),
    "scale":    (0.25, 0.13),
}


def allocate_workers(total: int, burst_enabled: bool = True,
                       mode: str | None = None) -> WorkerAllocation:
    """按 total + burst_enabled + mode 分配 3 池 worker 数.

    Args:
        total: 总 worker 数 (来自 operation_mode.worker_count())
        burst_enabled: False 时 burst quota → steady
        mode: 用于读默认比例, 缺省走 current_mode()

    Priority:
        1. 若 config executor.pool.{pool}.worker_count 有值 → 用 config (strict)
        2. 否则按 _DEFAULT_SHARES 百分比分配
        3. burst_enabled=False → burst=0, 其余量给 steady
        4. 保证 steady + maintenance ≥ 1 (除非 total=0)

    Returns:
        WorkerAllocation(burst, steady, maintenance, total, strategy)
    """
    if total < 1:
        return WorkerAllocation(0, 0, 0, 0, "empty")

    # 1. 读 config override (最高优)
    try:
        from core.app_config import get as _cg
        cb = _cg("executor.pool.burst.worker_count", None)
        cs = _cg("executor.pool.steady.worker_count", None)
        cm = _cg("executor.pool.maintenance.worker_count", None)
        if all(x is not None for x in (cb, cs, cm)):
            b, s, m = int(cb), int(cs), int(cm)
            if not burst_enabled:
                s += b
                b = 0
            return WorkerAllocation(b, s, m, b + s + m, "config_override")
    except Exception:
        pass

    # 2. mode 确定
    if mode is None:
        try:
            from core.operation_mode import current_mode
            mode = current_mode()
        except Exception:
            mode = "startup"

    shares = _DEFAULT_SHARES.get(mode, _DEFAULT_SHARES["startup"])
    burst_pct, maint_pct = shares

    # 3. 按比例分
    burst_n = int(round(total * burst_pct))
    maint_n = max(1, int(round(total * maint_pct)))   # maintenance 保底 1
    # steady 收剩
    steady_n = total - burst_n - maint_n

    # 4. burst_enabled=False → 合并
    strategy = "strict"
    if not burst_enabled:
        steady_n += burst_n
        burst_n = 0
        strategy = "burst_merged"

    # 5. 兜底: steady ≥ 1 (总 worker 够的话)
    if steady_n < 1 and total >= 2:
        # 从 maintenance 借 1 给 steady
        if maint_n > 1:
            maint_n -= 1
            steady_n += 1

    # 最终防御
    burst_n = max(0, burst_n)
    steady_n = max(0, steady_n)
    maint_n = max(0, maint_n)
    actual_total = burst_n + steady_n + maint_n

    return WorkerAllocation(burst_n, steady_n, maint_n, actual_total, strategy)


def get_pool_task_types(pool: str) -> list[str]:
    """某 pool 的 task_type 集, 含 config override."""
    default = POOL_MAP.get(pool, [])
    try:
        from core.app_config import get as _cg
        raw = _cg(f"executor.pool.{pool}.task_types", None)
        if raw:
            if isinstance(raw, str):
                return [t.strip() for t in raw.split(",") if t.strip()]
            if isinstance(raw, list):
                return raw
    except Exception:
        pass
    return default


def describe_allocation() -> dict:
    """给 dashboard 看当前分配. 返 {allocation, pool_types}."""
    try:
        from core.operation_mode import get_policy, current_mode, should_burst
        mode = current_mode()
        policy = get_policy()
        total = policy.worker_count
        burst_en = should_burst()
    except Exception:
        mode = "unknown"
        total = 2
        burst_en = False

    alloc = allocate_workers(total=total, burst_enabled=burst_en, mode=mode)
    return {
        "mode": mode,
        "total_workers": total,
        "burst_enabled": burst_en,
        "allocation": alloc._asdict(),
        "pool_task_types": {p: get_pool_task_types(p) for p in ALL_POOLS},
    }


if __name__ == "__main__":
    # CLI demo: show allocation for all 5 modes
    import sys
    try: sys.stdout.reconfigure(encoding="utf-8")
    except Exception: pass

    from core.operation_mode import _MODE_POLICIES

    print("═══ Task Pool Worker Allocation (全 5 档 mode) ═══\n")
    fmt = "{:<8} {:<6} {:<6} {:<7} {:<8} {:<8} {:<6}"
    print(fmt.format("mode", "total", "burst?", "burst", "steady", "maint", "sum"))
    print("─" * 55)
    for mode in ("startup", "growth", "volume", "matrix", "scale"):
        policy = _MODE_POLICIES[mode]
        total = policy["worker_count"]
        burst_en = policy["burst_enabled"]
        alloc = allocate_workers(total=total, burst_enabled=burst_en, mode=mode)
        print(fmt.format(mode, total, str(burst_en),
                         alloc.burst, alloc.steady, alloc.maintenance,
                         alloc.total))

    print("\n─── 现在 runtime 分配 ───")
    import json
    print(json.dumps(describe_allocation(), indent=2, default=str))
