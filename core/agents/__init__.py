# -*- coding: utf-8 -*-
"""Agent architecture — 4 Agent production design.

Per PRODUCTION_EVOLUTION_PLAN.md §6 and
TASK_QUEUE_AND_AGENT_STATE_DESIGN.md §7-9:

  AnalysisAgent     — data analyst; outputs findings + recommendations
  ExperimentAgent   — experiment manager; proposes A/B plans
  ScaleAgent        — scale manager; proposes amplification plans
  OrchestratorAgent — ONLY Agent allowed to dispatch; merges advice +
                      consults rule engine + writes decision_history +
                      creates task_queue tasks

All 4 share:
  - AgentResponse JSON envelope (schema_version 1.0)
  - BaseAgent with agent_runs persistence + latency tracking
  - Status values: ok / degraded / rejected / error
"""

from core.agents.base import (  # noqa: F401
    BaseAgent,
    AgentResponse,
    RESPONSE_STATUS_OK,
    RESPONSE_STATUS_DEGRADED,
    RESPONSE_STATUS_REJECTED,
    RESPONSE_STATUS_ERROR,
    ERROR_CODES,
)
