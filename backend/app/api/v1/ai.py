"""Phase 3 AI 自动化 API — L9 决策 / L10 Agent / L11 记忆 / L12 自愈."""
from __future__ import annotations

from fastapi import APIRouter, Depends, Request

from app.core.audit import audit_request
from app.core.deps import DbSession
from app.core.envelope import ok
from app.core.permissions import require_perm
from app.models import User
from app.schemas.ai import (
    AccountTierTransitionPublic,
    AgentRunPublic,
    AgentTriggerRequest,
    AutopilotCyclePublic,
    AutopilotDiagnosisPublic,
    BurstDetectionPublic,
    DailyCandidatePoolPublic,
    DailyPlanItemPublic,
    DailyPlanPublic,
    DecisionHistoryPublic,
    DiaryApproveRequest,
    DiaryEntryPublic,
    HealingDiagnosisPublic,
    PlaybookPublic,
    ProposalDecideRequest,
    ResearchNotePublic,
    RuleProposalPublic,
    StrategyMemoryPublic,
    StrategyRewardPublic,
    UpgradeProposalPublic,
)
from app.schemas.common import make_pagination
from app.services import ai_service


router = APIRouter()


def _trace(r: Request) -> str:
    return getattr(r.state, "trace_id", "-")


def _list_to_response(items, total, page, size, schema):
    return {
        "items": [schema.model_validate(i).model_dump(mode="json") for i in items],
        "pagination": make_pagination(total, page, size).model_dump(),
    }


# ============================================================
# L9: 候选池 / Plan / Burst / Tier
# ============================================================

@router.get("/candidate-pool")
async def get_candidate_pool(
    request: Request,
    db: DbSession,
    user: User = Depends(require_perm("ai:read")),
    page: int = 1, size: int = 50,
    pool_date: str | None = None, min_score: float | None = None,
    status: str | None = None, keyword: str | None = None,
):
    items, total = ai_service.list_candidate_pool(
        db, user, page=page, size=size, pool_date=pool_date,
        min_score=min_score, status=status, keyword=keyword,
    )
    return ok(
        _list_to_response(items, total, page, size, DailyCandidatePoolPublic),
        trace_id=_trace(request),
    )


@router.get("/daily-plans")
async def get_daily_plans(
    request: Request,
    db: DbSession,
    user: User = Depends(require_perm("ai:read")),
    page: int = 1, size: int = 30, status: str | None = None,
):
    items, total = ai_service.list_daily_plans(
        db, user, page=page, size=size, status=status,
    )
    return ok(
        _list_to_response(items, total, page, size, DailyPlanPublic),
        trace_id=_trace(request),
    )


@router.get("/plan-items")
async def get_plan_items(
    request: Request,
    db: DbSession,
    user: User = Depends(require_perm("ai:read")),
    plan_id: int | None = None,
    account_id: int | None = None,
    status: str | None = None,
    page: int = 1, size: int = 100,
):
    items, total = ai_service.list_plan_items(
        db, user, plan_id=plan_id, account_id=account_id,
        status=status, page=page, size=size,
    )
    return ok(
        _list_to_response(items, total, page, size, DailyPlanItemPublic),
        trace_id=_trace(request),
    )


@router.get("/burst-detections")
async def get_bursts(
    request: Request,
    db: DbSession,
    user: User = Depends(require_perm("ai:read")),
    page: int = 1, size: int = 50, hours: int | None = None,
):
    items, total = ai_service.list_burst_detections(
        db, user, page=page, size=size, hours=hours,
    )
    return ok(
        _list_to_response(items, total, page, size, BurstDetectionPublic),
        trace_id=_trace(request),
    )


@router.get("/tier-transitions")
async def get_tier_transitions(
    request: Request,
    db: DbSession,
    user: User = Depends(require_perm("ai:read")),
    account_id: int | None = None, page: int = 1, size: int = 50,
):
    items, total = ai_service.list_tier_transitions(
        db, user, account_id=account_id, page=page, size=size,
    )
    return ok(
        _list_to_response(items, total, page, size, AccountTierTransitionPublic),
        trace_id=_trace(request),
    )


# ============================================================
# L10: Agent + AutoPilot
# ============================================================

@router.get("/agents")
async def get_agents_status(
    request: Request,
    user: User = Depends(require_perm("ai:read")),
):
    """返回 9 个 agent + 是否可用 (lazy bridge import 状态)."""
    from app.services.ai_bridge import list_available_agents
    return ok(list_available_agents(), trace_id=_trace(request))


