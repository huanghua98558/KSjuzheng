# -*- coding: utf-8 -*-
"""Orchestrator — **唯一**有权下发任务的 Agent (LangGraph StateGraph).

节点图:
    [gather_context]                   采集系统快照
            ↓
    [run_analysis]                     纯规则 + GPT-5.4 增量归因
            ↓
    [run_experiment]                   LLM 设计 A/B 实验
            ↓
    [run_scale]                        LLM 审核 winner 真伪
            ↓
    [merge_advice]                     三路 findings+recs 合并
            ↓
    [rule_gate]  ─ rejected ─→  (记录)
            ↓ allowed
    [llm_arbitrate] (可选)             GPT-5.4 最终裁决 + 分 hitl
            ↓
    [generate_plan]                    execution_plan + manual_review_items
            ↓
    [persist_decision]                 落 decision_history + system_events
            ↓
         END

HITL 节点 (未来): 如果 plan 含 critical 项, interrupt 等人工确认
Checkpoint: 用 SqliteSaver 存到 langgraph_checkpoints 表
"""
from __future__ import annotations

import json
import secrets
import sqlite3
from datetime import datetime
from typing import Any, TypedDict

from core.agents.base import BaseAgent, AgentResponse, RESPONSE_STATUS_OK
from core.agents.analysis_agent import AnalysisAgent
from core.agents.experiment_agent import ExperimentAgent
from core.agents.scale_agent import ScaleAgent
from core.agents.rule_engine import RuleEngine
from core.llm.prompts import get_prompt
from core.switches import is_enabled
from core.config import DB_PATH

try:
    from langgraph.graph import END, StateGraph
    from langgraph.checkpoint.sqlite import SqliteSaver
    LANGGRAPH_OK = True
except ImportError:
    LANGGRAPH_OK = False


# ---------------------------------------------------------------------------
# State 定义
# ---------------------------------------------------------------------------

class OrchestratorState(TypedDict, total=False):
    batch_id:        str
    run_id:          str
    payload:         dict
    analysis:        dict
    experiment:      dict
    scale:           dict
    findings_all:    list
    raw_recs:        list
    allowed:         list
    rejected:        list
    execution_plan:  list
    pending_human:   list
    decision_id:     int
    decision_reasoning: str
    confidence:      float
    status:          str


# ---------------------------------------------------------------------------
# Orchestrator
# ---------------------------------------------------------------------------

