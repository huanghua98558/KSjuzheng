# -*- coding: utf-8 -*-
"""账号分层状态机 — 6 状态自动迁移.

状态:
    new            刚录入, 未验证过
    testing        测试期 (每日 3 条混搭 recipe, 观察播放)
    warming_up     起号中 (每日 5 条, 保留 TESTING 阶段 top recipe)
    established    起号成功 (每日 8 条, Bandit 选剧)
    viral          爆款 (每日 12 条, 全力倾斜)
    frozen         冻结 (限流/风控/0 播放 > 48h, 冷却 48h 后回 testing)

迁移规则 (从 app_config 读):
    ai.tier.testing.max_days         = 7    # 超 N 天无起色 → frozen
    ai.tier.testing.min_avg_views    = 500  # → warming_up 门槛
    ai.tier.warming.min_income       = 5.0  # → established 累计收益
    ai.tier.warming.min_viral_view   = 5000 # → established 单视频播放
    ai.tier.established.min_daily_income = 20.0  # → viral 日收益
    ai.tier.established.decay_days   = 7    # → warming_up (连续低收益天数)
    ai.tier.viral.decay_days         = 3    # → established
    ai.tier.frozen.cooldown_hours    = 48   # → testing
"""
from __future__ import annotations

import json
import logging
import sqlite3
from datetime import datetime, timedelta
from typing import Any

from core.app_config import get as cfg_get

log = logging.getLogger(__name__)

TIERS = ("new", "testing", "warming_up", "established", "viral", "frozen")


def _connect():
    from core.config import DB_PATH
    c = sqlite3.connect(DB_PATH, timeout=30)
    c.execute("PRAGMA busy_timeout=30000")
    c.execute("PRAGMA journal_mode=WAL")
    c.execute("PRAGMA synchronous=NORMAL")
    c.row_factory = sqlite3.Row
    return c


# ──────────────────────────────────────────────────────────────
# 状态查询
# ──────────────────────────────────────────────────────────────

def get_account_tier(account_id: int) -> dict[str, Any]:
    """读账号当前 tier + 进入时间."""
    with _connect() as c:
        r = c.execute(
            """SELECT id, account_name, tier, tier_since, frozen_reason, login_status
               FROM device_accounts WHERE id=?""",
            (account_id,)).fetchone()
    return dict(r) if r else {}


def list_accounts_by_tier(tier: str | None = None) -> list[dict]:
    """按 tier 列账号, None = 所有 logged_in.

    ★ 2026-04-23: 加 account_age_days / created_at / vertical_category
    等字段, 让 operation_policy 能按年龄动态 quota + 垂直判定.
    """
    cols = ("id, account_name, kuaishou_uid, tier, tier_since, "
            "account_age_days, created_at, vertical_category, "
            "vertical_locked, signed_status")
    # ★ 2026-04-23 修 1: 只派任务给 signed='signed' 的账号
    # 原因: unsigned 账号发 → 必 80004 "无作者变现权限", 浪费 8-15min pipeline
    # 如账号主手工开通萤光后, signed_status 自动变 signed, 立即恢复派任务
    from core.app_config import get as _cfg_get
    require_signed = str(_cfg_get("ai.planner.require_signed", "true")).lower() in ("true", "1", "yes")

    with _connect() as c:
        if tier:
            rows = c.execute(
                f"""SELECT {cols} FROM device_accounts
                   WHERE tier=? AND login_status='logged_in'
                     {" AND signed_status='signed'" if require_signed else ""}
                   ORDER BY id""", (tier,)).fetchall()
        else:
            rows = c.execute(
                f"""SELECT {cols} FROM device_accounts
                   WHERE login_status='logged_in'
                     {" AND signed_status='signed'" if require_signed else ""}
                   ORDER BY id""").fetchall()
    result = []
    for r in rows:
        d = dict(r)
        # creator_level schema 未存 (快手 API 未接), 默认 None fallback 到 tier_mapping
        d.setdefault("creator_level", None)
        result.append(d)
    return result


