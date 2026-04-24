# -*- coding: utf-8 -*-
"""账号决策记忆系统 — 三层 API.

架构:
    Layer 1  account_decision_history  事件级 (每决策 1 行)
    Layer 2  account_strategy_memory   聚合级 (每账号 1 行)
    Layer 3  account_diary_entries     文本级 (每周 1 篇 LLM)

核心用法:

    # 决策时 (planner 调):
    from core.account_memory import record_decision, get_account_context
    ctx = get_account_context(account_id=5, days=30)
    # ctx 含: preferred_genres, avoid_ids, ai_trust_score, 最近 30 天决策概要

    # 决策后立即记:
    record_decision(
        account_id=5, plan_item_id=123, task_id="task_xxx",
        drama_name="小小武神不好惹", recipe="zhizun_mode5",
        image_mode="qitian_art",
        decision_type="exploit_high_tier",
        hypothesis="viral 账号 + 热剧 → 预期 ¥5",
        confidence=0.75,
        score_breakdown={"tier":90, "income":15, "heat":22},
        expected_outcome={"income_est":5.0, "views_est":3000},
    )

    # 执行完后 (analyzer 调):
    from core.account_memory import record_actual_and_verdict
    record_actual_and_verdict(
        task_id="task_xxx",
        actual={"income":0.07, "views":120, "status":"success"},
    )
    # 自动算 verdict (correct/over_optimistic/...) 并更新 trust_score

    # 每日聚合 (analyzer 调):
    from core.account_memory import rebuild_strategy_memory
    rebuild_strategy_memory(account_id=5)
    # 从 decision_history + publish_results 聚合偏好/避雷/信任分

    # 周记 (LLMResearcher 调):
    from core.account_memory import save_diary_entry, load_recent_diaries
    save_diary_entry(account_id=5, diary_date="2026-04-21", ...)
"""
from __future__ import annotations

import json
import logging
import sqlite3
from datetime import datetime, timedelta
from typing import Any

log = logging.getLogger(__name__)


def _connect() -> sqlite3.Connection:
    """WAL + busy_timeout 版 (2026-04-20 修 record_decision DB lock 问题).

    用途场景: dashboard 长期 reader + planner/analyzer 高频 writer 并发.
    以前 timeout=15 的 SQLite 默认事务在 dashboard 长连接时易 lock.
    现在: busy_timeout=30s + WAL 模式允许多 reader + 单 writer 并发.
    """
    from core.config import DB_PATH
    c = sqlite3.connect(DB_PATH, timeout=30)
    c.execute("PRAGMA busy_timeout=30000")
    c.execute("PRAGMA journal_mode=WAL")
    c.execute("PRAGMA synchronous=NORMAL")
    c.row_factory = sqlite3.Row
    return c


def _json_dump(v: Any) -> str:
    if v is None:
        return ""
    if isinstance(v, str):
        return v
    try:
        return json.dumps(v, ensure_ascii=False, default=str)
    except Exception:
        return str(v)


def _json_load(s: str | None) -> Any:
    if not s:
        return None
    try:
        return json.loads(s)
    except Exception:
        return s


# ═══════════════════════════════════════════════════════════════
# Layer 1: account_decision_history — 事件级
# ═══════════════════════════════════════════════════════════════

def record_decision(
    *,
    account_id: int,
    plan_item_id: int | None = None,
    task_id: str | None = None,
    drama_name: str = "",
    recipe: str = "",
    image_mode: str = "",
    decision_type: str = "",
    hypothesis: str = "",
    confidence: float = 0.5,
    score_breakdown: dict | None = None,
    alternatives: list | None = None,
    expected_outcome: dict | None = None,
    decision_date: str | None = None,
) -> int | None:
    """在 planner 决策时立即调. 写 Layer 1 事件."""
    if decision_date is None:
        decision_date = datetime.now().strftime("%Y-%m-%d")

    try:
        with _connect() as c:
            cur = c.execute(
                """INSERT INTO account_decision_history
                     (account_id, decision_date, plan_item_id, task_id,
                      drama_name, recipe, image_mode,
                      decision_type, hypothesis, confidence,
                      score_breakdown, alternatives_json, expected_outcome,
                      verdict)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'pending')""",
                (account_id, decision_date, plan_item_id, task_id,
                 drama_name, recipe, image_mode,
                 decision_type, hypothesis, float(confidence),
                 _json_dump(score_breakdown),
                 _json_dump(alternatives),
                 _json_dump(expected_outcome)),
            )
            c.commit()
            return cur.lastrowid
    except Exception as e:
        log.warning("[account_memory] record_decision failed: %s", e)
        return None


