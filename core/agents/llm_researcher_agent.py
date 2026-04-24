# -*- coding: utf-8 -*-
"""LLMResearcherAgent — 每周一 7:00 跑一次.

输入:
  - 近 7 天 publish_daily_metrics (账号 × 日 × 收益/播放/recipe)
  - 当前 tier 分布
  - 当前 strategy_rewards top/bottom
输出:
  - research_notes 新行 (approved=0 待审批)
  - 给 Planner 的策略建议 (JSON)

Hermes LLM 网关: http://127.0.0.1:8642/v1
"""
from __future__ import annotations

import json
import logging
import sqlite3
from datetime import datetime, timedelta
from typing import Any

from core.account_tier import tier_distribution
from core.app_config import get as cfg_get
from core.llm_gateway import chat, is_online
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


def _collect_context(lookback_days: int = 7) -> dict:
    """收集喂给 LLM 的 context."""
    since = (datetime.now() - timedelta(days=lookback_days)).strftime("%Y-%m-%d")
    ctx = {}

    with _connect() as c:
        # 1. 每日总 income / publish / view
        daily = c.execute("""
            SELECT metric_date,
                   COUNT(DISTINCT account_id) AS active_accounts,
                   SUM(publishes_success) AS succ,
                   SUM(publishes_failed)  AS fail,
                   SUM(total_views)       AS views,
                   SUM(income_delta)      AS income
            FROM publish_daily_metrics
            WHERE metric_date >= ?
            GROUP BY metric_date ORDER BY metric_date DESC
        """, (since,)).fetchall()
        ctx["daily"] = [dict(r) for r in daily]

        # 2. tier × recipe 的 reward avg
        rewards = c.execute("""
            SELECT account_tier, recipe,
                   SUM(trials) AS trials,
                   ROUND(SUM(rewards), 3) AS total_reward,
                   ROUND(SUM(rewards)/NULLIF(SUM(trials),0), 3) AS avg_reward
            FROM strategy_rewards
            GROUP BY account_tier, recipe
            ORDER BY avg_reward DESC NULLS LAST
        """).fetchall()
        ctx["rewards_by_tier_recipe"] = [dict(r) for r in rewards]

        # 3. top 10 剧
        top_dramas = c.execute("""
            SELECT drama_name, banner_task_id, recent_income_sum, recent_income_count
            FROM drama_banner_tasks
            WHERE recent_income_sum > 0
            ORDER BY recent_income_sum DESC LIMIT 10
        """).fetchall()
        ctx["top_dramas"] = [dict(r) for r in top_dramas]

        # 4. 账号 tier 分布
        ctx["tier_distribution"] = tier_distribution()

    return ctx


def _build_prompt(ctx: dict) -> list[dict]:
    return [
        {"role": "system", "content":
            "你是快手短剧矩阵运营战略分析师. 基于过去 7 天的数据, 输出本周运营策略调整建议. "
            "输出严格 JSON, 字段: "
            "summary (一句话总结), findings (3-5 条数据发现), "
            "suggestions (list, 每条含 category/priority/action/rationale), "
            "next_week_focus (下周重点)."},
        {"role": "user", "content":
            f"本周数据 context:\n```json\n{json.dumps(ctx, ensure_ascii=False, indent=2, default=str)}\n```\n\n"
            f"请用中文输出严格 JSON (单个对象), 不要 markdown 包裹."},
    ]


def _parse_llm_json(text: str) -> dict:
    """抽 LLM 输出里的 JSON (可能被 markdown 包裹)."""
    import re
    # 剥离 ```json ... ``` 或 ``` ... ```
    m = re.search(r'```(?:json)?\s*(\{.+?\})\s*```', text, re.DOTALL)
    if m:
        text = m.group(1)
    # 直接尝试 parse
    try:
        return json.loads(text)
    except Exception:
        pass
    # 提第一个 {...} block
    m2 = re.search(r'\{[\s\S]+\}', text)
    if m2:
        try:
            return json.loads(m2.group(0))
        except Exception:
            pass
    return {"_raw": text[:2000]}