def tier_distribution() -> dict[str, int]:
    """当前矩阵的 tier 分布."""
    with _connect() as c:
        rows = c.execute(
            """SELECT tier, COUNT(*) n FROM device_accounts
               WHERE login_status='logged_in' GROUP BY tier""").fetchall()
    d = {t: 0 for t in TIERS}
    for r in rows:
        if r["tier"]:
            d[r["tier"]] = r["n"]
    return d


# ──────────────────────────────────────────────────────────────
# 迁移
# ──────────────────────────────────────────────────────────────

def transition(
    account_id: int,
    to_tier: str,
    reason: str = "",
    metrics: dict | None = None,
) -> bool:
    """迁移账号到新 tier + 写 transitions 审计."""
    if to_tier not in TIERS:
        raise ValueError(f"invalid tier: {to_tier}")

    with _connect() as c:
        current = c.execute(
            "SELECT tier FROM device_accounts WHERE id=?", (account_id,)
        ).fetchone()
        if not current:
            return False
        from_tier = current["tier"]
        if from_tier == to_tier:
            return False   # 无变化

        # 更新账号
        frozen_reason = reason if to_tier == "frozen" else None
        c.execute(
            """UPDATE device_accounts SET
                 tier=?, tier_since=datetime('now','localtime'),
                 frozen_reason=?
               WHERE id=?""",
            (to_tier, frozen_reason, account_id))
        # 写审计
        c.execute(
            """INSERT INTO account_tier_transitions
                 (account_id, from_tier, to_tier, reason, metrics_json)
               VALUES (?, ?, ?, ?, ?)""",
            (account_id, from_tier, to_tier, reason[:500],
             json.dumps(metrics, ensure_ascii=False) if metrics else None))
        c.commit()

    log.info("[tier] account=%s %s → %s (%s)",
             account_id, from_tier, to_tier, reason[:80])
    return True


# ──────────────────────────────────────────────────────────────
# 每日自动迁移 (由 Analyzer 调用)
# ──────────────────────────────────────────────────────────────

def _days_since(ts_str: str | None) -> float:
    if not ts_str:
        return 0
    try:
        ts = datetime.fromisoformat(ts_str.replace(" ", "T"))
        return (datetime.now() - ts).total_seconds() / 86400
    except Exception:
        return 0


def _hours_since(ts_str: str | None) -> float:
    return _days_since(ts_str) * 24