def record_actual_and_verdict(
    *,
    task_id: str,
    actual: dict,
    plan_item_id: int | None = None,
) -> dict | None:
    """task 跑完后调. 写 actual_outcome + 自动算 verdict.

    Verdict 规则 (简化):
      - actual.status='failed'        → 'wrong'
      - expected.income * 0.5 <= actual.income <= expected.income * 2.0 → 'correct'
      - actual.income < expected.income * 0.5                          → 'over_optimistic'
      - actual.income > expected.income * 2.0                          → 'under_confident'
      - 其他 (没预期)                  → 'pending'
    """
    with _connect() as c:
        # 查找对应的 decision_history 行
        where = []
        params = []
        if task_id:
            where.append("task_id = ?")
            params.append(task_id)
        if plan_item_id is not None:
            where.append("plan_item_id = ?")
            params.append(plan_item_id)
        if not where:
            return None

        row = c.execute(
            f"SELECT id, expected_outcome FROM account_decision_history "
            f"WHERE {' OR '.join(where)} ORDER BY id DESC LIMIT 1",
            params,
        ).fetchone()
        if not row:
            return None

        expected = _json_load(row["expected_outcome"]) or {}
        verdict, notes = _compute_verdict(expected, actual)

        c.execute(
            """UPDATE account_decision_history SET
                 actual_outcome = ?,
                 verdict = ?,
                 verdict_notes = ?,
                 verified_at = datetime('now','localtime')
               WHERE id = ?""",
            (_json_dump(actual), verdict, notes, row["id"]),
        )
        c.commit()
        return {"decision_id": row["id"], "verdict": verdict, "notes": notes}


def _compute_verdict(expected: dict, actual: dict) -> tuple[str, str]:
    """对比预期 vs 实际, 返回 (verdict, notes)."""
    actual_status = (actual.get("status") or "").lower()
    if actual_status in ("failed", "dead_letter"):
        return "wrong", f"task {actual_status}, 预期成功"

    # ★ 2026-04-22 §28_L bug fix: `0.0 or None = None` 陷阱
    # 老代码 `actual.get('income') or actual.get('income_delta')` 当 income=0.0 时
    # falsy → fallthrough → act_income=None → 误判"缺数据" → pending.
    # 修: 显式判 is not None.
    exp_income = expected.get("income_est")
    if exp_income is None:
        exp_income = expected.get("income")
    act_income = actual.get("income")
    if act_income is None:
        act_income = actual.get("income_delta")

    if exp_income is None or act_income is None:
        return "pending", "缺少 income 数据"

    # ★ 2026-04-22 §28_M: MCN 收益滞后保护
    # publish 成功但 income=0 不一定是 over_optimistic, 可能是 MCN snapshot 还没同步.
    # 规则: publish 成功 + income=0 → verdict=pending_settlement (等 48h 后再判).
    # 旧逻辑: 所有 income=0 都被算 over_optimistic 假阳性, 导致所有 success task 都标 avoid.
    if actual_status == "success" and act_income == 0:
        age_h = actual.get("age_hours")
        if age_h is None or age_h < 48:
            return "pending", "publish 成功等 MCN 结算 (<48h)"
        # >48h 且 income 仍 0 → 真的没赚到钱

    try:
        exp_income = float(exp_income)
        act_income = float(act_income)
    except (TypeError, ValueError):
        return "pending", "income 无法转数值"

    if exp_income == 0:
        return "pending", "预期收益 0, 无法比较"

    ratio = act_income / exp_income
    if 0.5 <= ratio <= 2.0:
        return "correct", f"预期 {exp_income:.2f}, 实际 {act_income:.2f}, 比例 {ratio:.2f}"
    elif ratio < 0.5:
        return "over_optimistic", f"预期 {exp_income:.2f} → 实际 {act_income:.2f} (只 {ratio*100:.0f}%, 过度乐观)"
    else:
        return "under_confident", f"预期 {exp_income:.2f} → 实际 {act_income:.2f} (超 {ratio*100:.0f}%, 低估)"


