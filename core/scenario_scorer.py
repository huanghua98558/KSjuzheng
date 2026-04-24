# -*- coding: utf-8 -*-
"""Scenario Scorer — 根据当前上下文推算"该场景至少需要几星 recipe".

让 AI planner 选 recipe 时不再凭 tier 单因素, 而是综合 5 个风险信号:
  1. 账号 tier (new=2, testing=2, warming_up=3, established=4, viral=5)
  2. task_source  (burst → 强制 5, experiment → 2-5 视 group, planner → 1)
  3. 同剧 72h 多账号爬 (≥5 账号 → 升到 4)
  4. 账号近 6h 失败次数 (≥2 → 升到 4)
  5. 同 MCN 同剧 24h 密度 (≥3 → 升到 5)

输出:
  min_strength: 1-5, 该场景下选 recipe 时最低综合星
  min_l3: 1-5, L3 最低星 (爆款/高风险要求 4+)
  scenario_tag: 场景分类字符串 (用于 recipe_performance 埋点)
  reasons: list, 触发了哪些规则

用法:
    from core.scenario_scorer import score_scenario
    result = score_scenario(account, drama_name, task_source)
    # result = {min_strength: 4, min_l3: 4, scenario_tag: "burst_high_risk", reasons: [...]}

然后 planner:
    pool = [r for r in recipe_knowledge
            if r.strength_overall >= result['min_strength']
            and r.beat_l3_phash >= result['min_l3']]
"""
from __future__ import annotations

import logging
import sqlite3
from datetime import datetime, timedelta
from typing import Any

from core.app_config import get as cfg_get

log = logging.getLogger(__name__)


def _connect():
    from core.config import DB_PATH
    c = sqlite3.connect(DB_PATH, timeout=30)
    c.execute("PRAGMA busy_timeout=30000")
    c.execute("PRAGMA journal_mode=WAL")
    c.execute("PRAGMA synchronous=NORMAL")
    c.row_factory = sqlite3.Row
    return c


# ─────────────────────────────────────────────────────────────
# 基础 tier → min_strength 映射
# ─────────────────────────────────────────────────────────────

_TIER_MIN = {
    "new":         2,
    "testing":     2,
    "warming_up":  3,
    "established": 4,
    "viral":       5,
    "frozen":      1,   # 冷却期无所谓, 省资源
}

_TIER_MIN_L3 = {
    "new":         2,
    "testing":     2,
    "warming_up":  3,
    "established": 3,
    "viral":       4,
    "frozen":      1,
}


# ─────────────────────────────────────────────────────────────
# 风险信号
# ─────────────────────────────────────────────────────────────

def _same_drama_recent_count(drama_name: str, hours: int = 72) -> int:
    """同剧近 N 小时被多少不同账号发过 (越多越危险)."""
    cutoff = (datetime.now() - timedelta(hours=hours)).strftime("%Y-%m-%d %H:%M:%S")
    try:
        with _connect() as c:
            r = c.execute(
                """SELECT COUNT(DISTINCT account_id) AS n FROM task_queue
                   WHERE drama_name = ?
                     AND status IN ('running', 'success')
                     AND datetime(created_at) >= ?""",
                (drama_name, cutoff),
            ).fetchone()
            return r["n"] if r else 0
    except Exception as e:
        log.debug("[scenario] same_drama_recent_count failed: %s", e)
        return 0


def _account_recent_fail_count(account_id: int | str, hours: int = 6) -> int:
    """账号近 N 小时失败 task 数."""
    cutoff = (datetime.now() - timedelta(hours=hours)).strftime("%Y-%m-%d %H:%M:%S")
    try:
        with _connect() as c:
            r = c.execute(
                """SELECT COUNT(*) AS n FROM task_queue
                   WHERE account_id = ?
                     AND status IN ('failed', 'dead_letter')
                     AND datetime(finished_at) >= ?""",
                (str(account_id), cutoff),
            ).fetchone()
            return r["n"] if r else 0
    except Exception as e:
        log.debug("[scenario] account_recent_fail_count failed: %s", e)
        return 0


def _same_mcn_same_drama_density(drama_name: str, hours: int = 24) -> int:
    """同 MCN (org=10) 同剧近 N 小时密度 — mcn_member_snapshots 粗估.

    限制: 我们只有 13 账号真实数据, 所以这里只能算自己账号.
    若有更完整 MCN 数据接入, 可替换实现.
    """
    cutoff = (datetime.now() - timedelta(hours=hours)).strftime("%Y-%m-%d %H:%M:%S")
    try:
        with _connect() as c:
            r = c.execute(
                """SELECT COUNT(*) AS n FROM task_queue tq
                   JOIN device_accounts da ON tq.account_id = CAST(da.id AS TEXT)
                   WHERE tq.drama_name = ?
                     AND tq.status IN ('running', 'success')
                     AND datetime(tq.created_at) >= ?""",
                (drama_name, cutoff),
            ).fetchone()
            return r["n"] if r else 0
    except Exception as e:
        log.debug("[scenario] mcn_density failed: %s", e)
        return 0