def run(dry_run: bool = False, mode: str = "strategy",
         hours: int = 24) -> dict[str, Any]:
    """主入口.

    ★ 2026-04-23 Bug 2 修复: 加 mode 参数让 controller_agent 可调 all/strategy/
    propose_rules/propose_upgrades/diary. 老调用 `run()` / `run(dry_run=True)` 保持兼容.

    Args:
        dry_run: 不写 DB
        mode: "strategy" (default, 老行为) / "all" / "propose_rules" /
              "propose_upgrades" / "diary"
        hours: propose_rules 的 lookback 小时数
    """
    # mode="all": 串跑 4 个子任务 + 汇总
    if mode == "all":
        out = {"ok": True, "mode": "all"}
        try:
            out["strategy"] = run(dry_run=dry_run, mode="strategy")
        except Exception as e:
            out["strategy"] = {"ok": False, "error": f"exc: {e}"}
        try:
            out["propose_rules"] = propose_new_rules_from_unmatched(
                dry_run=dry_run, hours=hours)
        except Exception as e:
            out["propose_rules"] = {"ok": False, "error": f"exc: {e}"}
        try:
            out["propose_upgrades"] = propose_upgrades_for_low_confidence(
                dry_run=dry_run)
        except Exception as e:
            out["propose_upgrades"] = {"ok": False, "error": f"exc: {e}"}
        try:
            out["diary"] = generate_account_diaries(dry_run=dry_run)
        except Exception as e:
            out["diary"] = {"ok": False, "error": f"exc: {e}"}
        return out

    if mode == "propose_rules":
        return propose_new_rules_from_unmatched(dry_run=dry_run, hours=hours)
    if mode == "propose_upgrades":
        return propose_upgrades_for_low_confidence(dry_run=dry_run)
    if mode == "diary":
        return generate_account_diaries(dry_run=dry_run)
    # mode="strategy" or unknown → 老行为

    if not cfg_get("ai.llm.enabled", True):
        return {"ok": False, "skip": "llm_disabled"}

    if not is_online():
        log.warning("[researcher] Hermes 离线, skip")
        return {"ok": False, "skip": "hermes_offline"}

    lookback = cfg_get("ai.analyzer.lookback_days", 7)
    ctx = _collect_context(lookback_days=lookback)

    # 数据量太少的话别跑 LLM 浪费 token
    if sum(d.get("succ") or 0 for d in ctx.get("daily", [])) < 5:
        log.info("[researcher] 样本太少, skip")
        return {"ok": False, "skip": "not_enough_data",
                "total_succ": sum(d.get("succ") or 0 for d in ctx.get("daily", []))}

    messages = _build_prompt(ctx)
    log.info("[researcher] calling Hermes...")
    resp = chat(messages=messages, temperature=0.3, max_tokens=2500)

    if not resp.get("ok"):
        return {"ok": False, "error": resp.get("error"),
                "resp_elapsed": resp.get("elapsed_sec")}

    text = resp.get("text", "")
    parsed = _parse_llm_json(text)
    summary = parsed.get("summary", "")[:500]

    # 写 research_notes
    if not dry_run:
        with _connect() as c:
            cur = c.execute("""
                INSERT INTO research_notes
                  (research_date, model, prompt_kind, summary, raw_response,
                   suggestions_json, approved)
                VALUES (?, ?, 'weekly_strategy', ?, ?, ?, 0)
            """, (datetime.now().strftime("%Y-%m-%d"),
                  resp.get("model", ""),
                  summary, text[:10000],
                  json.dumps(parsed, ensure_ascii=False)))
            note_id = cur.lastrowid
            c.commit()

        notify(
            title=f"📝 LLM 研究员新建议 (待审批)",
            body=f"summary: {summary[:200]}\n\n"
                 f"approve 后会影响 Planner 决策. \n"
                 f"SQL: UPDATE research_notes SET approved=1, approved_by='you', "
                 f"approved_at=datetime('now') WHERE id={note_id};",
            level="info", source="llm_researcher",
            extra={"note_id": note_id, "model": resp.get("model")},
        )
    else:
        note_id = None

    return {
        "ok": True,
        "dry_run": dry_run,
        "note_id": note_id,
        "model": resp.get("model"),
        "elapsed_sec": resp.get("elapsed_sec"),
        "usage": resp.get("usage"),
        "parsed": parsed,
    }


# ═════════════════════════════════════════════════════════════════
# D-5 深度联动: LLM → healing 系统
# ═════════════════════════════════════════════════════════════════