class Orchestrator(BaseAgent):
    name = "orchestrator"
    llm_mode = "hybrid"

    def __init__(self, db_manager):
        super().__init__(db_manager)
        self.analysis = AnalysisAgent(db_manager)
        self.experiment = ExperimentAgent(db_manager)
        self.scale = ScaleAgent(db_manager)
        self.rules = RuleEngine(db_manager)
        self._graph = None
        if LANGGRAPH_OK:
            self._graph = self._build_graph()

    # ==================================================================
    # 入口
    # ==================================================================

    def _compute(self, payload: dict) -> dict:
        batch_id = payload.get("batch_id") or self._new_batch_id()

        if self._graph is not None:
            final_state = self._run_graph(batch_id, payload)
        else:
            final_state = self._run_sequential(batch_id, payload)

        findings_all = final_state.get("findings_all", [])
        allowed = final_state.get("allowed", [])
        rejected = final_state.get("rejected", [])
        plan = final_state.get("execution_plan", [])
        pending_human = final_state.get("pending_human", [])
        decision_id = final_state.get("decision_id")

        summary = {
            "batch_id": batch_id,
            "decision_id": decision_id,
            "findings_count": len(findings_all),
            "raw_recommendations_count": len(final_state.get("raw_recs", [])),
            "allowed_count": len(allowed),
            "rule_rejection_count": len(rejected),
            "execution_plan_count": len(plan),
            "pending_human_count": len(pending_human),
            "sub_agent_status": {
                "analysis":   final_state.get("analysis", {}).get("status"),
                "experiment": final_state.get("experiment", {}).get("status"),
                "scale":      final_state.get("scale", {}).get("status"),
            },
            "graph_mode": "langgraph" if self._graph else "sequential",
        }

        return AgentResponse.make(
            self.name, run_id="",
            status=final_state.get("status", RESPONSE_STATUS_OK),
            confidence=final_state.get("confidence", 0.7),
            findings=findings_all,
            recommendations=allowed,
            rule_rejections=rejected,
            meta={
                "batch_id": batch_id,
                "decision_id": decision_id,
                "decision_summary": summary,
                "execution_plan": plan,
                "pending_human": pending_human,
                "decision_reasoning": final_state.get("decision_reasoning", ""),
                "sub_agent_runs": {
                    "analysis":   final_state.get("analysis", {}).get("run_id"),
                    "experiment": final_state.get("experiment", {}).get("run_id"),
                    "scale":      final_state.get("scale", {}).get("run_id"),
                },
                "prompt_version": "orchestrator_v1.0_zh",
            },
        )

    # ==================================================================
    # LangGraph 图
    # ==================================================================

    def _build_graph(self):
        g = StateGraph(OrchestratorState)
        g.add_node("gather",      self._node_gather)
        g.add_node("analysis",    self._node_analysis)
        g.add_node("experiment",  self._node_experiment)
        g.add_node("scale",       self._node_scale)
        g.add_node("merge",       self._node_merge)
        g.add_node("rule_gate",   self._node_rule_gate)
        g.add_node("arbitrate",   self._node_arbitrate)
        g.add_node("plan",        self._node_plan)
        g.add_node("persist",     self._node_persist)

        g.set_entry_point("gather")
        g.add_edge("gather",     "analysis")
        g.add_edge("analysis",   "experiment")
        g.add_edge("experiment", "scale")
        g.add_edge("scale",      "merge")
        g.add_edge("merge",      "rule_gate")
        # 条件路由: 有 allowed 就进 arbitrate, 没有直接 plan
        g.add_conditional_edges(
            "rule_gate",
            lambda s: "arbitrate" if s.get("allowed") else "plan",
            {"arbitrate": "arbitrate", "plan": "plan"},
        )
        g.add_edge("arbitrate", "plan")
        g.add_edge("plan",      "persist")
        g.add_edge("persist",   END)

        # Checkpoint — 存本项目 SQLite 方便事后回放
        try:
            conn = sqlite3.connect(DB_PATH, check_same_thread=False)
            saver = SqliteSaver(conn)
            return g.compile(checkpointer=saver)
        except Exception:
            return g.compile()

    def _run_graph(self, batch_id: str, payload: dict) -> dict:
        config = {"configurable": {"thread_id": batch_id}}
        initial: OrchestratorState = {
            "batch_id": batch_id,
            "payload": payload,
            "findings_all": [],
            "raw_recs": [],
            "allowed": [],
            "rejected": [],
            "execution_plan": [],
            "pending_human": [],
        }
        try:
            final = self._graph.invoke(initial, config=config)
            return dict(final)
        except Exception as exc:
            # 退回顺序执行
            return self._run_sequential(batch_id, payload, error=str(exc))

    def _run_sequential(self, batch_id: str, payload: dict,
                        error: str = "") -> dict:
        state: OrchestratorState = {
            "batch_id": batch_id, "payload": payload,
            "findings_all": [], "raw_recs": [], "allowed": [],
            "rejected": [], "execution_plan": [], "pending_human": [],
        }
        for fn in (self._node_gather, self._node_analysis, self._node_experiment,
                   self._node_scale, self._node_merge, self._node_rule_gate,
                   self._node_arbitrate, self._node_plan, self._node_persist):
            try:
                upd = fn(state) or {}
                state.update(upd)   # type: ignore[arg-type]
            except Exception as exc:
                state["status"] = "degraded"
        if error:
            state["status"] = "degraded"
        return dict(state)

    # ==================================================================
    # 节点实现
    # ==================================================================

    def _node_gather(self, s: OrchestratorState) -> dict:
        # 读一些辅助 context (系统开关 / 账号池规模), 供 arbitrate 使用
        payload = s.get("payload") or {}
        group_filter = payload.get("group") or payload.get("account_group") or ""
        lifecycle_filter = payload.get("lifecycle_stage") or ""
        try:
            if group_filter:
                total_accts = self.db.conn.execute(
                    """SELECT COUNT(*) FROM device_accounts
                       WHERE login_status='logged_in' AND account_group=?""",
                    (group_filter,),
                ).fetchone()[0]
            elif lifecycle_filter:
                total_accts = self.db.conn.execute(
                    """SELECT COUNT(*) FROM device_accounts
                       WHERE login_status='logged_in' AND lifecycle_stage=?""",
                    (lifecycle_filter,),
                ).fetchone()[0]
            else:
                total_accts = self.db.conn.execute(
                    "SELECT COUNT(*) FROM device_accounts WHERE login_status='logged_in'"
                ).fetchone()[0]
        except Exception:
            total_accts = 0

        # 组级开关覆盖
        try:
            from core.switches import is_enabled_for_group
            ctx_switches = {
                "ai_decision_enabled":    is_enabled_for_group("ai_decision_enabled",    group_filter or None),
                "publish_enabled":        is_enabled_for_group("publish_enabled",        group_filter or None),
                "auto_scale_enabled":     is_enabled_for_group("auto_scale_enabled",     group_filter or None),
                "experiment_auto_launch": is_enabled_for_group("experiment_auto_launch", group_filter or None),
            }
        except Exception:
            ctx_switches = {
                "ai_decision_enabled":    is_enabled("ai_decision_enabled"),
                "publish_enabled":        is_enabled("publish_enabled"),
                "auto_scale_enabled":     is_enabled("auto_scale_enabled"),
                "experiment_auto_launch": is_enabled("experiment_auto_launch"),
            }
        ctx = {
            **ctx_switches,
            "logged_in_accounts":      total_accts,
            "group_filter":            group_filter,
            "lifecycle_filter":        lifecycle_filter,
            "gathered_at":             datetime.now().isoformat(),
        }
        return {"payload": {**payload, "context": ctx}}

    def _node_analysis(self, s: OrchestratorState) -> dict:
        r = self.analysis.run({}, batch_id=s["batch_id"])
        return {"analysis": r}

    def _node_experiment(self, s: OrchestratorState) -> dict:
        r = self.experiment.run({}, batch_id=s["batch_id"])
        return {"experiment": r}

    def _node_scale(self, s: OrchestratorState) -> dict:
        r = self.scale.run({}, batch_id=s["batch_id"])
        return {"scale": r}

    def _node_merge(self, s: OrchestratorState) -> dict:
        fa = (
            [{"source": "analysis",   **f} for f in s["analysis"].get("findings", [])] +
            [{"source": "experiment", **f} for f in s["experiment"].get("findings", [])] +
            [{"source": "scale",      **f} for f in s["scale"].get("findings", [])]
        )
        rr = (
            [{"source": "analysis",   **r} for r in s["analysis"].get("recommendations", [])] +
            [{"source": "experiment", **r} for r in s["experiment"].get("recommendations", [])] +
            [{"source": "scale",      **r} for r in s["scale"].get("recommendations", [])]
        )
        # confidence 加权
        ca = s["analysis"].get("confidence", 0)
        ce = s["experiment"].get("confidence", 0)
        cs = s["scale"].get("confidence", 0)
        conf = round(ca * 0.5 + ce * 0.25 + cs * 0.25, 3)
        statuses = [s["analysis"].get("status"), s["experiment"].get("status"),
                    s["scale"].get("status")]
        status = "degraded" if any(st in ("degraded", "error") for st in statuses) else "ok"
        return {
            "findings_all": fa,
            "raw_recs": rr,
            "confidence": conf,
            "status": status,
        }

    def _node_rule_gate(self, s: OrchestratorState) -> dict:
        allowed, rejected = self.rules.filter_recommendations(s["raw_recs"])
        return {"allowed": allowed, "rejected": rejected}

    def _node_arbitrate(self, s: OrchestratorState) -> dict:
        """LLM 总控裁决 — 把各 agent 输出合成每日执行计划 + 人工项."""
        if not is_enabled("orchestrator_enabled") or not is_enabled("llm_consultation_enabled"):
            return {}
        # 构建 orchestrator prompt
        p = get_prompt("orchestrator")
        user_prompt = p["user_template"].format(
            analysis_output=json.dumps({
                "status": s["analysis"].get("status"),
                "confidence": s["analysis"].get("confidence"),
                "findings": s["analysis"].get("findings", [])[:15],
                "recommendations": s["analysis"].get("recommendations", [])[:10],
            }, ensure_ascii=False, default=str)[:4000],
            experiment_output=json.dumps({
                "status": s["experiment"].get("status"),
                "recommendations": s["experiment"].get("recommendations", [])[:6],
            }, ensure_ascii=False, default=str)[:2500],
            scale_output=json.dumps({
                "status": s["scale"].get("status"),
                "recommendations": s["scale"].get("recommendations", [])[:6],
            }, ensure_ascii=False, default=str)[:2500],
            system_state_json=json.dumps(
                (s.get("payload") or {}).get("context", {}),
                ensure_ascii=False, default=str,
            ),
            rule_rejections=json.dumps(
                s.get("rejected", [])[:10], ensure_ascii=False, default=str,
            )[:2000],
        )
        llm_out = self.llm_enrich(
            system_prompt=p["system"], user_prompt=user_prompt,
            purpose="orchestrator_arbitrate", as_json=True,
        )
        if not llm_out:
            return {}
        pending = llm_out.get("pending_human", []) or []
        reasoning = llm_out.get("daily_decision_reasoning", "")
        # 把 LLM 生成的 execution_plan 吸收 (与规则 allowed 合并去重)
        extra_plan = llm_out.get("execution_plan", []) or []
        merged_allowed = s.get("allowed", [])[:]
        seen = {json.dumps(x, sort_keys=True, default=str) for x in merged_allowed}
        for item in extra_plan:
            k = json.dumps(item, sort_keys=True, default=str)
            if k not in seen:
                merged_allowed.append({"source": "orchestrator_llm", **item})
        return {
            "allowed": merged_allowed,
            "pending_human": pending,
            "decision_reasoning": reasoning,
        }

    def _node_plan(self, s: OrchestratorState) -> dict:
        plan = self._to_execution_plan(s.get("allowed", []), s["batch_id"])
        # 如果还没有 decision_reasoning (arbitrate 没跑), 用规则版兜底
        if not s.get("decision_reasoning"):
            reasoning = (
                f"批次 {s['batch_id']}: 合并 {len(s.get('findings_all', []))} "
                f"findings, {len(s.get('allowed', []))} 条通过规则, 产出 "
                f"{len(plan)} 个执行动作."
            )
        else:
            reasoning = s["decision_reasoning"]
        return {"execution_plan": plan, "decision_reasoning": reasoning}

    def _node_persist(self, s: OrchestratorState) -> dict:
        did = self._persist_decision(
            s["batch_id"],
            s.get("findings_all", []),
            s.get("allowed", []),
            s.get("rejected", []),
            s.get("execution_plan", []),
            s.get("pending_human", []),
            s.get("decision_reasoning", ""),
            s.get("confidence", 0.7),
        )
        # 人工审核项落 manual_review_items
        self._write_pending_human(s["batch_id"], s.get("pending_human", []))
        self._emit_event("orchestrator_run",
                         f"batch {s['batch_id']} produced "
                         f"{len(s.get('execution_plan', []))} actions, "
                         f"{len(s.get('pending_human', []))} pending human")
        return {"decision_id": did}

    # ==================================================================
    # Helpers
    # ==================================================================

    @staticmethod
    def _new_batch_id() -> str:
        return f"batch_{datetime.now().strftime('%Y%m%d_%H%M%S')}_{secrets.token_hex(2)}"

    def _to_execution_plan(self, recs: list[dict], batch_id: str) -> list[dict]:
        plan = []
        for rec in recs:
            action = rec.get("action", "")
            priority = rec.get("priority_num", 50)
            if isinstance(rec.get("priority"), str):
                priority = {"critical": 10, "high": 30, "normal": 50, "low": 80}.get(
                    rec["priority"], 50)
            else:
                # 按 action 推断
                if action in ("prefer_genre", "reactivate_idle_accounts", "boost"):
                    priority = 30
                elif action in ("refill_drama_pool", "mcn_binding_audit"):
                    priority = 40
                elif action in ("create_experiment", "scale_pattern", "experiment"):
                    priority = 50
                elif action in ("reduce", "investigate"):
                    priority = 60
            plan.append({"batch_id": batch_id, "priority_num": priority, **rec})
        return sorted(plan, key=lambda x: x.get("priority_num", 50))

    def _persist_decision(self, batch_id: str, findings: list,
                          allowed: list, rejected: list,
                          execution_plan: list, pending_human: list,
                          reasoning: str, confidence: float) -> int | None:
        try:
            cursor = self.db.conn.execute(
                """INSERT INTO decision_history
                     (account_id, drama_name, strategy_name, channel,
                      publish_count, decision_reasoning,
                      created_at, llm_provider, prompt_version,
                      batch_id, source_agent, confidence, plan_type,
                      execution_plan_json, rule_rejections_json,
                      pending_human_json)
                   VALUES (?, ?, ?, ?, ?, ?,
                           datetime('now','localtime'), ?, ?,
                           ?, ?, ?, ?,
                           ?, ?, ?)""",
                (
                    "(multi)", "(multi)", "orchestrator_v2", "mixed",
                    len(execution_plan),
                    reasoning[:10000] if reasoning else json.dumps({
                        "findings": findings[:20], "allowed": allowed[:20],
                        "rejected": rejected[:10],
                    }, ensure_ascii=False, default=str)[:10000],
                    "mixed", "orchestrator_v1.0_zh",
                    batch_id, "orchestrator", float(confidence), "matrix_meta",
                    json.dumps(execution_plan[:60], ensure_ascii=False, default=str)[:16000],
                    json.dumps(rejected[:30], ensure_ascii=False, default=str)[:8000],
                    json.dumps(pending_human[:30], ensure_ascii=False, default=str)[:8000],
                ),
            )
            self.db.conn.commit()
            return cursor.lastrowid
        except Exception:
            return None

    def _write_pending_human(self, batch_id: str, items: list) -> None:
        for item in items:
            try:
                rid = f"rev_{batch_id[-10:]}_{secrets.token_hex(2)}"
                self.db.conn.execute(
                    """INSERT INTO manual_review_items
                         (review_id, source_type, source_id, batch_id,
                          manual_status, manual_reason, suggested_action,
                          severity, created_at)
                       VALUES (?, 'orchestrator', ?, ?,
                               'pending', ?, ?, ?, datetime('now','localtime'))""",
                    (
                        rid, item.get("target", ""), batch_id,
                        item.get("reason", "")[:400],
                        item.get("suggested_action", "")[:400],
                        item.get("severity", "normal"),
                    ),
                )
            except Exception:
                continue
        self.db.conn.commit()

    def _emit_event(self, event_type: str, message: str) -> None:
        try:
            self.db.conn.execute(
                """INSERT INTO system_events
                     (event_type, event_level, source_module, payload)
                   VALUES (?, 'info', 'orchestrator', ?)""",
                (event_type,
                 json.dumps({"message": message}, ensure_ascii=False)),
            )
            self.db.conn.commit()
        except Exception:
            pass
