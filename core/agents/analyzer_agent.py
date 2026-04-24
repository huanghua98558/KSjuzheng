# -*- coding: utf-8 -*-
"""AnalyzerAgent — 每日 17:00 跑 (MCN 批后).

职责:
  1. 聚合昨日 publish_results × fluorescent_members → publish_daily_metrics
  2. 根据 metrics 更新 strategy_rewards (Thompson Sampling 用)
  3. 跑 account_tier 评估 + 迁移
  4. 写 agent_runs 审计

驱动 Bandit 和 Tier 状态机.
"""
from __future__ import annotations

import json
import logging
import sqlite3
from datetime import datetime, timedelta
from typing import Any

from core.account_tier import run_tier_evaluation, list_accounts_by_tier
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


def aggregate_daily_metrics(target_date: str | None = None) -> dict:
    """聚合指定日期的每账号 publish_daily_metrics.

    默认目标日期 = 昨天 (今天 17:00 分析昨天全天).

    合并数据源:
      - publish_results: 昨日所有发布尝试 (success/failed count)
      - fluorescent_members: 昨日 vs 前日 total_amount / org_task_num delta
      - account_published_works: 播放/点赞/评论 (未来补)
    """
    if target_date is None:
        target_date = (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d")

    log.info("[analyzer] aggregating metrics for %s", target_date)
    prev_date = (datetime.strptime(target_date, "%Y-%m-%d")
                 - timedelta(days=1)).strftime("%Y-%m-%d")

    with _connect() as c:
        accounts = c.execute(
            """SELECT id, tier, account_name, numeric_uid FROM device_accounts
               WHERE login_status='logged_in'"""
        ).fetchall()

        aggregated = 0
        for acc in accounts:
            aid = acc["id"]
            nuid = acc["numeric_uid"]  # 数字 userId, 关联 mcn_member_snapshots.member_id

            # publish_results 昨日聚合
            stats = c.execute("""
                SELECT
                  COUNT(*) AS attempts,
                  SUM(CASE WHEN publish_status='success' THEN 1 ELSE 0 END) AS succ,
                  SUM(CASE WHEN publish_status='failed'  THEN 1 ELSE 0 END) AS fail
                FROM publish_results
                WHERE account_id=? AND date(created_at)=?
            """, (str(aid), target_date)).fetchone()

            attempts = stats["attempts"] or 0
            succ = stats["succ"] or 0
            fail = stats["fail"] or 0

            # fluorescent_members delta (从 mcn_member_snapshots 按 numeric_uid 关联)
            snap = None
            if nuid:
                snap = c.execute("""
                    SELECT delta_amount, org_task_num, total_amount
                    FROM mcn_member_snapshots
                    WHERE snapshot_date = ? AND member_id = ?
                    LIMIT 1
                """, (target_date, nuid)).fetchone()
            income_delta = (snap["delta_amount"] if snap else 0) or 0
            new_task_num = (snap["org_task_num"] if snap else 0) or 0

            # recipes used yesterday
            recipes_rows = c.execute("""
                SELECT DISTINCT process_recipe FROM task_queue
                WHERE account_id=? AND date(created_at)=? AND process_recipe IS NOT NULL
            """, (str(aid), target_date)).fetchall()
            recipes_used = [r[0] for r in recipes_rows if r[0]]

            if attempts == 0 and income_delta == 0:
                continue   # 完全不活跃, 跳过写入

            # Upsert
            c.execute("""
                INSERT OR REPLACE INTO publish_daily_metrics
                  (metric_date, account_id, account_tier,
                   publishes_attempted, publishes_success, publishes_failed,
                   income_delta, new_task_num, recipes_used_json)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (target_date, aid, acc["tier"], attempts, succ, fail,
                  float(income_delta), int(new_task_num),
                  json.dumps(recipes_used, ensure_ascii=False)))
            aggregated += 1
        c.commit()

    return {"target_date": target_date, "accounts_aggregated": aggregated}


def update_strategy_rewards(target_date: str | None = None) -> dict:
    """更新 strategy_rewards 表: (tier, recipe, drama) → reward.

    Reward 公式 (简化):
       reward = income_delta + (log(views+1) * 0.01)
    (未来: 加权审核过率, 权重从 config)
    """
    if target_date is None:
        target_date = (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d")

    updates = 0
    with _connect() as c:
        # 拉昨日成功的 publish_results → 每条算 reward
        rows = c.execute("""
            SELECT pr.account_id, pr.drama_name, pr.banner_task_id,
                   tq.process_recipe, tq.id AS task_id,
                   m.income_delta, m.total_views, da.tier
            FROM publish_results pr
            LEFT JOIN task_queue tq ON pr.task_queue_id = tq.id
            LEFT JOIN device_accounts da ON pr.account_id = CAST(da.id AS TEXT)
            LEFT JOIN publish_daily_metrics m
                 ON m.account_id = da.id AND m.metric_date = date(pr.created_at)
            WHERE date(pr.created_at) = ?
              AND pr.publish_status = 'success'
        """, (target_date,)).fetchall()

        for r in rows:
            tier = r["tier"] or "testing"
            recipe = r["process_recipe"] or "unknown"
            drama = r["drama_name"] or ""
            # 简化 reward: income_delta (整账号的, 按 success 数均分就近似)
            reward = float(r["income_delta"] or 0) / max(1, len(rows))
            # 加微小播放量贡献 (未来补 views)
            import math
            reward += math.log((r["total_views"] or 0) + 1) * 0.01

            # Upsert strategy_rewards
            existing = c.execute("""
                SELECT id, trials, rewards FROM strategy_rewards
                WHERE account_tier=? AND recipe=? AND drama_name=?
            """, (tier, recipe, drama)).fetchone()
            if existing:
                c.execute("""
                    UPDATE strategy_rewards SET
                        trials = trials + 1,
                        rewards = rewards + ?,
                        last_reward = ?,
                        last_updated = datetime('now','localtime')
                    WHERE id = ?
                """, (reward, reward, existing["id"]))
            else:
                c.execute("""
                    INSERT INTO strategy_rewards
                      (account_tier, recipe, drama_name, trials, rewards, last_reward, last_updated)
                    VALUES (?, ?, ?, 1, ?, ?, datetime('now','localtime'))
                """, (tier, recipe, drama, reward, reward))
            updates += 1
        c.commit()

    return {"target_date": target_date, "reward_rows_updated": updates}


def rebuild_knowledge_from_performance(
    lookback_days: int | None = None,
) -> dict[str, Any]:
    """★ S-8 (2026-04-20): 从 recipe_performance 反推更新 recipe_knowledge 星级.

    逻辑:
      - 统计近 N 天每 recipe × scenario_tag 的 success_rate + avg_income
      - 实战 success_rate 显著偏离 seed 值 → 调整 knowledge 的 strength_overall
      - 保守: 每次最多调 ±0.2 (10% 增量), 避免剧烈波动
      - 样本不足 (< 5) 不调

    这是"AI 不断推翻自己"的闭环 — 实战数据替代拍脑袋 seed.
    """
    if lookback_days is None:
        lookback_days = int(cfg_get("ai.recipe_performance.rebuild_days", 7))

    cutoff = (datetime.now() - timedelta(days=lookback_days)).strftime("%Y-%m-%d %H:%M:%S")
    updated = []
    with _connect() as c:
        # 按 recipe 聚合 (不细分 scenario 避免样本稀疏)
        rows = c.execute(
            """SELECT recipe_name,
                      COUNT(*) AS total,
                      SUM(CASE WHEN verdict='success' THEN 1 ELSE 0 END) AS succ,
                      SUM(CASE WHEN verdict='failed'  THEN 1 ELSE 0 END) AS fail,
                      AVG(COALESCE(income_delta, 0)) AS avg_income
               FROM recipe_performance
               WHERE recorded_at >= ?
               GROUP BY recipe_name
               HAVING total >= 5""",
            (cutoff,),
        ).fetchall()

        for r in rows:
            recipe = r[0]
            total, succ, fail, avg_inc = r[1], r[2] or 0, r[3] or 0, r[4] or 0
            success_rate = succ / max(1, total)

            # 查 knowledge 当前值
            k = c.execute(
                """SELECT strength_overall, beat_l3_phash FROM recipe_knowledge
                   WHERE recipe_name=?""",
                (recipe,),
            ).fetchone()
            if not k:
                continue
            cur_strength = k[0]

            # 实战 success_rate 90% 为基线:
            #   > 95% → +0.1 (奖励)
            #   < 70% → -0.2 (惩罚)
            delta = 0.0
            if success_rate >= 0.95:
                delta = 0.1
            elif success_rate >= 0.85:
                delta = 0.0  # 维持
            elif success_rate >= 0.70:
                delta = -0.05
            else:
                delta = -0.2

            # 加权 avg_income (正收益微调)
            if avg_inc >= 1.0:
                delta += 0.05
            elif avg_inc < 0.05:
                delta -= 0.05

            new_strength = max(1.0, min(5.0, cur_strength + delta))
            if abs(new_strength - cur_strength) >= 0.05:
                c.execute(
                    """UPDATE recipe_knowledge SET
                         strength_overall=?,
                         notes=COALESCE(notes,'') || ' | analyzer(' ||
                               datetime('now','localtime') || '): rate=' ||
                               ROUND(?, 2) || ' delta=' || ROUND(?, 2),
                         updated_at=datetime('now','localtime')
                       WHERE recipe_name=?""",
                    (new_strength, success_rate, delta, recipe),
                )
                updated.append({
                    "recipe": recipe, "samples": total,
                    "success_rate": round(success_rate, 2),
                    "old_strength": round(cur_strength, 2),
                    "new_strength": round(new_strength, 2),
                    "delta": round(delta, 2),
                })
        c.commit()

    return {"lookback_days": lookback_days, "updated": updated,
            "total_recipes_adjusted": len(updated)}


def run(dry_run: bool = False) -> dict[str, Any]:
    """Analyzer 主入口 (ControllerAgent 每日 17:00 调用)."""
    target_date = (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d")
    log.info("[analyzer] start — target_date=%s dry_run=%s", target_date, dry_run)

    stats = {"target_date": target_date}

    # 1. 聚合每日 metrics
    try:
        agg = aggregate_daily_metrics(target_date)
        stats["aggregate"] = agg
    except Exception as e:
        log.exception("[analyzer] aggregate failed")
        stats["aggregate_error"] = str(e)

    # 2. 更新 rewards (给 Bandit 用)
    try:
        ru = update_strategy_rewards(target_date)
        stats["rewards"] = ru
    except Exception as e:
        log.exception("[analyzer] rewards failed")
        stats["rewards_error"] = str(e)

    # 3. 跑 tier 评估 + 迁移
    try:
        tier_result = run_tier_evaluation(dry_run=dry_run)
        stats["tier"] = {
            "evaluated": tier_result["evaluated"],
            "transitioned": tier_result["transitioned"],
            "distribution": tier_result["distribution_after"],
        }
        # 若有迁移, 发通知
        if tier_result["transitioned"] > 0:
            lines = []
            for t in tier_result["transitions"][:10]:
                lines.append(
                    f"• {t['account_name']} {t['current_tier']} → {t['target_tier']}: {t['reason'][:80]}")
            notify(
                title=f"Analyzer: {tier_result['transitioned']} 账号迁移 tier",
                body="\n".join(lines),
                level="info", source="analyzer",
                extra={"transitions": tier_result["transitions"]},
            )
    except Exception as e:
        log.exception("[analyzer] tier eval failed")
        stats["tier_error"] = str(e)

    # ★ P3-1 (2026-04-20): 补 verdict — 把昨天完成的 task 对应的 decision 标上 verdict
    try:
        v_stats = backfill_decision_verdicts(target_date)
        stats["verdicts"] = v_stats
    except Exception as e:
        log.exception("[analyzer] verdict backfill failed")
        stats["verdicts_error"] = str(e)

    # ★ P3-2 (2026-04-20): 重建每账号 strategy_memory (Layer 2)
    try:
        from core.account_memory import rebuild_all_strategy_memories
        mem_results = rebuild_all_strategy_memories()
        stats["strategy_memory"] = {
            "rebuilt_accounts": len(mem_results),
            "trust_scored": sum(1 for v in mem_results.values()
                                   if isinstance(v, dict) and v.get("ai_trust_score") is not None),
        }
    except Exception as e:
        log.exception("[analyzer] strategy_memory rebuild failed")
        stats["strategy_memory_error"] = str(e)

    # ★ S-8 (2026-04-20): 从 recipe_performance 反推 recipe_knowledge
    try:
        rk_stats = rebuild_knowledge_from_performance()
        stats["recipe_knowledge_rebuild"] = rk_stats
        if rk_stats.get("total_recipes_adjusted"):
            log.info("[analyzer] recipe_knowledge 根据实战调整 %d 个 recipe",
                     rk_stats["total_recipes_adjusted"])
    except Exception as e:
        log.exception("[analyzer] recipe_knowledge rebuild failed")
        stats["recipe_knowledge_error"] = str(e)

    # ★ P2-8 (Phase 2 Round 2.3): 聚合 C 实验任务 → strategy_experiments
    try:
        exp_stats = aggregate_experiment_metrics(target_date)
        stats["experiments"] = exp_stats
        if exp_stats.get("experiments_finished"):
            lines = []
            for d in exp_stats.get("details", []):
                if d.get("finished"):
                    lines.append(
                        f"• {d['code']} winner={d.get('winner')} reason={d.get('finish_reason')}")
            if lines:
                notify(
                    title=f"Analyzer: {exp_stats['experiments_finished']} 实验完成",
                    body="\n".join(lines),
                    level="info", source="analyzer",
                    extra={"experiments": exp_stats.get("details", [])},
                )
    except Exception as e:
        log.exception("[analyzer] experiment aggregate failed")
        stats["experiment_error"] = str(e)

    log.info("[analyzer] done: %s", stats)
    return stats


def aggregate_experiment_metrics(target_date: str | None = None) -> dict:
    """★ P2-8: 聚合 experiment_assignments → strategy_experiments.result_summary.

    流程:
      1. 找 status='running' 的 strategy_experiments
      2. 对每个实验, JOIN experiment_assignments × task_queue × publish_daily_metrics
      3. 按 group_name 分组: 每组的 {n_assigned, n_success, n_failed, avg_income, success_rate}
      4. 写 result_summary (JSON), 更新 sample_current
      5. 判决条件 (stop_condition):
         - sample_current >= sample_target → stop + mark finished
         - 或者 day_passed >= 7 → stop regardless

    Returns:
        {experiments_updated, experiments_finished, details: [...]}
    """
    if target_date is None:
        target_date = datetime.now().strftime("%Y-%m-%d")

    result = {"experiments_updated": 0, "experiments_finished": 0,
              "details": []}

    with _connect() as c:
        # 1. 找所有 running 实验
        exps = c.execute("""
            SELECT * FROM strategy_experiments
            WHERE status = 'running'
            ORDER BY id DESC
        """).fetchall()

        for exp in exps:
            exp_code = exp["experiment_code"]
            started_at = exp["started_at"] or exp["created_at"]

            # 2. JOIN 数据: 每个 assignment 的 task 结果 + 当日 income
            rows = c.execute("""
                SELECT ea.group_name, ea.account_id, ea.drama_name,
                       ea.task_id, ea.status AS assignment_status,
                       tq.status AS task_status, tq.finished_at,
                       pr.publish_status, pr.photo_id,
                       (SELECT income_delta FROM publish_daily_metrics
                        WHERE account_id = CAST(ea.account_id AS INTEGER)
                          AND metric_date = date(tq.finished_at)
                        LIMIT 1) AS income_delta
                FROM experiment_assignments ea
                LEFT JOIN task_queue tq ON ea.task_id = tq.id
                LEFT JOIN publish_results pr ON tq.id = pr.task_queue_id
                WHERE ea.experiment_code = ?
            """, (exp_code,)).fetchall()

            if not rows:
                continue

            # 3. 按 group 分组聚合
            groups_stats = {}
            for r in rows:
                g = r["group_name"] or "?"
                gs = groups_stats.setdefault(g, {
                    "n_assigned": 0, "n_queued_or_running": 0,
                    "n_success": 0, "n_failed": 0,
                    "total_income": 0.0, "income_samples": 0,
                })
                gs["n_assigned"] += 1
                pubst = r["publish_status"]
                taskst = r["task_status"]
                if pubst == "success":
                    gs["n_success"] += 1
                elif pubst == "failed" or taskst in ("failed", "dead_letter", "canceled"):
                    gs["n_failed"] += 1
                else:
                    gs["n_queued_or_running"] += 1
                if r["income_delta"] is not None:
                    gs["total_income"] += float(r["income_delta"])
                    gs["income_samples"] += 1

            # 计算派生指标 (avg_income / success_rate)
            for g, gs in groups_stats.items():
                gs["success_rate"] = round(
                    gs["n_success"] / max(1, gs["n_success"] + gs["n_failed"]), 3)
                gs["avg_income_per_task"] = round(
                    gs["total_income"] / max(1, gs["income_samples"]), 2)

            total_sample_current = sum(gs["n_success"] + gs["n_failed"]
                                         for gs in groups_stats.values())

            # 4. 判决 winner (avg_income_per_task 最高者)
            winner = None
            best_income = -1e9
            for g, gs in groups_stats.items():
                if gs["income_samples"] >= 1 and gs["avg_income_per_task"] > best_income:
                    best_income = gs["avg_income_per_task"]
                    winner = g

            # 5. 生成 result_summary
            summary = {
                "analyzed_at": datetime.now().isoformat(timespec="seconds"),
                "target_date": target_date,
                "groups": groups_stats,
                "total_sample_current": total_sample_current,
                "winner_group": winner,
                "best_avg_income": best_income if winner else None,
            }

            # 6. 判断是否 finish (sample target / day_passed)
            should_finish = False
            finish_reason = None
            sample_target = exp["sample_target"] or 9
            if total_sample_current >= sample_target:
                should_finish = True
                finish_reason = f"sample_target_reached ({total_sample_current}/{sample_target})"
            else:
                try:
                    st_dt = datetime.fromisoformat(started_at.split(".")[0])
                    days_passed = (datetime.now() - st_dt).days
                    if days_passed >= 7:
                        should_finish = True
                        finish_reason = f"timeout_7_days ({days_passed}d)"
                except Exception:
                    pass

            # 7. 写回
            if should_finish:
                summary["finish_reason"] = finish_reason
                c.execute("""
                    UPDATE strategy_experiments SET
                      sample_current = ?,
                      result_summary = ?,
                      status = 'finished',
                      ended_at = datetime('now','localtime')
                    WHERE id = ?
                """, (total_sample_current,
                      json.dumps(summary, ensure_ascii=False),
                      exp["id"]))
                result["experiments_finished"] += 1
                log.info("[analyzer] experiment %s FINISHED (winner=%s reason=%s)",
                         exp_code, winner, finish_reason)
            else:
                c.execute("""
                    UPDATE strategy_experiments SET
                      sample_current = ?,
                      result_summary = ?
                    WHERE id = ?
                """, (total_sample_current,
                      json.dumps(summary, ensure_ascii=False),
                      exp["id"]))
                result["experiments_updated"] += 1

            result["details"].append({
                "code": exp_code, "groups": groups_stats,
                "winner": winner, "finished": should_finish,
                "finish_reason": finish_reason,
            })
        c.commit()

    return result


def backfill_decision_verdicts(target_date: str) -> dict:
    """★ P3-1: 把 target_date 当天完成的 task 对应的 decision_history 行补 verdict.

    流程:
      1. 查 publish_results.created_at 在 target_date 当天的行
      2. 对每条 pr, 用 task_queue_id → 找 account_decision_history (task_id 匹配)
      3. 组装 actual_outcome: 从 publish_daily_metrics 拿 income_delta
      4. 调 record_actual_and_verdict()
    """
    import sqlite3
    from core.account_memory import record_actual_and_verdict

    with _connect() as c:
        # ★ 2026-04-22 §28_L bug fix: 列名 verified_status → verify_status
        # 这个 bug 让 236 decisions 一直停在 verdict=pending, 闭环断 (Layer 2 total_decisions=0).
        rows = c.execute(
            """SELECT pr.task_queue_id AS task_id,
                      pr.account_id,
                      pr.publish_status,
                      pr.photo_id,
                      pr.verify_status
               FROM publish_results pr
               WHERE date(pr.created_at) = ?
                 AND pr.task_queue_id IS NOT NULL AND pr.task_queue_id != ''""",
            (target_date,),
        ).fetchall()

    verdicts = {"correct": 0, "over_optimistic": 0,
                "under_confident": 0, "wrong": 0, "pending": 0,
                "total": len(rows)}

    for r in rows:
        task_id = r["task_id"]
        acc_id = r["account_id"]
        status = r["publish_status"]

        # 查 income_delta (如果有)
        income = 0.0
        try:
            with _connect() as c:
                m = c.execute(
                    """SELECT income_delta FROM publish_daily_metrics
                       WHERE account_id = ? AND metric_date = ?""",
                    (int(acc_id), target_date),
                ).fetchone()
                if m:
                    # 平均分配: 当天该账号 metric income / 发布数
                    income_per_task = float(m["income_delta"] or 0)
                    # 先粗放: 不拆分
                    income = income_per_task
        except (ValueError, TypeError, sqlite3.Error):
            income = 0.0

        actual = {
            "status": status if status == "success" else "failed",
            "income": income,
            "photo_id": r["photo_id"] or "",
            "verify_status": r["verify_status"] or "",
        }
        try:
            res = record_actual_and_verdict(task_id=task_id, actual=actual)
            if res:
                v = res["verdict"]
                verdicts[v] = verdicts.get(v, 0) + 1
        except Exception as e:
            log.debug("[verdict] task %s failed: %s", task_id, e)

    return verdicts


if __name__ == "__main__":
    import sys, json as _j
    sys.stdout.reconfigure(encoding="utf-8")
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()
    print(_j.dumps(run(dry_run=args.dry_run), ensure_ascii=False, indent=2, default=str))
