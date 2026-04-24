# -*- coding: utf-8 -*-
"""Agent base class + unified response protocol + LLM hybrid layer.

统一响应信封 (TASK_QUEUE_AND_AGENT_STATE_DESIGN §8.1):

    {
      "agent":           "analysis",
      "schema_version":  "1.0",
      "status":          "ok | degraded | rejected | error",
      "run_id":          "run_<stamp>_<rand>",
      "confidence":      0.82,
      "findings":        [...],
      "recommendations": [...],
      "rule_rejections": [],
      "error_code":      "",
      "error_message":   "",
      "meta":            {"latency_ms": 320, "source_count": 28,
                          "llm": {"mode":"hybrid", "calls":2, "tokens":9500, "cost":0}}
    }

子类只实现 ``_compute(payload)``. 如果子类想用 LLM, 调 ``self.llm_enrich(...)``
让基类统一记录 trace.
"""
from __future__ import annotations

import json
import secrets
import time
import traceback
from abc import ABC, abstractmethod
from datetime import datetime
from typing import Any

from core.switches import is_enabled


SCHEMA_VERSION = "1.0"

RESPONSE_STATUS_OK = "ok"
RESPONSE_STATUS_DEGRADED = "degraded"
RESPONSE_STATUS_REJECTED = "rejected"
RESPONSE_STATUS_ERROR = "error"

ERROR_CODES = {
    "AUTH_EXPIRED", "AUTH_INVALID", "ASSET_MISSING", "ASSET_QC_FAILED",
    "PUBLISH_CHANNEL_A_FAILED", "PUBLISH_CHANNEL_B_FAILED",
    "VERIFY_TIMEOUT", "UPSTREAM_DATA_MISSING", "RULE_BLOCKED",
    "UNKNOWN_INTERNAL_ERROR",
    "AGENT_INPUT_INVALID", "AGENT_TIMEOUT", "AGENT_LLM_UNAVAILABLE",
}


class AgentResponse:
    @staticmethod
    def make(
        agent: str,
        run_id: str,
        *,
        status: str = RESPONSE_STATUS_OK,
        confidence: float = 1.0,
        findings: list | None = None,
        recommendations: list | None = None,
        rule_rejections: list | None = None,
        error_code: str = "",
        error_message: str = "",
        meta: dict | None = None,
    ) -> dict:
        return {
            "agent": agent,
            "schema_version": SCHEMA_VERSION,
            "status": status,
            "run_id": run_id,
            "confidence": round(float(confidence), 4),
            "findings": findings or [],
            "recommendations": recommendations or [],
            "rule_rejections": rule_rejections or [],
            "error_code": error_code,
            "error_message": error_message,
            "meta": meta or {},
        }

    @staticmethod
    def error(agent: str, run_id: str, *, error_code: str,
              error_message: str = "") -> dict:
        return AgentResponse.make(
            agent=agent, run_id=run_id,
            status=RESPONSE_STATUS_ERROR, confidence=0,
            error_code=error_code, error_message=error_message,
        )


