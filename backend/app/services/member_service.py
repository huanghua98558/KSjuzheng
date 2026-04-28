"""成员管理 + member-query 强隔离白名单."""
from __future__ import annotations

from datetime import date, datetime, timezone

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.core.errors import AUTH_403, AuthError, ResourceNotFound
from app.core.tenant_scope import (
    TenantScope,
    apply_to_account_query,
    compute_tenant_scope,
    validate_uids_in_scope,
)
from app.models import (
    Account,
    FireflyIncome,
    FireflyMember,
    FluorescentIncome,
    FluorescentMember,
    OrgMember,
    SparkIncome,
    SparkMember,
    User,
    ViolationPhoto,
)
from app.schemas.member import (
    MemberQueryRequest,
    ViolationListQuery,
    ViolationUpdate,
)


# ============================================================
# OrgMember
# ============================================================

def _scope_filter(stmt, scope: TenantScope, model):
    if scope.unrestricted:
        return stmt
    return stmt.where(model.organization_id.in_(scope.organization_ids))


def list_org_members(
    db: Session, user: User,
    *, page: int = 1, size: int = 50, keyword: str | None = None,
    renewal_status: str | None = None, cooperation_type: str | None = None,
):
    scope = compute_tenant_scope(db, user)
    stmt = select(OrgMember)
    stmt = _scope_filter(stmt, scope, OrgMember)
    if keyword:
        like = f"%{keyword}%"
        stmt = stmt.where(
            or_(
                OrgMember.nickname.like(like),
                OrgMember.broker_name.like(like),
            )
        )
    if renewal_status:
        stmt = stmt.where(OrgMember.renewal_status == renewal_status)
    if cooperation_type:
        stmt = stmt.where(OrgMember.cooperation_type == cooperation_type)

    total = db.execute(select(func.count()).select_from(stmt.subquery())).scalar_one()
    stmt = stmt.order_by(OrgMember.id.desc()).offset((page - 1) * size).limit(size)
    items = db.execute(stmt).scalars().all()
    return items, total


def list_spark_members(
    db: Session, user: User,
    *, page: int = 1, size: int = 50, keyword: str | None = None,
):
    scope = compute_tenant_scope(db, user)
    stmt = select(SparkMember)
    stmt = _scope_filter(stmt, scope, SparkMember)
    if keyword:
        like = f"%{keyword}%"
        stmt = stmt.where(
            or_(SparkMember.nickname.like(like), SparkMember.broker_name.like(like))
        )
    total = db.execute(select(func.count()).select_from(stmt.subquery())).scalar_one()
    stmt = stmt.order_by(SparkMember.id.desc()).offset((page - 1) * size).limit(size)
    items = db.execute(stmt).scalars().all()
    return items, total


def list_firefly_members(
    db: Session, user: User,
    *, page: int = 1, size: int = 50, keyword: str | None = None,
):
    scope = compute_tenant_scope(db, user)
    stmt = select(FireflyMember)
    stmt = _scope_filter(stmt, scope, FireflyMember)
    if keyword:
        like = f"%{keyword}%"
        stmt = stmt.where(
            or_(FireflyMember.nickname.like(like), FireflyMember.broker_name.like(like))
        )
    total = db.execute(select(func.count()).select_from(stmt.subquery())).scalar_one()
    stmt = stmt.order_by(FireflyMember.total_amount.desc()).offset((page - 1) * size).limit(size)
    items = db.execute(stmt).scalars().all()
    return items, total


def list_fluorescent_members(
    db: Session, user: User,
    *, page: int = 1, size: int = 50, keyword: str | None = None,
):
    scope = compute_tenant_scope(db, user)
    stmt = select(FluorescentMember)
    stmt = _scope_filter(stmt, scope, FluorescentMember)
    if keyword:
        like = f"%{keyword}%"
        stmt = stmt.where(
            or_(FluorescentMember.nickname.like(like),
                FluorescentMember.broker_name.like(like))
        )
    total = db.execute(select(func.count()).select_from(stmt.subquery())).scalar_one()
    stmt = stmt.order_by(FluorescentMember.total_amount.desc()).offset((page - 1) * size).limit(size)
    items = db.execute(stmt).scalars().all()
    return items, total


# ============================================================
# Member-Query (★ 严格 UID 白名单)
# ============================================================

