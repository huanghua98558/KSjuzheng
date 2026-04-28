"""收益管理 — 萤光 / 星火 / 荧光 + 归档 + 标结 + Excel 导入.

设计:
  - 三种 program 共享同一套 list / stats / import / settle 逻辑, 仅模型不同
  - 字段脱敏由 service 层统一调 income_masking.mask_income_record
  - 标结 = 把 income_archives.settlement_status='settled' + 写 settlement_records
"""
from __future__ import annotations

from datetime import date, datetime, timezone
from typing import Type

from sqlalchemy import and_, func, or_, select
from sqlalchemy.orm import Session

from app.core.errors import AUTH_403, AuthError, ResourceNotFound
from app.core.tenant_scope import TenantScope, compute_tenant_scope
from app.models import (
    Account,
    FireflyIncome,
    FluorescentIncome,
    IncomeArchive,
    SettlementRecord,
    SparkIncome,
    User,
)
from app.schemas.income import (
    ArchiveListQuery,
    BatchSettlementRequest,
    IncomeImportRequest,
    IncomeListQuery,
    SingleSettlementRequest,
)
from app.services.income_masking import mask_income_record


_now = lambda: datetime.now(timezone.utc)  # noqa: E731


PROGRAM_MODEL = {
    "spark": SparkIncome,
    "firefly": FireflyIncome,
    "fluorescent": FluorescentIncome,
}


# ============================================================
# 通用过滤
# ============================================================

def _apply_scope(stmt, scope: TenantScope, user: User, model):
    """对 income 表加 scope: 普通用户仅 own account."""
    if scope.unrestricted:
        return stmt
    stmt = stmt.where(model.organization_id.in_(scope.organization_ids))
    if scope.account_filter == "self_only":
        sub = select(Account.id).where(Account.assigned_user_id == user.id)
        stmt = stmt.where(model.account_id.in_(sub))
    elif user.role == "captain":
        sub = select(Account.id).where(Account.assigned_user_id.in_(scope.user_ids))
        stmt = stmt.where(model.account_id.in_(sub))
    return stmt


def _model_for(program: str):
    m = PROGRAM_MODEL.get(program)
    if not m:
        raise ResourceNotFound(f"未知收益类型: {program}")
    return m


# ============================================================
# 列表 + 脱敏
# ============================================================

def list_income(
    db: Session, user: User, program: str, q: IncomeListQuery
) -> tuple[list[dict], int]:
    model = _model_for(program)
    scope = compute_tenant_scope(db, user)

    stmt = select(model)
    stmt = _apply_scope(stmt, scope, user, model)

    if q.keyword:
        like = f"%{q.keyword}%"
        stmt = stmt.where(
            or_(model.task_name.like(like), model.task_id.like(like))
        )
    if q.member_id is not None:
        stmt = stmt.where(model.member_id == q.member_id)
    if q.account_id is not None:
        stmt = stmt.where(model.account_id == q.account_id)
    if q.settlement_status and program != "fluorescent":
        stmt = stmt.where(model.settlement_status == q.settlement_status)
    if q.archived_year_month and program != "fluorescent":
        stmt = stmt.where(model.archived_year_month == q.archived_year_month)
    if q.start:
        date_field = "income_date" if hasattr(model, "income_date") else "start_date"
        stmt = stmt.where(getattr(model, date_field) >= q.start)
    if q.end:
        date_field = "income_date" if hasattr(model, "income_date") else "start_date"
        stmt = stmt.where(getattr(model, date_field) <= q.end)

    total = db.execute(select(func.count()).select_from(stmt.subquery())).scalar_one()
    stmt = stmt.order_by(model.id.desc()).offset((q.page - 1) * q.size).limit(q.size)
    rows = db.execute(stmt).scalars().all()

    # 脱敏
    out = []
    for r in rows:
        d = {
            "id": r.id,
            "organization_id": r.organization_id,
            "program_type": program,
            "member_id": r.member_id,
            "account_id": r.account_id,
            "task_id": r.task_id,
            "task_name": r.task_name,
            "income_amount": r.income_amount,
            "commission_rate": getattr(r, "commission_rate", None),
            "commission_amount": getattr(r, "commission_amount", None),
            "income_date": (
                getattr(r, "income_date", None) or getattr(r, "start_date", None)
            ),
            "settlement_status": getattr(r, "settlement_status", None),
            "archived_year_month": getattr(r, "archived_year_month", None),
            "created_at": r.created_at,
        }
        out.append(mask_income_record(d, user))
    return out, total