@router.get("/agents/{agent_name}/runs")
async def get_agent_runs(
    agent_name: str,
    request: Request,
    db: DbSession,
    user: User = Depends(require_perm("ai:read")),
    status: str | None = None,
    page: int = 1, size: int = 50,
):
    items, total = ai_service.list_agent_runs(
        db, user, agent_name=agent_name, status=status, page=page, size=size,
    )
    return ok(
        _list_to_response(items, total, page, size, AgentRunPublic),
        trace_id=_trace(request),
    )


@router.post("/agents/{agent_name}/trigger")
async def post_trigger_agent(
    agent_name: str,
    data: AgentTriggerRequest,
    request: Request,
    db: DbSession,
    user: User = Depends(require_perm("ai:write")),
):
    run = ai_service.trigger_agent(
        db, user, agent_name=agent_name,
        organization_id=data.organization_id,
        dry_run=data.dry_run,
        note=data.note,
    )
    audit_request(request, db, user=user, action="trigger", module="agent",
                  target_type="agent", target_id=agent_name,
                  detail={"run_id": run.run_id, "dry_run": data.dry_run})
    db.commit()
    db.refresh(run)
    return ok(AgentRunPublic.model_validate(run).model_dump(mode="json"),
              trace_id=_trace(request))


@router.get("/agent-runs")
async def get_all_agent_runs(
    request: Request,
    db: DbSession,
    user: User = Depends(require_perm("ai:read")),
    agent_name: str | None = None,
    status: str | None = None,
    page: int = 1, size: int = 50,
):
    items, total = ai_service.list_agent_runs(
        db, user, agent_name=agent_name, status=status, page=page, size=size,
    )
    return ok(
        _list_to_response(items, total, page, size, AgentRunPublic),
        trace_id=_trace(request),
    )


@router.get("/autopilot/cycles")
async def get_cycles(
    request: Request,
    db: DbSession,
    user: User = Depends(require_perm("ai:read")),
    page: int = 1, size: int = 50, status: str | None = None,
):
    items, total = ai_service.list_autopilot_cycles(
        db, user, page=page, size=size, status=status,
    )
    return ok(
        _list_to_response(items, total, page, size, AutopilotCyclePublic),
        trace_id=_trace(request),
    )


@router.get("/autopilot/diagnoses")
async def get_autopilot_diagnoses(
    request: Request,
    db: DbSession,
    user: User = Depends(require_perm("ai:read")),
    page: int = 1, size: int = 50,
    severity: str | None = None,
    auto_resolved: bool | None = None,
):
    items, total = ai_service.list_autopilot_diagnoses(
        db, user, page=page, size=size,
        severity=severity, auto_resolved=auto_resolved,
    )
    return ok(
        _list_to_response(items, total, page, size, AutopilotDiagnosisPublic),
        trace_id=_trace(request),
    )


# ============================================================
# L11: 记忆
# ============================================================

@router.get("/memory/decision-history")
async def get_decision_history(
    request: Request,
    db: DbSession,
    user: User = Depends(require_perm("ai:read")),
    account_id: int | None = None, verdict: str | None = None,
    page: int = 1, size: int = 50,
):
    items, total = ai_service.list_decision_history(
        db, user, account_id=account_id, verdict=verdict, page=page, size=size,
    )
    return ok(
        _list_to_response(items, total, page, size, DecisionHistoryPublic),
        trace_id=_trace(request),
    )


@router.get("/memory/strategy")
async def get_strategy_memory(
    request: Request,
    db: DbSession,
    user: User = Depends(require_perm("ai:read")),
    account_id: int | None = None, page: int = 1, size: int = 50,
):
    items, total = ai_service.list_strategy_memory(
        db, user, account_id=account_id, page=page, size=size,
    )
    return ok(
        _list_to_response(items, total, page, size, StrategyMemoryPublic),
        trace_id=_trace(request),
    )


@router.get("/memory/diary")
async def get_diary(
    request: Request,
    db: DbSession,
    user: User = Depends(require_perm("ai:read")),
    account_id: int | None = None, approved: bool | None = None,
    page: int = 1, size: int = 50,
):
    items, total = ai_service.list_diary_entries(
        db, user, account_id=account_id, approved=approved, page=page, size=size,
    )
    return ok(
        _list_to_response(items, total, page, size, DiaryEntryPublic),
        trace_id=_trace(request),
    )


@router.put("/memory/diary/{diary_id}/approve")
async def put_approve_diary(
    diary_id: int,
    data: DiaryApproveRequest,
    request: Request,
    db: DbSession,
    user: User = Depends(require_perm("ai:write")),
):
    d = ai_service.approve_diary(db, user, diary_id, data.approved)
    audit_request(request, db, user=user, action="approve", module="diary",
                  target_type="diary", target_id=diary_id,
                  detail={"approved": data.approved, "note": data.note})
    db.commit()
    db.refresh(d)
    return ok(DiaryEntryPublic.model_validate(d).model_dump(mode="json"),
              trace_id=_trace(request))


