# -*- coding: utf-8 -*-
"""Agent 调试助手 — 给控制台 "调试中心" Tab 用.

功能:
  - trigger(agent_name, payload, db)        手动触发 + 返回 full response
  - get_run_detail(run_id, db)              取单次运行详情 (input + output + 元信息)
  - list_runs(db, filters)                  带过滤的运行历史
  - list_batches(db)                        按 batch_id 聚合的"决策回合"列表
  - batch_detail(batch_id, db)              单个回合下所有 Agent 的运行树
  - replay(run_id, db)                      用同样的 input 重跑一次 (同 payload)
"""
from __future__ import annotations

import json
from typing import Any

from core.agents.registry import AGENT_REGISTRY, get_agent_class, agent_exists
from core.switches import is_enabled


# ---------------------------------------------------------------------------
# Manual trigger
# ---------------------------------------------------------------------------

def trigger(agent_name: str, payload: dict | None, db_manager,
            *, batch_id: str = "", account_id: str = "",
            respect_switch: bool = True) -> dict[str, Any]:
    """手动触发 Agent.

    respect_switch=True (默认): 先检查 `{agent}_agent_enabled` 开关, OFF 则返回 rejected.
    调试时可关 respect_switch 直接跑.
    """
    payload = payload or {}
    if not agent_exists(agent_name):
        return {
            "status": "error",
            "error_code": "AGENT_NOT_FOUND",
            "error_message": f"未知 Agent: {agent_name}",
            "available": list(AGENT_REGISTRY.keys()),
        }

    meta = AGENT_REGISTRY[agent_name]
    switch_code = meta.get("switch_code")
    if respect_switch and switch_code and not is_enabled(switch_code):
        return {
            "status": "rejected",
            "error_code": "AGENT_DISABLED_BY_SWITCH",
            "error_message": f"开关 {switch_code} = OFF",
            "agent": agent_name,
            "switch_code": switch_code,
        }

    cls = get_agent_class(agent_name)
    instance = cls(db_manager)
    return instance.run(payload, batch_id=batch_id, account_id=account_id)


# ---------------------------------------------------------------------------
# Run history queries
# ---------------------------------------------------------------------------

def list_runs(db_manager, *, agent_name: str = "", status: str = "",
              batch_id: str = "", limit: int = 50, offset: int = 0) -> list[dict]:
    where = []
    params: list[Any] = []
    if agent_name:
        where.append("agent_name = ?")
        params.append(agent_name)
    if status:
        where.append("status = ?")
        params.append(status)
    if batch_id:
        where.append("batch_id = ?")
        params.append(batch_id)
    where_sql = ("WHERE " + " AND ".join(where)) if where else ""
    rows = db_manager.conn.execute(
        f"""SELECT id, agent_name, run_id, batch_id, account_id,
                   status, confidence,
                   findings_count, recommendations_count, rule_rejections_count,
                   error_code, error_message, latency_ms,
                   created_at
            FROM agent_runs {where_sql}
            ORDER BY id DESC LIMIT ? OFFSET ?""",
        (*params, limit, offset),
    ).fetchall()
    cols = ["id","agent","run_id","batch_id","account","status","confidence",
            "findings","recs","rejections","err_code","err_msg","latency_ms","created_at"]
    return [dict(zip(cols, r)) for r in rows]


def get_run_detail(run_id: str, db_manager) -> dict | None:
    row = db_manager.conn.execute(
        """SELECT id, agent_name, run_id, batch_id, account_id,
                  schema_version, status, confidence,
                  input_json, output_json,
                  findings_count, recommendations_count, rule_rejections_count,
                  error_code, error_message, latency_ms,
                  llm_provider, prompt_version, created_at
           FROM agent_runs WHERE run_id = ? LIMIT 1""",
        (run_id,),
    ).fetchone()
    if not row:
        return None
    cols = ["id","agent","run_id","batch_id","account_id","schema_version",
            "status","confidence","input_json","output_json",
            "findings","recs","rejections","err_code","err_msg","latency_ms",
            "llm_provider","prompt_version","created_at"]
    d = dict(zip(cols, row))
    try:
        d["input"] = json.loads(d.pop("input_json") or "{}")
    except Exception:
        d["input"] = {}
        d.pop("input_json", None)
    try:
        d["output"] = json.loads(d.pop("output_json") or "{}")
    except Exception:
        d["output"] = {}
        d.pop("output_json", None)
    return d