# ─────────────────────────────────────────────────────────────
# 主入口
# ─────────────────────────────────────────────────────────────

def score_scenario(
    account: dict | None = None,
    drama_name: str = "",
    task_source: str = "planner",
    experiment_group: str | None = None,
) -> dict[str, Any]:
    """推算当前场景下 recipe 的最低要求.

    Args:
        account: {id, tier} dict (来自 device_accounts)
        drama_name: 剧名
        task_source: planner / burst / experiment / maintenance
        experiment_group: A/B/C (实验组可强制用特定 recipe, 不过 scenario 不干涉)

    Returns:
        {
          "min_strength": 1-5,
          "min_l3": 1-5,
          "min_ks184_alignment": 0.0-1.0,
          "scenario_tag": "planner_warming_up" / "burst_high" / "experiment_A" / ...,
          "reasons": [{"rule": "...", "weight": N}, ...],
          "signals": {...} (debug 用)
        }
    """
    reasons = []
    signals = {}

    # 基线: tier
    tier = (account or {}).get("tier", "testing")
    base = _TIER_MIN.get(tier, 2)
    base_l3 = _TIER_MIN_L3.get(tier, 2)
    reasons.append({"rule": f"tier={tier}", "min_strength": base})

    min_strength = base
    min_l3 = base_l3

    # 信号 1: burst task_source → 直上 5
    if task_source == "burst":
        min_strength = max(min_strength, 5)
        min_l3 = max(min_l3, 4)
        reasons.append({"rule": "burst 扩散", "min_strength": 5})

    # 信号 2: experiment → 不强制 (由 planner.EXPERIMENT_VARIANTS 决定 recipe)
    if task_source == "experiment":
        # 实验组:  不干涉 strength (变量就是 recipe). 但 L3 要 ≥ 2 避免全判重
        min_l3 = max(min_l3, 2)
        reasons.append({"rule": f"experiment_{experiment_group or '?'}", "min_strength": 2})

    # 信号 3: 同剧 72h 多账号爬 ≥ 5
    n_same = _same_drama_recent_count(drama_name, 72) if drama_name else 0
    signals["same_drama_72h"] = n_same
    if n_same >= 5:
        min_strength = max(min_strength, 4)
        min_l3 = max(min_l3, 4)
        reasons.append({"rule": f"same_drama_72h={n_same} (≥5 升 4)",
                         "min_strength": 4})

    # 信号 4: 账号近 6h 失败 ≥ 2
    acc_id = (account or {}).get("id", 0)
    n_fail = _account_recent_fail_count(acc_id, 6) if acc_id else 0
    signals["account_recent_fails_6h"] = n_fail
    if n_fail >= 2:
        min_strength = max(min_strength, 4)
        reasons.append({"rule": f"recent_fails_6h={n_fail} (≥2 升 4)",
                         "min_strength": 4})

    # 信号 5: 同 MCN 同剧 24h 密度 ≥ 3
    n_mcn = _same_mcn_same_drama_density(drama_name, 24) if drama_name else 0
    signals["mcn_same_drama_24h"] = n_mcn
    if n_mcn >= 3:
        min_strength = max(min_strength, 5)
        min_l3 = max(min_l3, 4)
        reasons.append({"rule": f"mcn_density_24h={n_mcn} (≥3 升 5)",
                         "min_strength": 5})

    # 对齐度要求: burst/high_risk 场景要求高对齐 ≥ 0.7
    min_align = float(cfg_get("ai.recipe_knowledge.min_ks184_alignment", 0.5))
    if task_source == "burst" or n_same >= 5:
        min_align = max(min_align, 0.7)

    # 场景 tag
    if task_source == "burst":
        tag = "burst_high"
    elif task_source == "experiment":
        tag = f"experiment_{experiment_group or 'X'}"
    elif n_same >= 5:
        tag = f"same_drama_hot_{tier}"
    elif n_fail >= 2:
        tag = f"failing_{tier}"
    else:
        tag = f"planner_{tier}"

    return {
        "min_strength": min_strength,
        "min_l3": min_l3,
        "min_ks184_alignment": min_align,
        "scenario_tag": tag,
        "reasons": reasons,
        "signals": signals,
    }


# min_strength (1-5 档) → strength_overall 浮点阈值
# 考虑到 strength_overall = 5 层平均, L4 全系 1 拖累, 真实最高 ~3.8
_STRENGTH_THRESHOLD_MAP = {
    1: 1.0,   # 所有 recipe 都可入池 (只排除错误数据)
    2: 2.0,   # 排除 mvp (2.8 仍然满足) — 实际允许 mvp (但 L3/L2 过得去)
    3: 2.8,   # 排除 mvp (2.8), 其他 9 个
    4: 3.2,   # 只要中强以上
    5: 3.5,   # 最强组: touming/mode5/kirin (全 3.8)
}