@router.get("/memory/strategy-rewards")
async def get_strategy_rewards(
    request: Request,
    db: DbSession,
    user: User = Depends(require_perm("ai:read")),
    account_tier: str | None = None, recipe: str | None = None,
    page: int = 1, size: int = 50,
):
    items, total = ai_service.list_strategy_rewards(
        db, user, account_tier=account_tier, recipe=recipe, page=page, size=size,
    )
    return ok(
        _list_to_response(items, total, page, size, StrategyRewardPublic),
        trace_id=_trace(request),
    )


@router.get("/memory/research-notes")
async def get_research_notes(
    request: Request,
    db: DbSession,
    user: User = Depends(require_perm("ai:read")),
    approved: bool | None = None, page: int = 1, size: int = 50,
):
    items, total = ai_service.list_research_notes(
        db, user, approved=approved, page=page, size=size,
    )
    return ok(
        _list_to_response(items, total, page, size, ResearchNotePublic),
        trace_id=_trace(request),
    )


# ============================================================
# L12: 自愈 / 提议
# ============================================================

@router.get("/healing/playbook")
async def get_playbooks(
    request: Request,
    db: DbSession,
    user: User = Depends(require_perm("ai:read")),
    enabled: bool | None = None, page: int = 1, size: int = 100,
):
    items, total = ai_service.list_playbooks(
        db, user, enabled=enabled, page=page, size=size,
    )
    return ok(
        _list_to_response(items, total, page, size, PlaybookPublic),
        trace_id=_trace(request),
    )


@router.get("/healing/diagnoses")
async def get_diagnoses(
    request: Request,
    db: DbSession,
    user: User = Depends(require_perm("ai:read")),
    page: int = 1, size: int = 50,
    severity: str | None = None, auto_resolved: bool | None = None,
):
    items, total = ai_service.list_healing_diagnoses(
        db, user, page=page, size=size,
        severity=severity, auto_resolved=auto_resolved,
    )
    return ok(
        _list_to_response(items, total, page, size, HealingDiagnosisPublic),
        trace_id=_trace(request),
    )


@router.get("/healing/rule-proposals")
async def get_rule_proposals(
    request: Request,
    db: DbSession,
    user: User = Depends(require_perm("ai:read")),
    status: str | None = None, page: int = 1, size: int = 50,
):
    items, total = ai_service.list_rule_proposals(
        db, user, status=status, page=page, size=size,
    )
    return ok(
        _list_to_response(items, total, page, size, RuleProposalPublic),
        trace_id=_trace(request),
    )


@router.put("/healing/rule-proposals/{pid}/decide")
async def put_decide_rule_proposal(
    pid: int,
    data: ProposalDecideRequest,
    request: Request,
    db: DbSession,
    user: User = Depends(require_perm("ai:write")),
):
    p = ai_service.decide_rule_proposal(db, user, pid, data.decision, data.note)
    audit_request(request, db, user=user, action="decide_rule", module="healing",
                  target_type="rule_proposal", target_id=pid,
                  detail={"decision": data.decision})
    db.commit()
    db.refresh(p)
    return ok(RuleProposalPublic.model_validate(p).model_dump(mode="json"),
              trace_id=_trace(request))


@router.get("/healing/upgrade-proposals")
async def get_upgrade_proposals(
    request: Request,
    db: DbSession,
    user: User = Depends(require_perm("ai:read")),
    status: str | None = None, page: int = 1, size: int = 50,
):
    items, total = ai_service.list_upgrade_proposals(
        db, user, status=status, page=page, size=size,
    )
    return ok(
        _list_to_response(items, total, page, size, UpgradeProposalPublic),
        trace_id=_trace(request),
    )


@router.put("/healing/upgrade-proposals/{pid}/decide")
async def put_decide_upgrade_proposal(
    pid: int,
    data: ProposalDecideRequest,
    request: Request,
    db: DbSession,
    user: User = Depends(require_perm("ai:write")),
):
    p = ai_service.decide_upgrade_proposal(db, user, pid, data.decision, data.note)
    audit_request(request, db, user=user, action="decide_upgrade", module="healing",
                  target_type="upgrade_proposal", target_id=pid,
                  detail={"decision": data.decision})
    db.commit()
    db.refresh(p)
    return ok(UpgradeProposalPublic.model_validate(p).model_dump(mode="json"),
              trace_id=_trace(request))