def _collect_unmatched_failures(hours: int = 24, min_cluster_size: int = 3) -> list[dict]:
    """找未被任何 playbook 规则匹配的 failed task, 按 error_message 关键词聚类.

    返回 list[{error_signature, count, sample_tasks[]}],
    用来喂给 LLM 让它总结新规则.
    """
    import re
    import hashlib

    with _connect() as c:
        # 读所有 active playbook 的 pattern
        playbook = c.execute(
            "SELECT symptom_pattern, task_type FROM healing_playbook WHERE is_active=1"
        ).fetchall()
        patterns = [(re.compile(p["symptom_pattern"], re.IGNORECASE), p["task_type"])
                    for p in playbook]

        # 读近 N 小时所有 failed
        failed = c.execute(
            f"""SELECT id, task_type, account_id, drama_name, error_message, batch_id
                FROM task_queue
                WHERE status IN ('failed', 'dead_letter')
                  AND datetime(finished_at) >= datetime('now', ?, 'localtime')""",
            (f"-{hours} hours",),
        ).fetchall()

    # 过滤: 只要未被任何 pattern 匹配的
    unmatched = []
    for row in failed:
        err = (row["error_message"] or "")
        task_type = row["task_type"] or "*"
        matched = False
        for pat, pat_tt in patterns:
            if pat_tt not in ("*", task_type):
                continue
            if pat.search(err):
                matched = True
                break
        if not matched:
            unmatched.append(dict(row))

    # 按 error 开头 100 字符做 signature 聚类
    clusters: dict[str, list[dict]] = {}
    for row in unmatched:
        err = row.get("error_message") or ""
        # 取开头 ASCII 字母 (忽略变量名数字) 做粗粒度 signature
        sig = re.sub(r"[0-9a-f]{8,}", "X", err[:200])
        sig = sig[:80]
        clusters.setdefault(sig, []).append(row)

    result = []
    for sig, tasks in clusters.items():
        if len(tasks) >= min_cluster_size:
            result.append({
                "error_signature": sig,
                "count": len(tasks),
                "sample_tasks": tasks[:5],
            })
    result.sort(key=lambda x: -x["count"])
    return result


def _build_new_rule_prompt(clusters: list[dict]) -> list[dict]:
    """让 LLM 基于未匹配失败提新规则."""
    return [
        {"role": "system", "content":
            "你是快手矩阵运营自愈系统的规则工程师. 基于未被任何现有规则匹配的失败日志, "
            "给每个聚类推荐一条 healing_playbook 新规则.\n\n"
            "输出严格 JSON, 格式:\n"
            '{"proposals": [{"code": "xxx_yyy", '
            '"symptom_pattern": "正则表达式", '
            '"task_type": "*|PUBLISH|...", '
            '"diagnosis": "一句话诊断", '
            '"remedy_action": "trigger_recollect_and_fallback_browser|mark_account_needs_relogin|'
            'cancel_orphan_publish_and_reenqueue_upstream|pause_account_enter_cooldown|trigger_bulk_collect", '
            '"remedy_params": {}, '
            '"confidence": 0.0-1.0 (你对这条规则的自评), '
            '"rationale": "为什么这样写"}]}\n\n'
            "规则书写要点:\n"
            "1. symptom_pattern 用 | 分隔多个关键词, 覆盖同类错误变体\n"
            "2. remedy_action 必须从上面列表里选\n"
            "3. confidence ≤ 0.7 的规则会进 pending 不自动应用"},
        {"role": "user", "content":
            f"未匹配失败聚类 ({len(clusters)} 类):\n"
            + json.dumps(clusters, ensure_ascii=False, indent=2, default=str)[:4000]
            + "\n\n请输出 JSON (不要 markdown)."},
    ]


