# -*- coding: utf-8 -*-
"""自动选剧 — 从 drama_banner_tasks 按策略选 N 条给 Scheduler/Executor.

3 种策略 (by config `selector.strategy`):
  - top_by_income        : 永远挑 TOP N 按 recent_income_sum 排
  - top_weighted_random  : 从 TOP K 按收益加权抽 (推荐, 默认)
  - pure_random          : 从候选池纯随机 (探索冷门)

过滤层 (进入候选池之前):
  - recent_income_sum >= selector.drama.min_income_30d  (默认 ¥50)
  - recent_income_count >= selector.drama.min_income_count (默认 3)
  - 同账号 selector.drama.account_cooldown_days 内未发过 (默认 7 天)

使用:
    from core.drama_selector import select_for_account
    dramas = select_for_account(account_id=3, n=5)
    # → [{drama_name, banner_task_id, score, reason}, ...]
"""
from __future__ import annotations

import logging
import random
import sqlite3
from typing import Any

from core.app_config import get as cfg_get

log = logging.getLogger(__name__)

STRATEGIES = ("top_by_income", "top_weighted_random", "pure_random")


def _connect():
    from core.config import DB_PATH
    c = sqlite3.connect(DB_PATH, timeout=10)
    c.row_factory = sqlite3.Row
    return c


def _candidate_pool(
    conn: sqlite3.Connection,
    account_id: int | None = None,
    min_income: float | None = None,
    min_count: int | None = None,
    cooldown_days: int | None = None,
) -> list[dict]:
    """过滤出候选剧池 (按过滤规则)."""
    min_income = cfg_get("selector.drama.min_income_30d", 50) if min_income is None else min_income
    min_count = cfg_get("selector.drama.min_income_count", 3) if min_count is None else min_count
    cooldown_days = cfg_get("selector.drama.account_cooldown_days", 7) if cooldown_days is None else cooldown_days

    sql = """
        SELECT drama_name, banner_task_id, commission_rate,
               recent_income_sum, recent_income_count, last_income_at,
               promotion_type, entrance_type, bind_task_type
        FROM drama_banner_tasks
        WHERE recent_income_sum >= ?
          AND recent_income_count >= ?
    """
    params: list = [float(min_income), int(min_count)]

    # 同账号冷却: 排除 publish_results 里近 N 天用过的 drama_name
    if account_id is not None and cooldown_days > 0:
        sql += """
          AND drama_name NOT IN (
              SELECT drama_name FROM publish_results
              WHERE account_id = ?
                AND datetime(created_at) >= datetime('now', ?)
                AND publish_status = 'success'
          )
        """
        params.extend([str(account_id), f"-{cooldown_days} days"])

    sql += " ORDER BY recent_income_sum DESC"
    rows = conn.execute(sql, params).fetchall()
    return [dict(r) for r in rows]


def _strategy_top_by_income(pool: list[dict], n: int) -> list[dict]:
    out = []
    for r in pool[:n]:
        r2 = dict(r)
        r2["_score"] = r["recent_income_sum"]
        r2["_reason"] = f"TOP_BY_INCOME #{len(out)+1} ¥{r['recent_income_sum']:.0f}"
        out.append(r2)
    return out


def _strategy_top_weighted_random(pool: list[dict], n: int) -> list[dict]:
    """从 TOP K 按 recent_income_sum 加权抽样."""
    top_k = cfg_get("selector.drama.topN_pool", 50)
    candidates = pool[:top_k]
    if not candidates:
        return []

    weights = [max(0.01, float(c["recent_income_sum"])) for c in candidates]
    picked = []
    used_idx: set[int] = set()
    for _ in range(min(n, len(candidates))):
        # 按权重抽一个 (排除已选)
        remaining = [(i, c, w) for i, (c, w) in enumerate(zip(candidates, weights))
                    if i not in used_idx]
        if not remaining:
            break
        indices = [i for i, _, _ in remaining]
        items = [c for _, c, _ in remaining]
        ws = [w for _, _, w in remaining]
        idx = random.choices(range(len(remaining)), weights=ws, k=1)[0]
        used_idx.add(indices[idx])
        c = dict(items[idx])
        c["_score"] = c["recent_income_sum"]
        c["_reason"] = f"WEIGHTED_RANDOM ¥{c['recent_income_sum']:.0f}"
        picked.append(c)
    return picked