# ============================================================
# 统计
# ============================================================

def income_stats(db: Session, user: User, program: str) -> dict:
    model = _model_for(program)
    scope = compute_tenant_scope(db, user)
    base = select(model)
    base = _apply_scope(base, scope, user, model)

    sub = base.subquery()
    total_amount_q = select(func.coalesce(func.sum(sub.c.income_amount), 0.0))
    total_amount = float(db.execute(total_amount_q).scalar_one() or 0)
    record_count = db.execute(select(func.count()).select_from(sub)).scalar_one()

    settled_amount = 0.0
    pending_amount = 0.0
    if program != "fluorescent":
        settled_amount = float(db.execute(
            select(func.coalesce(func.sum(sub.c.income_amount), 0.0))
            .select_from(sub).where(sub.c.settlement_status == "settled")
        ).scalar_one() or 0)
        pending_amount = total_amount - settled_amount

    member_count = db.execute(
        select(func.count(func.distinct(sub.c.member_id))).select_from(sub)
    ).scalar_one()

    # by month
    by_month_stmt = (
        select(
            func.strftime("%Y-%m", sub.c.created_at).label("ym"),
            func.coalesce(func.sum(sub.c.income_amount), 0.0).label("amt"),
            func.count().label("cnt"),
        )
        .group_by("ym")
        .order_by("ym")
    )
    by_month = [
        {"ym": r.ym, "amount": float(r.amt or 0), "count": int(r.cnt or 0)}
        for r in db.execute(by_month_stmt).all()
        if r.ym
    ]

    out = {
        "total_amount": total_amount,
        "settled_amount": settled_amount,
        "pending_amount": pending_amount,
        "record_count": record_count or 0,
        "member_count": member_count or 0,
        "by_month": by_month,
    }
    return mask_income_record(out, user)


# ============================================================
# Excel 导入
# ============================================================

def import_income(
    db: Session, user: User, data: IncomeImportRequest
) -> dict:
    model = _model_for(data.program_type)
    org_id = user.organization_id

    inserted = 0
    skipped = 0
    errors: list[str] = []

    for idx, item in enumerate(data.items):
        try:
            kwargs = dict(
                organization_id=org_id,
                member_id=item.member_id,
                task_id=item.task_id,
                task_name=item.task_name,
                income_amount=item.income_amount,
            )
            if data.program_type in ("spark", "firefly"):
                kwargs["commission_rate"] = item.commission_rate
                kwargs["commission_amount"] = item.commission_amount
                kwargs["archived_year_month"] = item.archived_year_month
                kwargs["settlement_status"] = "pending"
                if data.program_type == "spark":
                    kwargs["start_date"] = item.income_date
                else:
                    kwargs["income_date"] = item.income_date
            else:  # fluorescent
                kwargs["income_date"] = item.income_date

            db.add(model(**kwargs))
            inserted += 1
        except Exception as ex:
            skipped += 1
            errors.append(f"row {idx + 1}: {type(ex).__name__}: {ex}")

    db.flush()
    return {"inserted": inserted, "skipped": skipped, "errors": errors[:20]}


# ============================================================
# 归档
# ============================================================