def evaluate_account_tier(account_id: int) -> dict[str, Any]:
    """评估单账号是否应迁移 tier. 返回决策 dict.

    ★ 2026-04-22 §28_N 根本修复: tier 判定不再依赖 views (永远采不到),
    改用**可观测且自动采集的 3 指标**:
      1. publishes_success (本地 publish_results, 实时)
      2. success_rate (成功 / 总发)
      3. income_delta (MCN 日快照, 滞后 48h 但权威)

    设计晋升 ladder (新):
      new         → testing:    login_status=logged_in (立即)
      testing     → warming_up: ≥3 success AND success_rate ≥ 50% (近 7 天)
      warming_up  → established: ≥10 success AND income ≥ ¥1 / 总收益 ≥ ¥3
      established → viral:       ≥30 success AND 日均 income ≥ ¥5
      viral       → established: 连续 3 天日均 income < ¥2 降级
      established → warming_up:  连续 7 天 income < ¥0.3 降级
      warming_up  → testing:     连续 14 天 0 success 降级

    冻结规则:
      testing 超 14 天无 success → frozen
      warming_up 超 21 天无收益 → frozen
      session 错连 3+ (watchdog 处理) → frozen

    frozen 复活:
      frozen 超 48h AND 账号在 MCN fluorescent → testing
    """
    acc = get_account_tier(account_id)
    if not acc:
        return {"account_id": account_id, "error": "not_found"}
    current = acc["tier"]
    tier_since_days = _days_since(acc["tier_since"])

    # 聚合最近 N 天指标 (daily_metrics 汇总)
    lookback = cfg_get("ai.analyzer.lookback_days", 7)
    with _connect() as c:
        rows = c.execute(
            """SELECT publishes_success, publishes_attempted, total_views, total_likes,
                     income_delta, metric_date
               FROM publish_daily_metrics
               WHERE account_id = ?
                 AND metric_date >= date('now', ?)
               ORDER BY metric_date DESC""",
            (account_id, f"-{lookback} days")
        ).fetchall()

        # 直接从 publish_results 算 (不依赖 metrics 聚合):
        pub_stats = c.execute(
            """SELECT COUNT(*) total, SUM(CASE WHEN publish_status='success' THEN 1 ELSE 0 END) ok
               FROM publish_results
               WHERE CAST(account_id AS INTEGER) = ?
                 AND DATE(created_at) >= date('now', ?)""",
            (account_id, f"-{lookback} days")
        ).fetchone()

    n_days = len(rows)
    total_views = sum((r["total_views"] or 0) for r in rows)
    total_income = sum((r["income_delta"] or 0) for r in rows)
    avg_views = total_views / n_days if n_days else 0
    avg_daily_income = total_income / n_days if n_days else 0
    max_single_view = max((r["total_views"] or 0) for r in rows) if rows else 0

    pub_total = pub_stats[0] if pub_stats else 0
    pub_success = pub_stats[1] or 0 if pub_stats else 0
    success_rate = pub_success / pub_total if pub_total > 0 else 0.0

    metrics = {
        "n_days": n_days, "tier_since_days": round(tier_since_days, 2),
        "publishes_attempted_{}d".format(lookback): pub_total,
        "publishes_success_{}d".format(lookback): pub_success,
        "success_rate": round(success_rate, 3),
        "total_views": total_views, "total_income": round(total_income, 2),
        "avg_views": round(avg_views, 1),
        "avg_daily_income": round(avg_daily_income, 2),
        "max_single_view": max_single_view,
    }

    # 决策逻辑
    target = current
    reason = ""

    # ═ FROZEN: 冷却足够 → 回 testing ═
    if current == "frozen":
        cooldown = cfg_get("ai.tier.frozen.cooldown_hours", 48)
        h = _hours_since(acc["tier_since"])
        # ★ 2026-04-22 §28_N: 只有 frozen_reason 是 "not_in_mcn_fluorescent"
        # 需要手工加 MCN 后才能复活 (否则会无限循环冻结)
        frozen_reason = acc.get("frozen_reason") or ""
        is_mcn_issue = "not_in_mcn_fluorescent" in frozen_reason or "mcn_not_joined" in frozen_reason
        if h >= cooldown and not is_mcn_issue:
            target = "testing"
            reason = f"frozen 冷却 {h:.1f}h ≥ {cooldown}h, 回 testing 重新观察"

    # ═ NEW → TESTING ═
    elif current == "new":
        if acc.get("login_status") == "logged_in":
            target = "testing"
            reason = "新账号登录成功 → 进入测试期"

    # ═ TESTING → WARMING_UP (★ 基于 success, 不依赖 views) ═
    elif current == "testing":
        # 新规则: ≥3 success AND success_rate ≥ 50%
        min_success = cfg_get("ai.tier.testing.min_success", 3)
        min_rate = cfg_get("ai.tier.testing.min_success_rate", 0.5)
        testing_frozen_days = cfg_get("ai.tier.testing.frozen_after_days", 14)

        if pub_success >= min_success and success_rate >= min_rate:
            target = "warming_up"
            reason = (f"TESTING 达标: {pub_success} 成功 / {pub_total} 发 "
                      f"(rate={success_rate:.0%} ≥ {min_rate:.0%})")
        elif tier_since_days >= testing_frozen_days and pub_success == 0:
            target = "frozen"
            reason = f"TESTING {testing_frozen_days} 天无 success, 冻结"

    # ═ WARMING_UP → ESTABLISHED (基于累计 success + income) ═
    elif current == "warming_up":
        min_success_est = cfg_get("ai.tier.warming.min_success_for_est", 10)
        min_income_est = cfg_get("ai.tier.warming.min_income_for_est", 3.0)
        min_vv = cfg_get("ai.tier.warming.min_viral_view", 5000)
        warming_frozen_days = cfg_get("ai.tier.warming.frozen_after_days", 21)

        if pub_success >= min_success_est and total_income >= min_income_est:
            target = "established"
            reason = (f"WARMING_UP 达标: {pub_success} 成功 + ¥{total_income:.2f} "
                      f"≥ {min_success_est} success + ¥{min_income_est}")
        elif max_single_view >= min_vv:
            target = "established"
            reason = f"WARMING_UP 爆款单视频 {max_single_view} ≥ {min_vv}"
        elif tier_since_days >= warming_frozen_days and total_income < 0.5:
            target = "frozen"
            reason = f"WARMING_UP {warming_frozen_days} 天仍 ¥{total_income:.2f}, 冻结"
        elif tier_since_days >= 14 and pub_success == 0:
            target = "testing"
            reason = f"WARMING_UP 14 天 0 success, 降级 testing"

    # ═ ESTABLISHED → VIRAL ═
    elif current == "established":
        min_viral = cfg_get("ai.tier.established.min_daily_income", 5.0)
        decay = cfg_get("ai.tier.established.decay_days", 7)
        if n_days >= 3 and all((r["income_delta"] or 0) >= min_viral for r in rows[:3]):
            target = "viral"
            reason = f"ESTABLISHED 连续 3 天 > ¥{min_viral} → VIRAL"
        elif n_days >= decay and all((r["income_delta"] or 0) < 0.3 for r in rows[:decay]):
            target = "warming_up"
            reason = f"ESTABLISHED 连续 {decay} 天 < ¥0.3, 降级 warming_up"

    # ═ VIRAL → ESTABLISHED ═
    elif current == "viral":
        decay = cfg_get("ai.tier.viral.decay_days", 3)
        if n_days >= decay and all((r["income_delta"] or 0) < 2 for r in rows[:decay]):
            target = "established"
            reason = f"VIRAL 连续 {decay} 天 < ¥2 → ESTABLISHED"

    return {
        "account_id": account_id,
        "account_name": acc.get("account_name"),
        "current_tier": current,
        "target_tier": target,
        "should_transition": target != current,
        "reason": reason,
        "metrics": metrics,
    }