def propose_new_rules_from_unmatched(dry_run: bool = False,
                                       hours: int = 24) -> dict:
    """★ D-5 核心 1: LLM 看未匹配失败 → 写 rule_proposals.

    流程:
      1. 查近 N 小时 failed task
      2. 排除所有被 playbook 匹配的
      3. 按 error 粗粒度聚类 (≥ N 次才分析, 避免碎片)
      4. 喂给 Hermes → 得到新规则 JSON
      5. 每条规则写入 rule_proposals (status=pending, 等人审批)
    """
    if not cfg_get("ai.llm.propose_rules", True):
        return {"ok": False, "skip": "propose_rules_disabled"}
    if not is_online():
        return {"ok": False, "skip": "hermes_offline"}

    min_cluster = cfg_get("ai.healing.unmatched_threshold", 3)
    clusters = _collect_unmatched_failures(hours=hours,
                                              min_cluster_size=min_cluster)

    if not clusters:
        return {"ok": True, "skip": "no_unmatched_clusters",
                "hours_looked_back": hours,
                "min_cluster_size": min_cluster}

    log.info("[researcher] found %d unmatched clusters, asking Hermes",
             len(clusters))
    messages = _build_new_rule_prompt(clusters)
    resp = chat(messages=messages, temperature=0.2,
                max_tokens=int(cfg_get("ai.llm.analysis_max_tokens", 3000) or 3000))
    if not resp.get("ok"):
        return {"ok": False, "error": resp.get("error")}

    parsed = _parse_llm_json(resp.get("text", ""))
    proposals = parsed.get("proposals", []) if isinstance(parsed, dict) else []

    min_conf = cfg_get("ai.healing.min_llm_confidence_to_propose", 0.7)
    inserted = 0
    skipped_low_conf = 0
    with _connect() as c:
        for p in proposals:
            conf = float(p.get("confidence", 0))
            if conf < min_conf:
                skipped_low_conf += 1
                continue
            if dry_run:
                inserted += 1
                continue
            # 写 rule_proposals
            # rule_body_json = 完整 playbook 规则 (批准后直接抄进 healing_playbook)
            rule_body = {
                "code": p.get("code", f"llm_{inserted}"),
                "symptom_pattern": p.get("symptom_pattern", ".*"),
                "task_type": p.get("task_type", "*"),
                "min_occurrences": 2,
                "diagnosis": p.get("diagnosis", ""),
                "remedy_action": p.get("remedy_action",
                                        "pause_account_enter_cooldown"),
                "remedy_params": p.get("remedy_params", {}),
                "confidence": conf,
            }
            c.execute(
                """INSERT INTO rule_proposals
                     (category, config_key, current_value, proposed_value,
                      proposer, reason, evidence_json, confidence, status,
                      llm_confidence)
                   VALUES ('healing_playbook', ?, ?, ?,
                           'llm_researcher', ?, ?, ?, 'pending', ?)""",
                (p.get("code", ""),
                 "",  # current = 无 (新增规则)
                 json.dumps(rule_body, ensure_ascii=False),
                 p.get("rationale", "")[:500],
                 json.dumps(clusters[:3], ensure_ascii=False, default=str)[:4000],
                 conf, conf),
            )
            inserted += 1
        c.commit()

    if inserted > 0:
        notify(
            title=f"🤖 LLM 建议 {inserted} 条新自愈规则",
            body=f"从 {len(clusters)} 个未匹配失败模式中提炼. "
                 f"审批: SELECT * FROM rule_proposals WHERE status='pending';",
            level="info", source="llm_researcher",
            extra={"proposals_count": inserted,
                   "skipped_low_confidence": skipped_low_conf},
        )

    return {
        "ok": True,
        "clusters_analyzed": len(clusters),
        "proposals_total": len(proposals),
        "proposals_inserted": inserted,
        "skipped_low_confidence": skipped_low_conf,
        "llm_elapsed_sec": resp.get("elapsed_sec"),
    }


def _collect_low_confidence_rules(min_trials: int = 5,
                                     max_success_rate: float = 0.5) -> list[dict]:
    """找跑了 ≥ N 次但成功率低的 playbook 规则 (候选升级目标)."""
    with _connect() as c:
        rows = c.execute(
            """SELECT id, code, symptom_pattern, diagnosis, remedy_action,
                      confidence, success_count, fail_count,
                      (success_count + fail_count) AS total_trials,
                      CASE WHEN (success_count + fail_count) > 0
                           THEN 1.0 * success_count / (success_count + fail_count)
                           ELSE NULL
                      END AS success_rate,
                      last_triggered_at, llm_analyzed_at
               FROM healing_playbook
               WHERE is_active = 1
                 AND (success_count + fail_count) >= ?
               ORDER BY success_rate ASC""",
            (min_trials,),
        ).fetchall()
    out = []
    for r in rows:
        sr = r["success_rate"]
        if sr is None or sr > max_success_rate:
            continue
        out.append(dict(r))
    return out