def query_account_decisions(
    account_id: int,
    days: int = 30,
    verdict_filter: str | None = None,
    limit: int = 100,
) -> list[dict]:
    """查该账号近 N 天决策历史 (含 verdict).

    Returns: list[{id, decision_date, drama_name, recipe, confidence,
                   hypothesis, expected, actual, verdict, verdict_notes}]
    """
    where = ["account_id = ?", f"decision_date >= date('now', '-{int(days)} days', 'localtime')"]
    params = [account_id]
    if verdict_filter:
        where.append("verdict = ?")
        params.append(verdict_filter)

    with _connect() as c:
        rows = c.execute(
            f"""SELECT id, account_id, decision_date,
                       plan_item_id, task_id,
                       drama_name, recipe, image_mode,
                       decision_type, hypothesis, confidence, score_breakdown,
                       alternatives_json, expected_outcome, actual_outcome,
                       verdict, verdict_notes,
                       created_at, verified_at
                FROM account_decision_history
                WHERE {' AND '.join(where)}
                ORDER BY id DESC LIMIT ?""",
            params + [int(limit)],
        ).fetchall()

    out = []
    for r in rows:
        d = dict(r)
        # 解 JSON 字段
        for k in ("score_breakdown", "expected_outcome", "actual_outcome"):
            d[k] = _json_load(d.get(k))
        out.append(d)
    return out


# ═══════════════════════════════════════════════════════════════
# Layer 2: account_strategy_memory — 聚合级
# ═══════════════════════════════════════════════════════════════

def get_strategy_memory(account_id: int) -> dict | None:
    """查账号记忆 (单条, 每账号 1 行)."""
    with _connect() as c:
        row = c.execute(
            "SELECT * FROM account_strategy_memory WHERE account_id=?",
            (account_id,),
        ).fetchone()
        if not row:
            return None
    d = dict(row)
    # 解 JSON 字段
    for k in ("preferred_genres", "preferred_recipes", "preferred_image_modes",
              "avoid_drama_ids", "avoid_genres", "avoid_post_hours",
              "best_post_hours", "notes_json"):
        d[k] = _json_load(d.get(k))
    return d