def run_tier_evaluation(dry_run: bool = False) -> dict:
    """批量评估所有 logged_in 账号, 自动迁移 (除非 dry_run).

    Analyzer 每日调用.
    """
    accounts = list_accounts_by_tier()
    transitions_applied = []
    for acc in accounts:
        result = evaluate_account_tier(acc["id"])
        if result.get("should_transition"):
            if not dry_run:
                transition(acc["id"], result["target_tier"],
                           reason=result["reason"],
                           metrics=result["metrics"])
            transitions_applied.append(result)
    return {
        "evaluated": len(accounts),
        "transitioned": len(transitions_applied),
        "dry_run": dry_run,
        "transitions": transitions_applied,
        "distribution_after": tier_distribution(),
    }


if __name__ == "__main__":
    import argparse, json, sys
    sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser()
    ap.add_argument("--dist", action="store_true", help="打印 tier 分布")
    ap.add_argument("--eval", type=int, help="评估单账号")
    ap.add_argument("--run", action="store_true", help="跑一次 tier evaluation (dry-run)")
    ap.add_argument("--apply", action="store_true", help="真的迁移")
    args = ap.parse_args()

    if args.dist:
        print(json.dumps(tier_distribution(), ensure_ascii=False, indent=2))
    elif args.eval:
        print(json.dumps(evaluate_account_tier(args.eval), ensure_ascii=False, indent=2))
    elif args.run or args.apply:
        r = run_tier_evaluation(dry_run=not args.apply)
        print(json.dumps(r, ensure_ascii=False, indent=2, default=str))
    else:
        ap.print_help()