def _build_upgrade_prompt(low_rules: list[dict]) -> list[dict]:
    """让 LLM 分析低成功率规则, 提升级建议."""
    return [
        {"role": "system", "content":
            "你是自愈规则审计师. 以下 playbook 规则跑了多次但成功率低, 需要改进. "
            "为每条规则给出升级建议.\n\n"
            "输出严格 JSON:\n"
            '{"upgrades": [{"target_rule_id": 1, '
            '"target_rule_code": "xxx", '
            '"upgrade_type": "refine_pattern|change_action|adjust_params|deprecate", '
            '"new_value": {...}, '
            '"rationale": "为什么升级", '
            '"confidence": 0.0-1.0}]}'},
        {"role": "user", "content":
            f"低成功率规则 ({len(low_rules)} 条):\n"
            + json.dumps(low_rules, ensure_ascii=False, indent=2, default=str)[:4000]
            + "\n\n请输出 JSON."},
    ]


def propose_upgrades_for_low_confidence(dry_run: bool = False) -> dict:
    """★ D-5 核心 2: LLM 审计低成功率规则 → upgrade_proposals."""
    if not cfg_get("ai.llm.propose_upgrades", True):
        return {"ok": False, "skip": "propose_upgrades_disabled"}
    if not is_online():
        return {"ok": False, "skip": "hermes_offline"}

    low_rules = _collect_low_confidence_rules(min_trials=5, max_success_rate=0.5)
    if not low_rules:
        return {"ok": True, "skip": "no_low_confidence_rules"}

    log.info("[researcher] %d low-success rules to audit", len(low_rules))
    messages = _build_upgrade_prompt(low_rules)
    resp = chat(messages=messages, temperature=0.2,
                max_tokens=int(cfg_get("ai.llm.analysis_max_tokens", 3000) or 3000))
    if not resp.get("ok"):
        return {"ok": False, "error": resp.get("error")}

    parsed = _parse_llm_json(resp.get("text", ""))
    upgrades = parsed.get("upgrades", []) if isinstance(parsed, dict) else []

    inserted = 0
    with _connect() as c:
        for u in upgrades:
            if dry_run:
                inserted += 1
                continue
            c.execute(
                """INSERT INTO upgrade_proposals
                     (upgrade_type, target_file, current_state, proposed_state,
                      reason, evidence_json, confidence, status, proposer)
                   VALUES ('healing_rule_upgrade', ?, ?, ?, ?, ?, ?,
                           'pending', 'llm_researcher')""",
                (f"playbook:{u.get('target_rule_code', '')}",
                 json.dumps({"rule_id": u.get("target_rule_id")},
                            ensure_ascii=False),
                 json.dumps(u.get("new_value", {}), ensure_ascii=False),
                 u.get("rationale", "")[:500],
                 json.dumps(low_rules[:3], ensure_ascii=False, default=str)[:4000],
                 float(u.get("confidence", 0.5))),
            )
            # 标记已分析过 (llm_analyzed_at)
            rule_id = u.get("target_rule_id")
            if rule_id:
                c.execute(
                    "UPDATE healing_playbook SET llm_analyzed_at = "
                    "datetime('now','localtime') WHERE id = ?",
                    (int(rule_id),),
                )
            inserted += 1
        c.commit()

    if inserted > 0:
        notify(
            title=f"🔧 LLM 建议 {inserted} 条规则升级",
            body=f"审计发现 {len(low_rules)} 条低成功率规则. "
                 f"审批: SELECT * FROM upgrade_proposals WHERE status='pending';",
            level="info", source="llm_researcher",
        )

    return {
        "ok": True,
        "low_rules_count": len(low_rules),
        "upgrades_proposed": inserted,
        "llm_elapsed_sec": resp.get("elapsed_sec"),
    }


# ═════════════════════════════════════════════════════════════════
# ★ P4 (2026-04-20): 账号周记 — 每账号自然语言运营总结
# ═════════════════════════════════════════════════════════════════