class BaseAgent(ABC):
    """统一基类: run_id / 计时 / agent_runs 落表 / LLM hybrid 增强."""

    name: str = "base"

    # 子类可覆盖:
    # llm_mode:  "rules" 纯规则 / "ai" 仅 LLM / "hybrid" 规则在前 LLM 在后
    llm_mode: str = "hybrid"
    llm_provider_override: str | None = None   # 强制指定 provider (debug 用)

    def __init__(self, db_manager):
        self.db = db_manager
        # 运行期的 tracer — 在 run() 里按 run_id 实例化
        self._tracer = None
        self._current_run_id = ""

    @abstractmethod
    def _compute(self, payload: dict) -> dict:
        raise NotImplementedError

    # ------------------------------------------------------------------
    # 对外: run
    # ------------------------------------------------------------------

    def run(self, payload: dict | None = None, *,
            batch_id: str = "", account_id: str = "") -> dict:
        payload = payload or {}
        run_id = self._make_run_id()
        self._current_run_id = run_id
        start = time.time()

        # 初始化 tracer (延迟 import 避免循环)
        try:
            from core.llm.trace import LLMTracer
            self._tracer = LLMTracer(self.db, run_id=run_id, agent_name=self.name)
        except Exception:
            self._tracer = None

        try:
            response = self._compute(payload)
            if not isinstance(response, dict):
                response = AgentResponse.error(
                    self.name, run_id,
                    error_code="UNKNOWN_INTERNAL_ERROR",
                    error_message="agent 返回非 dict",
                )
            response["run_id"] = run_id
            response["agent"] = self.name
        except Exception as exc:
            tb = traceback.format_exc()
            response = AgentResponse.error(
                self.name, run_id,
                error_code="UNKNOWN_INTERNAL_ERROR",
                error_message=f"{type(exc).__name__}: {exc}",
            )
            response["meta"]["traceback"] = tb[:2000]

        latency_ms = int((time.time() - start) * 1000)
        response.setdefault("meta", {})["latency_ms"] = latency_ms

        # 合入 LLM summary 到 meta.llm
        if self._tracer is not None:
            llm_summary = self._tracer.summary()
            if llm_summary["call_count"] > 0:
                response["meta"]["llm"] = {
                    "mode": self.llm_mode,
                    **llm_summary,
                }

        self._persist(run_id, response, payload, batch_id, account_id, latency_ms)

        # flush tracer (回写 llm_calls_json)
        if self._tracer is not None:
            try:
                self._tracer.flush()
            except Exception:
                pass

        self._current_run_id = ""
        return response

    # ------------------------------------------------------------------
    # 子类调用: llm_enrich
    # ------------------------------------------------------------------

    def get_llm(self):
        """获得 LLMClient (懒加载 + 自动注入 tracer + respect 开关)."""
        # 开关检查
        if not is_enabled("ai_decision_enabled") or not is_enabled("llm_consultation_enabled"):
            return None
        if self.llm_mode == "rules":
            return None
        try:
            from core.llm import LLMClient
        except Exception:
            return None
        llm = LLMClient(provider=self.llm_provider_override)
        if not llm.available:
            return None
        if self._tracer is not None:
            llm.set_trace_callback(self._tracer.record)
        return llm

    def llm_enrich(
        self,
        *,
        system_prompt: str,
        user_prompt: str,
        purpose: str = "",
        as_json: bool = True,
    ) -> dict | str | None:
        """子类的便捷入口: 带 trace 的 LLM 调用."""
        llm = self.get_llm()
        if llm is None:
            return None
        if as_json:
            return llm.chat_json(
                system_prompt, user_prompt,
                purpose=purpose, agent_name=self.name,
                run_id=self._current_run_id,
            )
        return llm.chat(
            system_prompt, user_prompt,
            purpose=purpose, agent_name=self.name,
            run_id=self._current_run_id,
        )

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _make_run_id() -> str:
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        rand = secrets.token_hex(3)
        return f"run_{stamp}_{rand}"

    def _persist(self, run_id: str, response: dict, payload: dict,
                 batch_id: str, account_id: str, latency_ms: int) -> None:
        if self.db is None:
            return
        try:
            self.db.conn.execute(
                """INSERT INTO agent_runs
                     (agent_name, run_id, batch_id, account_id, schema_version,
                      status, confidence,
                      input_json, output_json,
                      findings_count, recommendations_count, rule_rejections_count,
                      error_code, error_message,
                      latency_ms,
                      llm_mode, prompt_version)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    self.name, run_id, batch_id, account_id,
                    response.get("schema_version", SCHEMA_VERSION),
                    response.get("status", RESPONSE_STATUS_ERROR),
                    float(response.get("confidence", 0)),
                    json.dumps(payload, ensure_ascii=False, default=str)[:60000],
                    json.dumps(response, ensure_ascii=False, default=str)[:60000],
                    len(response.get("findings", [])),
                    len(response.get("recommendations", [])),
                    len(response.get("rule_rejections", [])),
                    response.get("error_code", ""),
                    response.get("error_message", "")[:500],
                    latency_ms,
                    self.llm_mode,
                    response.get("meta", {}).get("prompt_version", ""),
                ),
            )
            self.db.conn.commit()
        except Exception:
            pass
