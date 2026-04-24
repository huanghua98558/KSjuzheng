# -*- coding: utf-8 -*-
"""LLM 调用 trace — 回写 agent_runs.llm_calls_json 供 UI 展示.

设计:
  - 每个 Agent run 期间可能触发 N 次 LLM 调用
  - 所有调用记录聚合到 agent_runs.llm_calls_json (JSON 数组)
  - 同时维护 meta: total_cost_usd / total_tokens / total_latency_ms

LLMTracer 用法:
    tracer = LLMTracer(db_manager, run_id="run_xxx", agent_name="analysis")
    llm = LLMClient(provider="codex")
    llm.set_trace_callback(tracer.record)

    # ... 正常调 llm.chat() / chat_json() ...

    tracer.flush()   # 把累积的 llm_calls 写入 agent_runs 表
"""
from __future__ import annotations

import json
from typing import Any


class LLMTracer:
    """收集一次 agent.run() 期间的全部 LLM 调用, flush 时写回 DB."""

    def __init__(self, db_manager, *, run_id: str, agent_name: str):
        self.db = db_manager
        self.run_id = run_id
        self.agent_name = agent_name
        self.calls: list[dict] = []

    # 由 LLMClient trace_callback 注入调用
    def record(self, record: dict) -> None:
        # 去掉过长 preview, 保留元信息
        call = {
            "provider": record.get("provider"),
            "model": record.get("model"),
            "purpose": record.get("purpose"),
            "prompt_tokens": record.get("prompt_tokens", 0),
            "completion_tokens": record.get("completion_tokens", 0),
            "latency_ms": record.get("latency_ms", 0),
            "cost_usd": record.get("cost_usd", 0),
            "ok": record.get("ok"),
            "error": record.get("error") or "",
            "system_preview": record.get("system_preview", "")[:150],
            "user_preview": record.get("user_preview", "")[:200],
            "response_preview": record.get("response_preview", "")[:300],
            "ts": record.get("ts"),
        }
        self.calls.append(call)

    def summary(self) -> dict:
        total_prompt = sum(c["prompt_tokens"] for c in self.calls)
        total_completion = sum(c["completion_tokens"] for c in self.calls)
        total_latency = sum(c["latency_ms"] for c in self.calls)
        total_cost = sum(c["cost_usd"] for c in self.calls)
        ok_count = sum(1 for c in self.calls if c["ok"])
        return {
            "call_count": len(self.calls),
            "ok_count": ok_count,
            "error_count": len(self.calls) - ok_count,
            "total_prompt_tokens": total_prompt,
            "total_completion_tokens": total_completion,
            "total_tokens": total_prompt + total_completion,
            "total_latency_ms": total_latency,
            "total_cost_usd": round(total_cost, 6),
            "primary_provider": (self.calls[0]["provider"] if self.calls else None),
            "primary_model": (self.calls[0]["model"] if self.calls else None),
        }

    def to_json(self) -> str:
        """序列化成 JSON 存表."""
        payload = {
            "calls": self.calls,
            "summary": self.summary(),
        }
        return json.dumps(payload, ensure_ascii=False, default=str)[:120_000]

    def flush(self) -> None:
        """写入 agent_runs 表的 llm_calls_json 字段 (如果存在)."""
        if not self.calls or self.db is None:
            return
        payload = self.to_json()
        summary = self.summary()
        try:
            self.db.conn.execute(
                """UPDATE agent_runs SET
                     llm_calls_json = ?,
                     llm_provider   = COALESCE(NULLIF(llm_provider,''), ?),
                     prompt_version = COALESCE(NULLIF(prompt_version,''), ?)
                   WHERE run_id = ?""",
                (payload,
                 summary.get("primary_provider") or "",
                 "",   # prompt_version 由 Agent 自己填
                 self.run_id),
            )
            self.db.conn.commit()
        except Exception:
            # llm_calls_json 列可能还没 migrate — 忽略
            pass