def _build_diary_prompt(account_id: int, account_name: str,
                          ctx: dict, week_range: str) -> list[dict]:
    """组 LLM prompt: 给账号写周记."""
    memory = ctx.get("strategy_memory") or {}
    decisions = ctx.get("recent_decisions") or []
    stats = ctx.get("stats") or {}

    # 精简上下文 (控制 prompt 长度)
    decisions_preview = []
    for d in decisions[:20]:
        decisions_preview.append({
            "date": d.get("decision_date"),
            "drama": (d.get("drama_name") or "")[:30],
            "recipe": d.get("recipe"),
            "verdict": d.get("verdict"),
            "hypothesis": (d.get("hypothesis") or "")[:80],
            "expected": d.get("expected_outcome"),
            "actual": d.get("actual_outcome"),
        })

    memory_preview = {
        "trust_score": memory.get("ai_trust_score"),
        "preferred_recipes": memory.get("preferred_recipes"),
        "preferred_image_modes": memory.get("preferred_image_modes"),
        "avoid_drama_ids": (memory.get("avoid_drama_ids") or [])[:5],
        "total_income_7d": memory.get("total_income_7d"),
        "total_income_30d": memory.get("total_income_30d"),
        "total_published": memory.get("total_published"),
    }

    return [
        {"role": "system", "content":
            "你是账号运营顾问. 基于账号近期决策数据, 写一份**中文**周记, 要求:\n\n"
            "1. summary — 一句话总结 (本周是赚了还是赔了, 稳定还是震荡)\n"
            "2. performance_review — 3-5 句复盘 (哪些决策对了, 哪些错了, 为什么)\n"
            "3. lessons_learned — 1-3 条经验/教训 (AI 自我反省, 如 '下次不要再给该账号排 X 类剧')\n"
            "4. next_week_strategy — 1-3 条具体建议 (recipe/image_mode/drama_type)\n\n"
            "输出严格 JSON (单个对象), 字段: "
            '{"summary": "...", "performance_review": "...", '
            '"lessons_learned": "...", "next_week_strategy": "..."}'},
        {"role": "user", "content":
            f"账号: {account_name} (ID {account_id})\n"
            f"周期: {week_range}\n\n"
            f"## 本周决策概要 ({stats.get('total_decisions_known', 0)} 次)\n"
            f"- correct: {stats.get('correct', 0)}\n"
            f"- over_optimistic: {stats.get('over_optimistic', 0)}\n"
            f"- pending: {stats.get('pending', 0)}\n"
            f"- trust_score: {stats.get('trust_score')}\n\n"
            f"## 账号画像 (memory)\n"
            f"```json\n{json.dumps(memory_preview, ensure_ascii=False, indent=2, default=str)}\n```\n\n"
            f"## 最近 20 条决策 (事件流)\n"
            f"```json\n{json.dumps(decisions_preview, ensure_ascii=False, indent=2, default=str)[:3500]}\n```\n\n"
            "请输出 JSON."},
    ]