def upsert_strategy_memory(account_id: int, patch: dict) -> None:
    """UPSERT 账号记忆 (merge 模式)."""
    current = get_strategy_memory(account_id) or {"account_id": account_id}
    for k, v in patch.items():
        if v is not None:
            current[k] = v

    # JSON 字段序列化
    json_fields = ("preferred_genres", "preferred_recipes", "preferred_image_modes",
                    "avoid_drama_ids", "avoid_genres", "avoid_post_hours",
                    "best_post_hours", "notes_json")
    serialized = {k: (_json_dump(v) if k in json_fields else v)
                   for k, v in current.items()}

    fields = ("account_id", "updated_at",
              "preferred_genres", "preferred_recipes", "preferred_image_modes",
              "avoid_drama_ids", "avoid_genres", "avoid_post_hours",
              "best_post_hours",
              "total_decisions", "correct_count", "over_optimistic_count",
              "ai_trust_score", "last_verdict", "last_verdict_date",
              "total_published", "total_income_7d", "total_income_30d",
              "tier_stable_days", "notes_json")

    serialized["updated_at"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    values = [serialized.get(f) for f in fields]
    placeholders = ",".join("?" * len(fields))

    with _connect() as c:
        c.execute(
            f"INSERT OR REPLACE INTO account_strategy_memory ({','.join(fields)}) "
            f"VALUES ({placeholders})",
            values,
        )
        c.commit()


def rebuild_strategy_memory(account_id: int) -> dict:
    """从 decision_history + publish_results + mcn 聚合出当前账号记忆.

    每日 analyzer 17:00 调一次 (对所有活跃账号).
    """
    min_samples = _cfg_int("ai.memory.strategy.min_samples_for_trust", 5)

    with _connect() as c:
        # Decision stats
        stats = c.execute(
            """SELECT
                 COUNT(*) AS total,
                 SUM(CASE WHEN verdict='correct' THEN 1 ELSE 0 END) AS correct,
                 SUM(CASE WHEN verdict='over_optimistic' THEN 1 ELSE 0 END) AS over_opt,
                 MAX(verdict) AS last_v, MAX(verified_at) AS last_date
               FROM account_decision_history
               WHERE account_id = ?
                 AND verdict != 'pending'""",
            (account_id,),
        ).fetchone()

        # Recipe 成功率
        recipe_stats = c.execute(
            """SELECT recipe,
                      COUNT(*) AS n,
                      SUM(CASE WHEN verdict='correct' THEN 1 ELSE 0 END) AS c
               FROM account_decision_history
               WHERE account_id = ? AND verdict != 'pending'
               GROUP BY recipe""",
            (account_id,),
        ).fetchall()

        # Image mode 成功率
        img_stats = c.execute(
            """SELECT image_mode, COUNT(*) AS n,
                      SUM(CASE WHEN verdict='correct' THEN 1 ELSE 0 END) AS c
               FROM account_decision_history
               WHERE account_id = ? AND verdict != 'pending'
                 AND image_mode != '' AND image_mode IS NOT NULL
               GROUP BY image_mode""",
            (account_id,),
        ).fetchall()

        # 避雷: over_optimistic 的剧
        avoid_dramas = c.execute(
            """SELECT DISTINCT drama_name FROM account_decision_history
               WHERE account_id = ?
                 AND verdict IN ('over_optimistic', 'wrong')
               ORDER BY id DESC LIMIT 20""",
            (account_id,),
        ).fetchall()

        # 发布总数 + 收益 (从 publish_results 和 mcn)
        pub_stats = c.execute(
            """SELECT COUNT(*) AS n FROM publish_results
               WHERE account_id = CAST(? AS TEXT)
                 AND publish_status='success'""",
            (account_id,),
        ).fetchone()

        uid_row = c.execute(
            "SELECT numeric_uid FROM device_accounts WHERE id=?",
            (account_id,),
        ).fetchone()

        income_7d = 0.0
        income_30d = 0.0
        if uid_row and uid_row["numeric_uid"]:
            r = c.execute(
                """SELECT SUM(income_delta) AS s
                   FROM publish_daily_metrics
                   WHERE account_id = ?
                     AND metric_date >= date('now','-7 days','localtime')""",
                (account_id,),
            ).fetchone()
            income_7d = float(r["s"] or 0) if r else 0.0
            r = c.execute(
                """SELECT SUM(income_delta) AS s
                   FROM publish_daily_metrics
                   WHERE account_id = ?
                     AND metric_date >= date('now','-30 days','localtime')""",
                (account_id,),
            ).fetchone()
            income_30d = float(r["s"] or 0) if r else 0.0

    total = stats["total"] if stats else 0
    correct = stats["correct"] if stats else 0
    trust = None
    if total >= min_samples:
        trust = round(correct / total, 3)

    preferred_recipes = {}
    for r in recipe_stats:
        if r["n"] >= 2:
            preferred_recipes[r["recipe"]] = round(r["c"] / r["n"], 3)

    preferred_image_modes = {}
    for r in img_stats:
        if r["n"] >= 2:
            preferred_image_modes[r["image_mode"]] = round(r["c"] / r["n"], 3)

    patch = {
        "total_decisions": total,
        "correct_count": correct,
        "over_optimistic_count": stats["over_opt"] if stats else 0,
        "ai_trust_score": trust,
        "last_verdict": stats["last_v"] if stats else None,
        "last_verdict_date": stats["last_date"] if stats else None,
        "preferred_recipes": preferred_recipes,
        "preferred_image_modes": preferred_image_modes,
        "avoid_drama_ids": [r["drama_name"] for r in avoid_dramas],
        "total_published": pub_stats["n"] if pub_stats else 0,
        "total_income_7d": round(income_7d, 2),
        "total_income_30d": round(income_30d, 2),
    }

    upsert_strategy_memory(account_id, patch)
    return patch


def rebuild_all_strategy_memories() -> dict:
    """对所有活跃账号重建记忆."""
    with _connect() as c:
        rows = c.execute(
            "SELECT id FROM device_accounts WHERE login_status='logged_in'"
        ).fetchall()
    results = {}
    for r in rows:
        try:
            results[r["id"]] = rebuild_strategy_memory(r["id"])
        except Exception as e:
            results[r["id"]] = {"error": str(e)[:200]}
    return results


# ═══════════════════════════════════════════════════════════════
# Layer 3: account_diary_entries — 文本级 (LLM 周记)
# ═══════════════════════════════════════════════════════════════

def save_diary_entry(
    *,
    account_id: int,
    diary_date: str,
    week_range: str = "",
    summary: str = "",
    performance_review: str = "",
    lessons_learned: str = "",
    next_week_strategy: str = "",
    input_metrics: dict | None = None,
    model: str = "",
    tokens_used: int = 0,
    elapsed_sec: float = 0.0,
) -> int | None:
    try:
        with _connect() as c:
            cur = c.execute(
                """INSERT OR REPLACE INTO account_diary_entries
                     (account_id, diary_date, week_range,
                      summary, performance_review, lessons_learned,
                      next_week_strategy, input_metrics_json,
                      model, tokens_used, elapsed_sec,
                      approved)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0)""",
                (account_id, diary_date, week_range,
                 summary, performance_review, lessons_learned,
                 next_week_strategy, _json_dump(input_metrics),
                 model, tokens_used, elapsed_sec),
            )
            c.commit()
            return cur.lastrowid
    except Exception as e:
        log.warning("[account_memory] save_diary_entry failed: %s", e)
        return None


def load_recent_diaries(account_id: int, weeks: int = 4) -> list[dict]:
    with _connect() as c:
        rows = c.execute(
            """SELECT id, diary_date, week_range, summary, performance_review,
                      lessons_learned, next_week_strategy, approved, created_at
               FROM account_diary_entries
               WHERE account_id = ?
                 AND diary_date >= date('now', ?, 'localtime')
               ORDER BY diary_date DESC LIMIT ?""",
            (account_id, f"-{weeks * 7} days", int(weeks)),
        ).fetchall()
    return [dict(r) for r in rows]


def approve_diary(diary_id: int, approved_by: str = "user") -> bool:
    try:
        with _connect() as c:
            c.execute(
                """UPDATE account_diary_entries SET
                     approved=1, approved_by=?,
                     approved_at=datetime('now','localtime')
                   WHERE id=?""",
                (approved_by, int(diary_id)),
            )
            c.commit()
        return True
    except Exception:
        return False


# ═══════════════════════════════════════════════════════════════
# Planner 主入口: get_account_context
# ═══════════════════════════════════════════════════════════════

def get_account_context(account_id: int, days: int = 30) -> dict:
    """Planner 做决策前调这个. 返回"该账号目前 AI 知道的所有 useful 信息".

    Returns:
        {
          "strategy_memory": {...},         # Layer 2 完整记录
          "recent_decisions": [...],        # Layer 1 近 N 天
          "recent_diaries": [...],          # Layer 3 近 4 周
          "stats": {total, correct, ...},
        }
    """
    memory = get_strategy_memory(account_id) or {}
    decisions = query_account_decisions(account_id, days=days, limit=50)
    diaries = load_recent_diaries(account_id, weeks=4)

    # 简快统计
    stats = {
        "total_decisions_known": len(decisions),
        "correct": sum(1 for d in decisions if d.get("verdict") == "correct"),
        "over_optimistic": sum(1 for d in decisions
                                   if d.get("verdict") == "over_optimistic"),
        "pending": sum(1 for d in decisions if d.get("verdict") == "pending"),
        "trust_score": memory.get("ai_trust_score"),
    }

    return {
        "strategy_memory": memory,
        "recent_decisions": decisions,
        "recent_diaries": diaries,
        "stats": stats,
    }


# ═══════════════════════════════════════════════════════════════
# Config helper
# ═══════════════════════════════════════════════════════════════

def _cfg_int(key: str, default: int) -> int:
    from core.app_config import get as _g
    v = _g(key, default)
    try:
        return int(v)
    except (TypeError, ValueError):
        return default


def _cfg_float(key: str, default: float) -> float:
    from core.app_config import get as _g
    v = _g(key, default)
    try:
        return float(v)
    except (TypeError, ValueError):
        return default


# ═══════════════════════════════════════════════════════════════
# CLI
# ═══════════════════════════════════════════════════════════════

if __name__ == "__main__":
    import argparse, sys
    sys.stdout.reconfigure(encoding="utf-8")

    ap = argparse.ArgumentParser()
    ap.add_argument("--rebuild", type=int, help="重建某账号记忆")
    ap.add_argument("--rebuild-all", action="store_true", help="重建所有账号记忆")
    ap.add_argument("--context", type=int, help="查某账号完整 context")
    ap.add_argument("--decisions", type=int, help="查某账号最近决策")
    ap.add_argument("--days", type=int, default=30)
    args = ap.parse_args()

    if args.rebuild:
        r = rebuild_strategy_memory(args.rebuild)
        print(json.dumps(r, ensure_ascii=False, indent=2, default=str))
    elif args.rebuild_all:
        r = rebuild_all_strategy_memories()
        print(f"重建 {len(r)} 账号记忆:")
        for acc, v in r.items():
            if isinstance(v, dict) and "error" not in v:
                print(f"  account_id={acc}: decisions={v.get('total_decisions')} "
                      f"trust={v.get('ai_trust_score')}")
            else:
                print(f"  account_id={acc}: ERR {v.get('error', '')}")
    elif args.context:
        ctx = get_account_context(args.context, days=args.days)
        print(json.dumps(ctx, ensure_ascii=False, indent=2, default=str))
    elif args.decisions:
        rows = query_account_decisions(args.decisions, days=args.days)
        print(f"account_id={args.decisions} 近 {args.days} 天 {len(rows)} 决策:")
        for r in rows[:10]:
            print(f"  [{r['id']}] {r['decision_date']} {r['drama_name'][:20]} "
                  f"{r['recipe']} verdict={r['verdict']}")
    else:
        ap.print_help()