def list_archives(
    db: Session, user: User, q: ArchiveListQuery
) -> tuple[list[dict], int]:
    scope = compute_tenant_scope(db, user)
    stmt = select(IncomeArchive)
    if not scope.unrestricted:
        stmt = stmt.where(IncomeArchive.organization_id.in_(scope.organization_ids))
    if q.program_type:
        stmt = stmt.where(IncomeArchive.program_type == q.program_type)
    if q.year is not None:
        stmt = stmt.where(IncomeArchive.year == q.year)
    if q.month is not None:
        stmt = stmt.where(IncomeArchive.month == q.month)
    if q.settlement_status:
        stmt = stmt.where(IncomeArchive.settlement_status == q.settlement_status)

    total = db.execute(select(func.count()).select_from(stmt.subquery())).scalar_one()
    stmt = (
        stmt.order_by(IncomeArchive.year.desc(), IncomeArchive.month.desc())
        .offset((q.page - 1) * q.size).limit(q.size)
    )
    rows = db.execute(stmt).scalars().all()
    out = []
    for r in rows:
        d = {
            "id": r.id,
            "organization_id": r.organization_id,
            "program_type": r.program_type,
            "year": r.year,
            "month": r.month,
            "member_id": r.member_id,
            "account_id": r.account_id,
            "total_amount": r.total_amount,
            "commission_rate": r.commission_rate,
            "commission_amount": r.commission_amount,
            "settlement_status": r.settlement_status,
            "archived_at": r.archived_at,
        }
        out.append(mask_income_record(d, user))
    return out, total


def archive_stats(db: Session, user: User, program: str | None = None) -> dict:
    scope = compute_tenant_scope(db, user)
    base = select(IncomeArchive)
    if not scope.unrestricted:
        base = base.where(IncomeArchive.organization_id.in_(scope.organization_ids))
    if program:
        base = base.where(IncomeArchive.program_type == program)

    sub = base.subquery()
    total_count = db.execute(select(func.count()).select_from(sub)).scalar_one()
    settled_count = db.execute(
        select(func.count()).select_from(sub).where(sub.c.settlement_status == "settled")
    ).scalar_one()
    pending_count = total_count - settled_count
    total_amount = float(db.execute(
        select(func.coalesce(func.sum(sub.c.total_amount), 0.0)).select_from(sub)
    ).scalar_one() or 0)
    settled_amount = float(db.execute(
        select(func.coalesce(func.sum(sub.c.total_amount), 0.0))
        .select_from(sub).where(sub.c.settlement_status == "settled")
    ).scalar_one() or 0)
    return {
        "total_count": total_count,
        "settled_count": settled_count,
        "pending_count": pending_count,
        "total_amount": total_amount,
        "settled_amount": settled_amount,
    }


# ============================================================
# 标结
# ============================================================

def settle_archive(
    db: Session, user: User, archive_id: int, remark: str | None = None
) -> IncomeArchive:
    scope = compute_tenant_scope(db, user)
    a = db.get(IncomeArchive, archive_id)
    if not a:
        raise ResourceNotFound("归档条目不存在")
    if not scope.unrestricted and a.organization_id not in scope.organization_ids:
        raise AuthError(AUTH_403, message="不在您的可见范围")

    a.settlement_status = "settled"
    a.archived_at = a.archived_at or _now()
    db.add(SettlementRecord(
        archive_id=a.id,
        settled_by_user_id=user.id,
        settled_at=_now(),
        status="settled",
        remark=remark,
    ))
    db.flush()
    return a


def batch_settle(
    db: Session, user: User, data: BatchSettlementRequest
) -> dict:
    scope = compute_tenant_scope(db, user)

    # 校验范围 (整批拒)
    if not scope.unrestricted:
        in_scope = set(db.execute(
            select(IncomeArchive.id)
            .where(IncomeArchive.id.in_(data.archive_ids))
            .where(IncomeArchive.organization_id.in_(scope.organization_ids))
        ).scalars().all())
        invalid = set(data.archive_ids) - in_scope
        if invalid:
            raise AuthError(
                AUTH_403,
                message=f"部分归档不在您的范围 ({len(invalid)} 条)",
            )

    affected = 0
    now = _now()
    for aid in data.archive_ids:
        a = db.get(IncomeArchive, aid)
        if a and a.settlement_status != "settled":
            a.settlement_status = "settled"
            a.archived_at = a.archived_at or now
            db.add(SettlementRecord(
                archive_id=a.id,
                settled_by_user_id=user.id,
                settled_at=now,
                status="settled",
                remark=data.remark,
            ))
            affected += 1
    db.flush()
    return {"settled_count": affected, "skipped_count": len(data.archive_ids) - affected}
