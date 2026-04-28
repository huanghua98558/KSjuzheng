"""Phase 3: L9 决策 / L10 Agent / L11 记忆 / L12 自愈 schemas (列表只读 + 触发).

Phase 3 后端只做:
  - GET 各类历史 (候选池 / agent_runs / decision_history / playbook / diagnoses)
  - POST agent 手动触发 (写 agent_runs + 调度 worker, 不在请求线程跑)
  - PUT / approve 规则提议
不做实际剪辑去重 / ffmpeg / 视频处理 — 那在客户端.
"""
from __future__ import annotations

from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


# ============================================================
# L9 候选池
# ============================================================

class DailyCandidatePoolPublic(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    pool_date: date
    organization_id: int
    drama_name: str
    banner_task_id: str | None = None
    biz_id: int | None = None
    commission_rate: float | None = None
    freshness_tier: str | None = None
    w24h_count: int = 0
    w48h_count: int = 0
    cdn_count: int = 0
    pool_count: int = 0
    income_numeric: float | None = None
    violation_status: str | None = None
    score_freshness: float = 0.0
    score_url_ready: float = 0.0
    score_commission: float = 0.0
    score_heat: float = 0.0
    score_matrix: float = 0.0
    score_penalty: float = 0.0
    composite_score: float = 0.0
    status: str = "pending"
    notes: str | None = None
    created_at: datetime


# ============================================================
# L9 Daily Plan
# ============================================================

class DailyPlanPublic(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    organization_id: int
    plan_date: date
    summary: str | None = None
    total_items: int = 0
    finished_items: int = 0
    status: str = "active"
    created_at: datetime


class DailyPlanItemPublic(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    plan_id: int
    organization_id: int
    account_id: int
    drama_name: str
    recipe: str | None = None
    image_mode: str | None = None
    sched_at: datetime | None = None
    priority: int = 50
    status: str = "pending"
    reason: str | None = None
    experiment_group: str | None = None
    task_id: int | None = None
    finished_at: datetime | None = None


# ============================================================
# L9 爆款 + Tier
# ============================================================

class BurstDetectionPublic(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    organization_id: int
    drama_name: str
    views_24h: int = 0
    growth_pct: float = 0.0
    income_24h: float = 0.0
    competition_score: float = 0.0
    recommended_accounts: str | None = None
    detected_at: datetime | None = None
    acted_upon: bool = False


class AccountTierTransitionPublic(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    account_id: int
    organization_id: int
    old_tier: str | None = None
    new_tier: str
    reason: str | None = None
    triggered_by: str | None = None
    transitioned_at: datetime | None = None


# ============================================================
# L10 Agent + AutoPilot
# ============================================================

AGENT_NAMES = (
    "strategy_planner", "task_scheduler", "watchdog", "analyzer",
    "llm_researcher", "burst", "maintenance", "self_healing", "controller",
)


class AgentRunPublic(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    run_id: str
    agent_name: str
    organization_id: int | None = None
    trigger_type: str = "schedule"
    triggered_by_user_id: int | None = None
    started_at: datetime | None = None
    finished_at: datetime | None = None
    duration_ms: int | None = None
    status: str = "running"
    output_json: str | None = None
    error_message: str | None = None
    cycle_id: int | None = None
    created_at: datetime


class AgentTriggerRequest(BaseModel):
    """手动触发 agent — 实际跑放 worker / 后台 thread, 端点立即返回."""

    organization_id: int | None = None
    dry_run: bool = True
    note: str | None = None


class AutopilotCyclePublic(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    cycle_id: int
    organization_id: int | None = None
    started_at: datetime | None = None
    finished_at: datetime | None = None
    duration_ms: int | None = None
    status: str = "ok"
    steps_executed: int = 0
    steps_skipped: int = 0
    errors_json: str | None = None


class AutopilotDiagnosisPublic(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    organization_id: int | None = None
    diagnosis_type: str
    severity: str = "medium"
    summary: str
    affected_object: str | None = None
    detected_at: datetime | None = None
    resolved_at: datetime | None = None
    auto_resolved: bool = False
    confidence: float | None = None
    playbook_code: str | None = None


# ============================================================
# L11 记忆
# ============================================================

class DecisionHistoryPublic(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    account_id: int
    organization_id: int
    plan_item_id: int | None = None
    task_id: int | None = None
    drama_name: str
    recipe: str | None = None
    image_mode: str | None = None
    hypothesis: str | None = None
    expected_income: float | None = None
    expected_views: int | None = None
    confidence: float | None = None
    actual_income: float | None = None
    actual_views: int | None = None
    verdict: str | None = None
    decided_at: datetime | None = None
    verdicted_at: datetime | None = None
    reason: str | None = None
    created_at: datetime


class StrategyMemoryPublic(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    account_id: int
    organization_id: int
    total_decisions: int = 0
    correct_count: int = 0
    over_optimistic_count: int = 0
    wrong_count: int = 0
    ai_trust_score: float | None = None
    income_7d: float = 0.0
    income_30d: float = 0.0
    preferred_recipes: str | None = None
    preferred_image_modes: str | None = None
    avoid_drama_ids: str | None = None
    last_aggregated_at: datetime | None = None


class DiaryEntryPublic(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    account_id: int
    organization_id: int
    week_start: date | None = None
    week_end: date | None = None
    summary: str | None = None
    performance_review: str | None = None
    lessons_learned: str | None = None
    next_week_strategy: str | None = None
    approved: bool = False
    generated_at: datetime | None = None


class DiaryApproveRequest(BaseModel):
    approved: bool = True
    note: str | None = None


class StrategyRewardPublic(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    organization_id: int
    account_tier: str
    recipe: str
    image_mode: str | None = None
    total_trials: int = 0
    total_reward: float = 0.0
    avg_reward: float | None = None
    last_updated: datetime | None = None


class ResearchNotePublic(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    organization_id: int | None = None
    note_key: str | None = None
    topic: str
    content: str
    confidence: float | None = None
    approved: bool = False
    source: str | None = None
    created_at: datetime


# ============================================================
# L12 Healing
# ============================================================

class PlaybookPublic(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    code: str
    description: str | None = None
    symptom_pattern: str
    remedy_action: str
    params_json: str | None = None
    confidence: float = 0.5
    success_count: int = 0
    fail_count: int = 0
    enabled: bool = True
    proposed_by: str | None = None
    last_triggered_at: datetime | None = None


class HealingDiagnosisPublic(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    organization_id: int | None = None
    playbook_code: str | None = None
    severity: str = "medium"
    summary: str
    detail_json: str | None = None
    target_type: str | None = None
    target_id: str | None = None
    auto_resolved: bool = False
    resolved_at: datetime | None = None
    detected_at: datetime | None = None
    created_at: datetime


class RuleProposalPublic(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    organization_id: int | None = None
    proposed_code: str
    symptom_pattern: str
    remedy_action: str
    params_json: str | None = None
    rationale: str | None = None
    sample_count: int = 0
    llm_confidence: float | None = None
    target_playbook_id: int | None = None
    status: str = "pending"
    decided_by_user_id: int | None = None
    decided_at: datetime | None = None
    applied_at: datetime | None = None
    created_at: datetime


class UpgradeProposalPublic(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    target_playbook_code: str
    suggestion_type: str
    suggested_pattern: str | None = None
    suggested_action: str | None = None
    suggested_params_json: str | None = None
    rationale: str | None = None
    llm_confidence: float | None = None
    status: str = "pending"
    decided_at: datetime | None = None
    created_at: datetime


class ProposalDecideRequest(BaseModel):
    decision: Literal["approved", "rejected"]
    note: str | None = None