def generate_account_diaries(
    dry_run: bool = False,
    weeks_back: int = 0,
) -> dict:
    """★ P4: 为所有活跃账号生成周记 (Layer 3).

    流程:
      1. 查所有活跃账号 (login_status='logged_in')
      2. 过滤: 最近 7 天活动数 >= min_activity
      3. 对每个账号:
         - get_account_context(days=7)
         - 组 prompt → 调 Hermes
         - parse JSON → save_diary_entry
      4. 批量通知

    Args:
        dry_run: 不写库, 只 print
        weeks_back: 往前第几周 (0=本周, 1=上周)

    Returns:
        {total, skipped, generated, errors}
    """
    if not cfg_get("ai.memory.diary.enabled", True):
        return {"skipped": "diary_disabled"}
    if not is_online():
        return {"skipped": "hermes_offline"}

    from core.account_memory import get_account_context, save_diary_entry
    from datetime import timedelta

    try:
        min_activity = int(cfg_get("ai.memory.diary.min_activity", 3))
    except (TypeError, ValueError):
        min_activity = 3

    today = datetime.now()
    diary_date = (today - timedelta(days=today.weekday())).strftime("%Y-%m-%d")
    if weeks_back > 0:
        from datetime import timedelta as _td
        diary_date = (datetime.strptime(diary_date, "%Y-%m-%d")
                      - _td(weeks=weeks_back)).strftime("%Y-%m-%d")
    week_start = datetime.strptime(diary_date, "%Y-%m-%d") - timedelta(days=6)
    week_range = f"{week_start.strftime('%Y-%m-%d')} ~ {diary_date}"

    # 查活跃账号
    with _connect() as c:
        accounts = c.execute(
            """SELECT id, account_name FROM device_accounts
               WHERE login_status='logged_in'"""
        ).fetchall()

    stats = {"total": len(accounts), "skipped_low_activity": 0,
             "generated": 0, "errors": 0, "diaries": []}

    for acc in accounts:
        acc_id = acc["id"]
        acc_name = acc["account_name"] or f"acc_{acc_id}"
        ctx = get_account_context(acc_id, days=7)

        if len(ctx.get("recent_decisions", [])) < min_activity:
            stats["skipped_low_activity"] += 1
            continue

        messages = _build_diary_prompt(acc_id, acc_name, ctx, week_range)
        resp = chat(messages=messages, temperature=0.3, max_tokens=1500)

        if not resp.get("ok"):
            stats["errors"] += 1
            log.warning("[diary] account %s chat failed: %s", acc_id, resp.get("error"))
            continue

        parsed = _parse_llm_json(resp.get("text", ""))
        # ★ 2026-04-22 §28_P bug fix: LLM 可能返 list (e.g. lessons=["a","b","c"])
        # save_diary_entry 期望 str, 需转换.
        def _to_str(x):
            if x is None: return ""
            if isinstance(x, str): return x
            if isinstance(x, list):
                return "\n".join(f"- {_to_str(item)}" for item in x)
            if isinstance(x, dict):
                import json as _j
                return _j.dumps(x, ensure_ascii=False, indent=2)
            return str(x)
        summary = _to_str(parsed.get("summary")) if isinstance(parsed, dict) else ""
        review = _to_str(parsed.get("performance_review")) if isinstance(parsed, dict) else ""
        lessons = _to_str(parsed.get("lessons_learned")) if isinstance(parsed, dict) else ""
        next_strat = _to_str(parsed.get("next_week_strategy")) if isinstance(parsed, dict) else ""

        if dry_run:
            log.info("[diary] [DRY RUN] account=%s: %s", acc_name, summary[:80])
        else:
            save_diary_entry(
                account_id=acc_id, diary_date=diary_date, week_range=week_range,
                summary=summary, performance_review=review,
                lessons_learned=lessons, next_week_strategy=next_strat,
                input_metrics=ctx.get("stats"),
                model=resp.get("model", ""),
                tokens_used=(resp.get("usage", {}) or {}).get("total_tokens", 0),
                elapsed_sec=resp.get("elapsed_sec", 0),
            )
        stats["generated"] += 1
        stats["diaries"].append({
            "account_id": acc_id, "account_name": acc_name,
            "summary": summary[:120],
        })

    if stats["generated"] > 0 and not dry_run:
        notify(
            title=f"📔 LLM 为 {stats['generated']} 账号写了周记",
            body=f"周期 {week_range}. 跳过低活跃 {stats['skipped_low_activity']} 账号.",
            level="info", source="llm_researcher_diary",
        )

    return stats


if __name__ == "__main__":
    import sys, json as _j
    sys.stdout.reconfigure(encoding="utf-8")
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--mode", default="strategy",
                    choices=["strategy", "propose_rules", "propose_upgrades",
                              "diary", "all"],
                    help="strategy=每周策略建议 / propose_rules=未匹配失败分析 / "
                         "propose_upgrades=规则升级 / diary=账号周记 / all=全跑")
    ap.add_argument("--hours", type=int, default=24,
                    help="propose_rules 回溯小时数")
    ap.add_argument("--weeks-back", type=int, default=0,
                    help="diary 模式: 0=本周, 1=上周")
    args = ap.parse_args()

    result = {}
    if args.mode in ("strategy", "all"):
        result["strategy"] = run(dry_run=args.dry_run)
    if args.mode in ("propose_rules", "all"):
        result["propose_rules"] = propose_new_rules_from_unmatched(
            dry_run=args.dry_run, hours=args.hours)
    if args.mode in ("propose_upgrades", "all"):
        result["propose_upgrades"] = propose_upgrades_for_low_confidence(
            dry_run=args.dry_run)
    if args.mode in ("diary", "all"):
        result["diary"] = generate_account_diaries(
            dry_run=args.dry_run, weeks_back=args.weeks_back)

    print(_j.dumps(result, ensure_ascii=False, indent=2, default=str))