def _strategy_pure_random(pool: list[dict], n: int) -> list[dict]:
    if not pool:
        return []
    k = min(n, len(pool))
    picked = random.sample(pool, k)
    out = []
    for r in picked:
        r2 = dict(r)
        r2["_score"] = 0
        r2["_reason"] = f"PURE_RANDOM ¥{r['recent_income_sum']:.0f}"
        out.append(r2)
    return out


def select_for_account(
    account_id: int | None = None,
    n: int | None = None,
    strategy: str | None = None,
) -> list[dict[str, Any]]:
    """选 N 条剧给指定账号.

    Args:
        account_id: 账号 device_accounts.id, 用于冷却过滤. None = 不过滤冷却.
        n: 选几条. None = 读 selector.drama.batch_size (默认 5).
        strategy: 覆盖默认策略. None = 读 selector.strategy.

    Returns:
        [{drama_name, banner_task_id, recent_income_sum, _score, _reason, ...}, ...]
    """
    n = cfg_get("selector.drama.batch_size", 5) if n is None else n
    strategy = (strategy or cfg_get("selector.strategy", "top_weighted_random"))
    if strategy not in STRATEGIES:
        log.warning("[selector] unknown strategy %s, fall back to top_weighted_random", strategy)
        strategy = "top_weighted_random"

    with _connect() as c:
        pool = _candidate_pool(c, account_id=account_id)

    log.info("[selector] pool=%d strategy=%s n=%d account_id=%s",
             len(pool), strategy, n, account_id)

    if strategy == "top_by_income":
        return _strategy_top_by_income(pool, n)
    if strategy == "top_weighted_random":
        return _strategy_top_weighted_random(pool, n)
    if strategy == "pure_random":
        return _strategy_pure_random(pool, n)
    return []


def pool_stats() -> dict:
    """看候选池长啥样 (dashboard / CLI 诊断用)."""
    with _connect() as c:
        total = c.execute("SELECT COUNT(*) FROM drama_banner_tasks").fetchone()[0]
        has_income = c.execute(
            "SELECT COUNT(*) FROM drama_banner_tasks WHERE recent_income_sum > 0"
        ).fetchone()[0]
        pool_default = _candidate_pool(c)
        sum_30d = sum(r["recent_income_sum"] or 0 for r in pool_default)
    return {
        "total_dramas": total,
        "has_income_30d": has_income,
        "pool_after_filter": len(pool_default),
        "pool_total_income_30d": round(sum_30d, 2),
        "filter_min_income": cfg_get("selector.drama.min_income_30d", 50),
        "filter_min_count": cfg_get("selector.drama.min_income_count", 3),
    }


if __name__ == "__main__":
    import argparse, json
    ap = argparse.ArgumentParser()
    ap.add_argument("--account", type=int, default=3)
    ap.add_argument("--n", type=int, default=5)
    ap.add_argument("--strategy", default=None)
    ap.add_argument("--stats", action="store_true")
    args = ap.parse_args()

    if args.stats:
        print(json.dumps(pool_stats(), indent=2, ensure_ascii=False))
    else:
        picks = select_for_account(account_id=args.account, n=args.n,
                                     strategy=args.strategy)
        for p in picks:
            print(f"  {p['drama_name'][:20]:<22} biz={p['banner_task_id']:<8} "
                  f"¥{p['recent_income_sum']:<7.0f} {p['_reason']}")