def list_batches(db_manager, limit: int = 30) -> list[dict]:
    """决策回合视图 — 按 batch_id 聚合."""
    rows = db_manager.conn.execute(
        """SELECT batch_id,
                  MIN(created_at) AS started_at,
                  MAX(created_at) AS ended_at,
                  COUNT(*) AS runs,
                  SUM(CASE WHEN status='ok' THEN 1 ELSE 0 END)       AS ok_count,
                  SUM(CASE WHEN status='error' THEN 1 ELSE 0 END)    AS err_count,
                  SUM(findings_count)                                AS total_findings,
                  SUM(recommendations_count)                         AS total_recs,
                  AVG(confidence)                                    AS avg_confidence,
                  GROUP_CONCAT(DISTINCT agent_name)                  AS agents
           FROM agent_runs
           WHERE batch_id IS NOT NULL AND batch_id <> ''
           GROUP BY batch_id
           ORDER BY ended_at DESC LIMIT ?""",
        (limit,),
    ).fetchall()
    cols = ["batch_id","started_at","ended_at","runs","ok_count","err_count",
            "total_findings","total_recs","avg_confidence","agents"]
    return [dict(zip(cols, r)) for r in rows]


def batch_detail(batch_id: str, db_manager) -> dict | None:
    """某个 batch 的全量详情 (含 decision_history)."""
    runs = list_runs(db_manager, batch_id=batch_id, limit=100)
    if not runs:
        return None

    # decision_history 里以 batch_id 为纽带
    try:
        drow = db_manager.conn.execute(
            """SELECT id, created_at, batch_id, decision_reasoning, publish_count,
                      rule_ids_applied
               FROM decision_history WHERE batch_id = ? ORDER BY id DESC LIMIT 1""",
            (batch_id,),
        ).fetchone()
    except Exception:
        drow = None

    decision = None
    if drow:
        decision = {
            "id": drow[0], "created_at": drow[1], "batch_id": drow[2],
            "reasoning": drow[3], "publish_count": drow[4],
            "rule_ids_applied": drow[5],
        }

    return {
        "batch_id": batch_id,
        "runs": runs,
        "decision": decision,
        "agent_count": len({r["agent"] for r in runs}),
    }


# ---------------------------------------------------------------------------
# Replay
# ---------------------------------------------------------------------------

def replay(run_id: str, db_manager) -> dict[str, Any]:
    """用同样的 input 重跑一次 (但生成新的 run_id)."""
    detail = get_run_detail(run_id, db_manager)
    if not detail:
        return {"status": "error", "error_code": "RUN_NOT_FOUND",
                "error_message": f"run_id={run_id} 不存在"}
    return trigger(
        detail["agent"],
        detail.get("input") or {},
        db_manager,
        batch_id=detail.get("batch_id", "") + "_replay",
        account_id=detail.get("account_id", "") or "",
        respect_switch=False,
    )


# ---------------------------------------------------------------------------
# Quick stats for dashboard header
# ---------------------------------------------------------------------------

def summary(db_manager) -> dict[str, Any]:
    row = db_manager.conn.execute(
        """SELECT
             COUNT(*) AS total,
             SUM(CASE WHEN status='ok'       THEN 1 ELSE 0 END) AS ok,
             SUM(CASE WHEN status='degraded' THEN 1 ELSE 0 END) AS degraded,
             SUM(CASE WHEN status='rejected' THEN 1 ELSE 0 END) AS rejected,
             SUM(CASE WHEN status='error'    THEN 1 ELSE 0 END) AS error,
             AVG(confidence) AS avg_conf,
             AVG(latency_ms) AS avg_latency,
             SUM(CASE WHEN DATE(created_at)=DATE('now','localtime') THEN 1 ELSE 0 END) AS today
           FROM agent_runs"""
    ).fetchone()
    cols = ["total","ok","degraded","rejected","error","avg_conf","avg_latency","today"]
    return dict(zip(cols, row))