def member_query(
    db: Session, user: User, req: MemberQueryRequest
) -> dict:
    """按 UID 列表查收益, 严格白名单.

    1. 解析 scope + 查 scope 内全部账号 UID
    2. requested - scope_uids = invalid → 整批 403
    3. 仅查 (requested ∩ scope_uids)
    """
    scope = compute_tenant_scope(db, user)

    # 校验 UID 都在 scope (整批拒)
    validate_uids_in_scope(db, scope, user, req.uids)

    # 现 UID → account_id, member_id 映射
    accounts = db.execute(
        select(Account.id, Account.real_uid, Account.nickname)
        .where(Account.real_uid.in_(req.uids))
        .where(Account.deleted_at.is_(None))
    ).all()
    uid_to_acc = {a.real_uid: a for a in accounts}

    # 在每个 program 表查 member_id
    rows: list[dict] = []
    summary = {"total_income": 0.0, "total_tasks": 0, "uid_count": len(req.uids)}

    program_models = []
    if req.program_type in ("all", "spark"):
        program_models.append(("spark", SparkIncome, "income_amount", SparkMember))
    if req.program_type in ("all", "firefly"):
        program_models.append(("firefly", FireflyIncome, "income_amount", FireflyMember))
    if req.program_type in ("all", "fluorescent"):
        program_models.append(("fluorescent", FluorescentIncome, "income_amount", FluorescentMember))

    for prog, inc_model, amount_field, mem_model in program_models:
        # 这里用账号→member_id (account_id 关联)
        for uid, acc in uid_to_acc.items():
            mem = db.execute(
                select(mem_model).where(mem_model.account_id == acc.id)
                .limit(1)
            ).scalar_one_or_none()
            if not mem:
                continue
            inc_q = (
                select(
                    func.coalesce(func.sum(getattr(inc_model, amount_field)), 0.0).label("amt"),
                    func.count().label("cnt"),
                    func.max(getattr(inc_model, "income_date", None)).label("last"),
                )
                .where(inc_model.member_id == mem.member_id)
            )
            if req.start:
                if hasattr(inc_model, "income_date"):
                    inc_q = inc_q.where(inc_model.income_date >= req.start)
            if req.end:
                if hasattr(inc_model, "income_date"):
                    inc_q = inc_q.where(inc_model.income_date <= req.end)
            r = db.execute(inc_q).one()
            amt = float(r.amt or 0)
            cnt = int(r.cnt or 0)
            rows.append({
                "uid": uid,
                "nickname": mem.nickname or acc.nickname,
                "fans_count": getattr(mem, "fans_count", 0),
                "program_type": prog,
                "total_income": amt,
                "total_tasks": cnt,
                "last_income_date": r.last,
            })
            summary["total_income"] += amt
            summary["total_tasks"] += cnt

    return {"items": rows, "summary": summary}


# ============================================================
# Violation
# ============================================================

def list_violations(
    db: Session, user: User, q: ViolationListQuery,
):
    scope = compute_tenant_scope(db, user)
    stmt = select(ViolationPhoto)
    stmt = _scope_filter(stmt, scope, ViolationPhoto)
    if q.keyword:
        like = f"%{q.keyword}%"
        stmt = stmt.where(
            or_(ViolationPhoto.uid.like(like), ViolationPhoto.work_id.like(like))
        )
    if q.business_type:
        stmt = stmt.where(ViolationPhoto.business_type == q.business_type)
    if q.appeal_status:
        stmt = stmt.where(ViolationPhoto.appeal_status == q.appeal_status)
    if q.start:
        stmt = stmt.where(ViolationPhoto.published_at >= q.start)
    if q.end:
        stmt = stmt.where(ViolationPhoto.published_at <= q.end)

    total = db.execute(select(func.count()).select_from(stmt.subquery())).scalar_one()
    stmt = (
        stmt.order_by(ViolationPhoto.published_at.desc())
        .offset((q.page - 1) * q.size).limit(q.size)
    )
    items = db.execute(stmt).scalars().all()
    return items, total


def update_violation(
    db: Session, user: User, vid: int, data: ViolationUpdate
) -> ViolationPhoto:
    scope = compute_tenant_scope(db, user)
    v = db.get(ViolationPhoto, vid)
    if not v:
        raise ResourceNotFound("违规记录不存在")
    if not scope.unrestricted and v.organization_id not in scope.organization_ids:
        raise AuthError(AUTH_403, message="不在您的可见范围")
    for k, val in data.model_dump(exclude_unset=True).items():
        setattr(v, k, val)
    db.flush()
    return v


def delete_violation(db: Session, user: User, vid: int) -> None:
    scope = compute_tenant_scope(db, user)
    v = db.get(ViolationPhoto, vid)
    if not v:
        raise ResourceNotFound("违规记录不存在")
    if not scope.unrestricted and v.organization_id not in scope.organization_ids:
        raise AuthError(AUTH_403, message="不在您的可见范围")
    db.delete(v)
    db.flush()