def query_recipe_pool(
    min_strength: int,
    min_l3: int = 0,
    min_ks184_alignment: float = 0.0,
) -> list[dict]:
    """从 recipe_knowledge 里选满足条件的 recipe.

    min_strength 用 1-5 档, 内部映射到 strength_overall 浮点阈值.

    Returns:
        list of dict, 按 strength_overall DESC. 空 list 表示没满足的.
    """
    threshold = _STRENGTH_THRESHOLD_MAP.get(min_strength, 2.0)
    try:
        with _connect() as c:
            rows = c.execute(
                """SELECT recipe_name, strength_overall,
                          beat_l1_bytes, beat_l2_meta, beat_l3_phash,
                          beat_l4_audio, beat_l5_cnn,
                          ks184_alignment, alignment_status,
                          cost_sec, cost_mb, notes
                   FROM recipe_knowledge
                   WHERE strength_overall >= ?
                     AND beat_l3_phash >= ?
                     AND ks184_alignment >= ?
                   ORDER BY strength_overall DESC, beat_l3_phash DESC""",
                (threshold, min_l3, min_ks184_alignment),
            ).fetchall()
        return [dict(r) for r in rows]
    except sqlite3.OperationalError:
        return []


def pick_recipe_from_scenario(
    account: dict | None = None,
    drama_name: str = "",
    task_source: str = "planner",
    experiment_group: str | None = None,
) -> tuple[str | None, dict]:
    """端到端入口: scenario → pool → 加权抽 1 个 recipe.

    Returns:
        (recipe_name | None, info_dict)
        None 表示池空 (调用方应 fallback 到老逻辑)
    """
    scenario = score_scenario(account, drama_name, task_source, experiment_group)
    pool = query_recipe_pool(
        min_strength=scenario["min_strength"],
        min_l3=scenario["min_l3"],
        min_ks184_alignment=scenario["min_ks184_alignment"],
    )

    if not pool:
        # 降 min_strength 1 档再试 (兜底)
        relaxed = max(1, scenario["min_strength"] - 1)
        pool = query_recipe_pool(
            min_strength=relaxed,
            min_l3=max(1, scenario["min_l3"] - 1),
            min_ks184_alignment=0.0,
        )
        if pool:
            scenario["reasons"].append({"rule": f"relaxed to {relaxed}",
                                         "pool_size": len(pool)})
        else:
            return None, {"scenario": scenario, "pool": [],
                          "error": "no_recipe_satisfies"}

    # 加权随机 (综合星高的更常被选)
    import random
    weights = [max(0.1, r["strength_overall"]) for r in pool]
    pick = random.choices(pool, weights=weights, k=1)[0]

    return pick["recipe_name"], {
        "scenario": scenario,
        "pool_size": len(pool),
        "pool_top3": [(r["recipe_name"], r["strength_overall"]) for r in pool[:3]],
        "picked": pick,
    }


# ─────────────────────────────────────────────────────────────
# CLI (dev testing)
# ─────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import argparse, json, sys
    sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser()
    ap.add_argument("--tier", default="established")
    ap.add_argument("--account-id", type=int, default=0)
    ap.add_argument("--drama", default="test_drama")
    ap.add_argument("--source", default="planner",
                    choices=["planner", "burst", "experiment", "maintenance"])
    ap.add_argument("--exp-group", default=None)
    ap.add_argument("--show-pool", action="store_true")
    args = ap.parse_args()

    account = {"id": args.account_id, "tier": args.tier}

    print(f"=== scenario_scorer test ===")
    print(f"account: tier={args.tier} id={args.account_id}")
    print(f"drama: {args.drama}")
    print(f"task_source: {args.source}")

    scen = score_scenario(account, args.drama, args.source, args.exp_group)
    print(f"\nscenario:")
    print(json.dumps(scen, ensure_ascii=False, indent=2))

    if args.show_pool:
        pool = query_recipe_pool(
            scen["min_strength"], scen["min_l3"], scen["min_ks184_alignment"])
        print(f"\n候选 pool ({len(pool)} 个):")
        for p in pool:
            print(f"  {p['recipe_name']:30s} strength={p['strength_overall']:.1f} "
                  f"L3={p['beat_l3_phash']}/5 ks184={p['ks184_alignment']*100:.0f}%")

    recipe, info = pick_recipe_from_scenario(
        account, args.drama, args.source, args.exp_group)
    print(f"\nPicked: {recipe}")
    if info.get("pool_top3"):
        print(f"Top 3 candidates: {info['pool_top3']}")
