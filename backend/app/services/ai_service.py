"""Phase 3 AI 服务层 — 列表查询 + 简单 CRUD + agent 触发.

后端只做"调度 + 元数据存档", 真实 agent / ffmpeg 在客户端 (ks_automation/core).
触发 = 写一条 agent_run 记录 + (可选) 调用 lazy bridge 把任务排到客户端拉取队列.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy import desc, func, or_, select
from sqlalchemy.orm import Session

from app.core.errors import (
    AUTH_403,
    AuthError,
    BizError,
    ConflictError,
    ResourceNotFound,
    VALIDATION_422,
)
from app.core.tenant_scope import (
    TenantScope,
    apply_to_account_query,
    compute_tenant_scope,
)
from app.models import (
    AccountDecisionHistory,
    AccountDiaryEntry,
    AccountStrategyMemory,
    AccountTierTransition,
    AgentRun,
    AutopilotCycle,
    AutopilotDiagnosis,
    BurstDetection,
    DailyCandidatePool,
    DailyPlan,
    DailyPlanItem,
    HealingDiagnosis,
    HealingPlaybook,
    ResearchNote,
    RuleProposal,
    StrategyReward,
    UpgradeProposal,
    User,
)


_now = lambda: datetime.now(timezone.utc)  # noqa: E731


# ============================================================
# helper
# ============================================================

def _scope_filter(stmt, scope: TenantScope, model, optional: bool = False):
    """org_id 在 scope 内 (或 NULL 时 optional)."""
    if scope.unrestricted:
        return stmt
    if optional:
        return stmt.where(
            or_(
                model.organization_id.in_(scope.organization_ids),
                model.organization_id.is_(None),
            )
        )
    return stmt.where(model.organization_id.in_(scope.organization_ids))


def _paginate(stmt, page: int, size: int, db: Session):
    total = db.execute(select(func.count()).select_from(stmt.subquery())).scalar_one()
    items = db.execute(stmt.offset((page - 1) * size).limit(size)).scalars().all()
    return items, total


# ============================================================
# L9: 候选池 / Daily Plan / Burst / Tier
# ============================================================

def list_candidate_pool(
    db: Session, user: User,
    *, page: int = 1, size: int = 50,
    pool_date: str | None = None,
    min_score: float | None = None,
    status: str | None = None,
    keyword: str | None = None,
):
    scope = compute_tenant_scope(db, user)
    stmt = select(DailyCandidatePool)
    stmt = _scope_filter(stmt, scope, DailyCandidatePool)
    if pool_date:
        stmt = stmt.where(DailyCandidatePool.pool_date == pool_date)
    if min_score is not None:
        stmt = stmt.where(DailyCandidatePool.composite_score >= min_score)
    if status:
        stmt = stmt.where(DailyCandidatePool.status == status)
    if keyword:
        stmt = stmt.where(DailyCandidatePool.drama_name.like(f"%{keyword}%"))
    stmt = stmt.order_by(
        DailyCandidatePool.pool_date.desc(),
        DailyCandidatePool.composite_score.desc(),
    )
    return _paginate(stmt, page, size, db)


def list_daily_plans(
    db: Session, user: User,
    *, page: int = 1, size: int = 30, status: str | None = None,
):
    scope = compute_tenant_scope(db, user)
    stmt = select(DailyPlan)
    stmt = _scope_filter(stmt, scope, DailyPlan)
    if status:
        stmt = stmt.where(DailyPlan.status == status)
    stmt = stmt.order_by(DailyPlan.plan_date.desc())
    return _paginate(stmt, page, size, db)


def list_plan_items(
    db: Session, user: User,
    *, plan_id: int | None = None,
    account_id: int | None = None,
    status: str | None = None,
    page: int = 1, size: int = 100,
):
    scope = compute_tenant_scope(db, user)
    stmt = select(DailyPlanItem)
    stmt = _scope_filter(stmt, scope, DailyPlanItem)
    if plan_id is not None:
        stmt = stmt.where(DailyPlanItem.plan_id == plan_id)
    if account_id is not None:
        stmt = stmt.where(DailyPlanItem.account_id == account_id)
    if status:
        stmt = stmt.where(DailyPlanItem.status == status)
    stmt = stmt.order_by(DailyPlanItem.id.desc())
    return _paginate(stmt, page, size, db)


def list_burst_detections(
    db: Session, user: User,
    *, page: int = 1, size: int = 50, hours: int | None = None,
):
    scope = compute_tenant_scope(db, user)
    stmt = select(BurstDetection)
    stmt = _scope_filter(stmt, scope, BurstDetection)
    if hours:
        cutoff = _now() - timedelta(hours=hours)
        stmt = stmt.where(BurstDetection.detected_at >= cutoff)
    stmt = stmt.order_by(BurstDetection.detected_at.desc())
    return _paginate(stmt, page, size, db)


def list_tier_transitions(
    db: Session, user: User,
    *, account_id: int | None = None, page: int = 1, size: int = 50,
):
    scope = compute_tenant_scope(db, user)
    stmt = select(AccountTierTransition)
    stmt = _scope_filter(stmt, scope, AccountTierTransition)
    if account_id is not None:
        stmt = stmt.where(AccountTierTransition.account_id == account_id)
    stmt = stmt.order_by(AccountTierTransition.transitioned_at.desc())
    return _paginate(stmt, page, size, db)


# ============================================================
# L10: Agent / AutoPilot
# ============================================================

def list_agent_runs(
    db: Session, user: User,
    *, agent_name: str | None = None, status: str | None = None,
    page: int = 1, size: int = 50,
):
    scope = compute_tenant_scope(db, user)
    stmt = select(AgentRun)
    stmt = _scope_filter(stmt, scope, AgentRun, optional=True)
    if agent_name:
        stmt = stmt.where(AgentRun.agent_name == agent_name)
    if status:
        stmt = stmt.where(AgentRun.status == status)
    stmt = stmt.order_by(AgentRun.id.desc())
    return _paginate(stmt, page, size, db)


def trigger_agent(
    db: Session, user: User,
    *, agent_name: str,
    organization_id: int | None = None,
    dry_run: bool = True,
    note: str | None = None,
) -> AgentRun:
    """记录一次手动触发. 真实跑放 worker / 后台 thread.

    Phase 3 后端: 写 agent_run + 后台 lazy bridge 调 ks_automation.core.agents.<name>.run().
    """
    scope = compute_tenant_scope(db, user)
    if organization_id is None:
        organization_id = user.organization_id
    if not scope.unrestricted and organization_id not in scope.organization_ids:
        raise AuthError(AUTH_403, message="不在您的可见机构")

    run_id = uuid.uuid4().hex
    run = AgentRun(
        run_id=run_id,
        agent_name=agent_name,
        organization_id=organization_id,
        trigger_type="manual",
        triggered_by_user_id=user.id,
        started_at=_now(),
        status="running",
        input_json='{"dry_run": %s, "note": "%s"}' % (
            "true" if dry_run else "false",
            (note or "").replace('"', "'"),
        ),
    )
    db.add(run)
    db.flush()

    # lazy bridge: 后台调 ks_automation.core.agents.<name>.run()
    try:
        from app.services.ai_bridge import dispatch_agent_async
        dispatch_agent_async(run.id, agent_name, organization_id, dry_run)
    except ImportError:
        pass  # bridge 不可用 (test / 缺依赖) → 仍返 running, agent_run.status 由 Phase 3 后续完善

    return run


def list_autopilot_cycles(
    db: Session, user: User,
    *, page: int = 1, size: int = 50, status: str | None = None,
):
    scope = compute_tenant_scope(db, user)
    stmt = select(AutopilotCycle)
    stmt = _scope_filter(stmt, scope, AutopilotCycle, optional=True)
    if status:
        stmt = stmt.where(AutopilotCycle.status == status)
    stmt = stmt.order_by(AutopilotCycle.cycle_id.desc())
    return _paginate(stmt, page, size, db)


def list_autopilot_diagnoses(
    db: Session, user: User,
    *, page: int = 1, size: int = 50,
    severity: str | None = None,
    auto_resolved: bool | None = None,
):
    scope = compute_tenant_scope(db, user)
    stmt = select(AutopilotDiagnosis)
    stmt = _scope_filter(stmt, scope, AutopilotDiagnosis, optional=True)
    if severity:
        stmt = stmt.where(AutopilotDiagnosis.severity == severity)
    if auto_resolved is not None:
        stmt = stmt.where(AutopilotDiagnosis.auto_resolved.is_(auto_resolved))
    stmt = stmt.order_by(AutopilotDiagnosis.id.desc())
    return _paginate(stmt, page, size, db)


# ============================================================
# L11: 记忆
# ============================================================

def list_decision_history(
    db: Session, user: User,
    *, account_id: int | None = None,
    verdict: str | None = None,
    page: int = 1, size: int = 50,
):
    scope = compute_tenant_scope(db, user)
    stmt = select(AccountDecisionHistory)
    stmt = _scope_filter(stmt, scope, AccountDecisionHistory)
    if account_id is not None:
        stmt = stmt.where(AccountDecisionHistory.account_id == account_id)
    if verdict:
        stmt = stmt.where(AccountDecisionHistory.verdict == verdict)
    stmt = stmt.order_by(AccountDecisionHistory.id.desc())
    return _paginate(stmt, page, size, db)


def list_strategy_memory(
    db: Session, user: User, *, account_id: int | None = None, page: int = 1, size: int = 50,
):
    scope = compute_tenant_scope(db, user)
    stmt = select(AccountStrategyMemory)
    stmt = _scope_filter(stmt, scope, AccountStrategyMemory)
    if account_id is not None:
        stmt = stmt.where(AccountStrategyMemory.account_id == account_id)
    stmt = stmt.order_by(AccountStrategyMemory.id.desc())
    return _paginate(stmt, page, size, db)


def list_diary_entries(
    db: Session, user: User,
    *, account_id: int | None = None, approved: bool | None = None,
    page: int = 1, size: int = 50,
):
    scope = compute_tenant_scope(db, user)
    stmt = select(AccountDiaryEntry)
    stmt = _scope_filter(stmt, scope, AccountDiaryEntry)
    if account_id is not None:
        stmt = stmt.where(AccountDiaryEntry.account_id == account_id)
    if approved is not None:
        stmt = stmt.where(AccountDiaryEntry.approved.is_(approved))
    stmt = stmt.order_by(AccountDiaryEntry.id.desc())
    return _paginate(stmt, page, size, db)


def approve_diary(db: Session, user: User, diary_id: int, approved: bool) -> AccountDiaryEntry:
    scope = compute_tenant_scope(db, user)
    d = db.get(AccountDiaryEntry, diary_id)
    if not d:
        raise ResourceNotFound("周记不存在")
    if not scope.unrestricted and d.organization_id not in scope.organization_ids:
        raise AuthError(AUTH_403, message="不在您的范围")
    d.approved = approved
    d.approved_by_user_id = user.id
    d.approved_at = _now() if approved else None
    db.flush()
    return d


def list_strategy_rewards(
    db: Session, user: User,
    *, account_tier: str | None = None,
    recipe: str | None = None,
    page: int = 1, size: int = 50,
):
    scope = compute_tenant_scope(db, user)
    stmt = select(StrategyReward)
    stmt = _scope_filter(stmt, scope, StrategyReward)
    if account_tier:
        stmt = stmt.where(StrategyReward.account_tier == account_tier)
    if recipe:
        stmt = stmt.where(StrategyReward.recipe == recipe)
    # MySQL does not support "NULLS LAST"; this keeps the same ordering portably.
    stmt = stmt.order_by(StrategyReward.avg_reward.is_(None).asc(), StrategyReward.avg_reward.desc())
    return _paginate(stmt, page, size, db)


def list_research_notes(
    db: Session, user: User, *, approved: bool | None = None, page: int = 1, size: int = 50,
):
    scope = compute_tenant_scope(db, user)
    stmt = select(ResearchNote)
    stmt = _scope_filter(stmt, scope, ResearchNote, optional=True)
    if approved is not None:
        stmt = stmt.where(ResearchNote.approved.is_(approved))
    stmt = stmt.order_by(ResearchNote.id.desc())
    return _paginate(stmt, page, size, db)


# ============================================================
# L12: 自愈 / playbook / 提议
# ============================================================

def list_playbooks(db: Session, user: User, *, enabled: bool | None = None,
                   page: int = 1, size: int = 100):
    stmt = select(HealingPlaybook)
    if enabled is not None:
        stmt = stmt.where(HealingPlaybook.enabled.is_(enabled))
    stmt = stmt.order_by(HealingPlaybook.id.asc())
    return _paginate(stmt, page, size, db)


def list_healing_diagnoses(
    db: Session, user: User,
    *, page: int = 1, size: int = 50,
    severity: str | None = None,
    auto_resolved: bool | None = None,
):
    scope = compute_tenant_scope(db, user)
    stmt = select(HealingDiagnosis)
    stmt = _scope_filter(stmt, scope, HealingDiagnosis, optional=True)
    if severity:
        stmt = stmt.where(HealingDiagnosis.severity == severity)
    if auto_resolved is not None:
        stmt = stmt.where(HealingDiagnosis.auto_resolved.is_(auto_resolved))
    stmt = stmt.order_by(HealingDiagnosis.id.desc())
    return _paginate(stmt, page, size, db)


def list_rule_proposals(db: Session, user: User, *, status: str | None = None,
                        page: int = 1, size: int = 50):
    scope = compute_tenant_scope(db, user)
    stmt = select(RuleProposal)
    stmt = _scope_filter(stmt, scope, RuleProposal, optional=True)
    if status:
        stmt = stmt.where(RuleProposal.status == status)
    stmt = stmt.order_by(RuleProposal.id.desc())
    return _paginate(stmt, page, size, db)


def decide_rule_proposal(
    db: Session, user: User, pid: int, decision: str, note: str | None = None,
) -> RuleProposal:
    p = db.get(RuleProposal, pid)
    if not p:
        raise ResourceNotFound("提议不存在")
    if p.status != "pending":
        raise ConflictError(f"提议已是 {p.status} 状态")
    if decision not in ("approved", "rejected"):
        raise BizError(VALIDATION_422, message="decision 仅允许 approved/rejected")
    p.status = decision
    p.decided_by_user_id = user.id
    p.decided_at = _now()
    if decision == "approved":
        # 写到 healing_playbook
        existing = db.execute(
            select(HealingPlaybook).where(HealingPlaybook.code == p.proposed_code)
        ).scalar_one_or_none()
        if existing:
            existing.symptom_pattern = p.symptom_pattern
            existing.remedy_action = p.remedy_action
            existing.params_json = p.params_json
            existing.proposed_by = "llm"
            existing.enabled = True
            p.target_playbook_id = existing.id
        else:
            new = HealingPlaybook(
                code=p.proposed_code,
                description=p.rationale,
                symptom_pattern=p.symptom_pattern,
                remedy_action=p.remedy_action,
                params_json=p.params_json,
                confidence=p.llm_confidence or 0.5,
                enabled=True,
                proposed_by="llm",
            )
            db.add(new)
            db.flush()
            p.target_playbook_id = new.id
        p.applied_at = _now()
    db.flush()
    return p


def list_upgrade_proposals(db: Session, user: User, *, status: str | None = None,
                           page: int = 1, size: int = 50):
    stmt = select(UpgradeProposal)
    if status:
        stmt = stmt.where(UpgradeProposal.status == status)
    stmt = stmt.order_by(UpgradeProposal.id.desc())
    return _paginate(stmt, page, size, db)


def decide_upgrade_proposal(
    db: Session, user: User, pid: int, decision: str, note: str | None = None,
) -> UpgradeProposal:
    p = db.get(UpgradeProposal, pid)
    if not p:
        raise ResourceNotFound("升级提议不存在")
    if p.status != "pending":
        raise ConflictError(f"提议已是 {p.status} 状态")
    p.status = decision
    p.decided_by_user_id = user.id
    p.decided_at = _now()
    if decision == "approved":
        # 应用到 playbook
        pb = db.execute(
            select(HealingPlaybook).where(HealingPlaybook.code == p.target_playbook_code)
        ).scalar_one_or_none()
        if pb:
            if p.suggestion_type == "refine_pattern" and p.suggested_pattern:
                pb.symptom_pattern = p.suggested_pattern
            elif p.suggestion_type == "change_action" and p.suggested_action:
                pb.remedy_action = p.suggested_action
            elif p.suggestion_type == "adjust_params" and p.suggested_params_json:
                pb.params_json = p.suggested_params_json
            elif p.suggestion_type == "deprecate":
                pb.enabled = False
    db.flush()
    return p
