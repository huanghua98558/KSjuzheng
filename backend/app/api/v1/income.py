"""收益 API — spark / firefly / fluorescent + archive + 标结."""
from __future__ import annotations

from datetime import date

from fastapi import APIRouter, Depends, Request
from sqlalchemy import text

from app.core.audit import audit_request
from app.core.deps import DbSession
from app.core.envelope import ok
from app.core.permissions import require_perm
from app.models import User
from app.schemas.common import make_pagination
from app.schemas.income import (
    ArchiveListQuery,
    ArchiveStats,
    BatchSettlementRequest,
    IncomeArchivePublic,
    IncomeImportRequest,
    IncomeImportResult,
    IncomeListQuery,
    IncomeRecordPublic,
    IncomeStats,
    SingleSettlementRequest,
)
from app.services import income_service
from app.services import source_mysql_service


router = APIRouter()


def _trace(r: Request) -> str:
    return getattr(r.state, "trace_id", "-")


def _income_row(row, *, program: str) -> dict:
    amount = row.get("total_amount")
    if amount is None:
        amount = row.get("income")
    if amount is None:
        amount = row.get("settlement_amount")
    return {
        "id": row.get("id"),
        "organization_id": row.get("org_id"),
        "member_id": row.get("member_id") or row.get("author_id"),
        "account_id": row.get("account_id"),
        "task_id": row.get("task_id") or row.get("video_id"),
        "task_name": row.get("task_name") or row.get("member_name") or row.get("author_nickname"),
        "income_amount": float(amount or 0),
        "total_amount": float(amount or 0),
        "commission_rate": row.get("commission_rate"),
        "commission_amount": row.get("commission_amount"),
        "settlement_status": row.get("settlement_status") or "pending",
        "program_type": program,
        "created_at": row.get("created_at") or row.get("archived_at"),
        "updated_at": row.get("updated_at") or row.get("archived_at"),
    }


def _source_income(db, user, *, table: str, amount_column: str, program: str, page: int, size: int, keyword: str | None, org_column: str | None = "org_id"):
    where = []
    params = {}
    if org_column and not user.is_superadmin:
        where.append(f"{org_column} = :org_id")
        params["org_id"] = user.organization_id
    if keyword:
        col = "member_name" if table.endswith("_archive") else "task_name"
        where.append(f"{col} LIKE :kw")
        params["kw"] = f"%{keyword}%"
    sql_where = " AND ".join(where) if where else "1=1"
    total = int(db.execute(text(f"SELECT COUNT(*) FROM {table} WHERE {sql_where}"), params).scalar_one())
    rows = db.execute(
        text(f"SELECT * FROM {table} WHERE {sql_where} ORDER BY id DESC LIMIT :limit OFFSET :offset"),
        {**params, "limit": size, "offset": max(page - 1, 0) * size},
    ).mappings().all()
    return [_income_row(dict(row), program=program) for row in rows], total


def _source_income_stats(db, user, *, table: str, amount_column: str, org_column: str | None = "org_id") -> dict:
    where = []
    params = {}
    if org_column and not user.is_superadmin:
        where.append(f"{org_column} = :org_id")
        params["org_id"] = user.organization_id
    sql_where = " AND ".join(where) if where else "1=1"
    row = db.execute(text(f"SELECT COUNT(*) total, COALESCE(SUM({amount_column}), 0) amount FROM {table} WHERE {sql_where}"), params).mappings().one()
    amount = float(row["amount"] or 0)
    return {"total": int(row["total"] or 0), "total_amount": amount, "total_income": amount, "settled_amount": 0, "pending_amount": amount}


# ============================================================
# Spark Income
# ============================================================

@router.get("/spark/income")
async def get_spark_income(
    request: Request,
    db: DbSession,
    user: User = Depends(require_perm("spark:view-detail")),
    page: int = 1, size: int = 50, keyword: str | None = None,
    member_id: int | None = None, account_id: int | None = None,
    settlement_status: str | None = None,
    archived_year_month: str | None = None,
    start: date | None = None, end: date | None = None,
):
    if source_mysql_service.is_source_mysql(db):
        items, total = _source_income(db, user, table="spark_income", amount_column="income", program="spark", page=page, size=size, keyword=keyword)
        return ok({"items": items, "pagination": make_pagination(total, page, size).model_dump()}, trace_id=_trace(request))
    q = IncomeListQuery(
        page=page, size=size, keyword=keyword,
        member_id=member_id, account_id=account_id,
        settlement_status=settlement_status,
        archived_year_month=archived_year_month,
        start=start, end=end,
    )
    items, total = income_service.list_income(db, user, "spark", q)
    return ok(
        {"items": items, "pagination": make_pagination(total, page, size).model_dump()},
        trace_id=_trace(request),
    )


@router.get("/spark/income/stats")
async def get_spark_income_stats(
    request: Request,
    db: DbSession,
    user: User = Depends(require_perm("spark:view-detail")),
):
    if source_mysql_service.is_source_mysql(db):
        return ok(_source_income_stats(db, user, table="spark_income", amount_column="income"), trace_id=_trace(request))
    return ok(
        income_service.income_stats(db, user, "spark"),
        trace_id=_trace(request),
    )


@router.post("/spark/income/import")
async def post_spark_import(
    data: IncomeImportRequest,
    request: Request,
    db: DbSession,
    user: User = Depends(require_perm("spark:import")),
):
    if data.program_type != "spark":
        from app.core.errors import ValidationError
        raise ValidationError("program_type 必须为 spark")
    result = income_service.import_income(db, user, data)
    audit_request(request, db, user=user, action="import", module="spark",
                  detail={"requested": len(data.items), **result})
    db.commit()
    return ok(IncomeImportResult(**result).model_dump(mode="json"),
              trace_id=_trace(request))


# ============================================================
# Firefly Income
# ============================================================

@router.get("/firefly/income")
async def get_firefly_income(
    request: Request,
    db: DbSession,
    user: User = Depends(require_perm("firefly:view-detail")),
    page: int = 1, size: int = 50, keyword: str | None = None,
    member_id: int | None = None, account_id: int | None = None,
    settlement_status: str | None = None,
    archived_year_month: str | None = None,
    start: date | None = None, end: date | None = None,
):
    if source_mysql_service.is_source_mysql(db):
        items, total = _source_income(db, user, table="firefly_income", amount_column="settlement_amount", program="firefly", page=page, size=size, keyword=keyword, org_column=None)
        return ok({"items": items, "pagination": make_pagination(total, page, size).model_dump()}, trace_id=_trace(request))
    q = IncomeListQuery(
        page=page, size=size, keyword=keyword, member_id=member_id,
        account_id=account_id, settlement_status=settlement_status,
        archived_year_month=archived_year_month, start=start, end=end,
    )
    items, total = income_service.list_income(db, user, "firefly", q)
    return ok(
        {"items": items, "pagination": make_pagination(total, page, size).model_dump()},
        trace_id=_trace(request),
    )


@router.get("/firefly/income/stats")
async def get_firefly_income_stats(
    request: Request,
    db: DbSession,
    user: User = Depends(require_perm("firefly:view-detail")),
):
    if source_mysql_service.is_source_mysql(db):
        return ok(_source_income_stats(db, user, table="firefly_income", amount_column="settlement_amount", org_column=None), trace_id=_trace(request))
    return ok(
        income_service.income_stats(db, user, "firefly"),
        trace_id=_trace(request),
    )


@router.post("/firefly/income/import")
async def post_firefly_import(
    data: IncomeImportRequest,
    request: Request,
    db: DbSession,
    user: User = Depends(require_perm("firefly:import")),
):
    if data.program_type != "firefly":
        from app.core.errors import ValidationError
        raise ValidationError("program_type 必须为 firefly")
    result = income_service.import_income(db, user, data)
    audit_request(request, db, user=user, action="import", module="firefly",
                  detail={"requested": len(data.items), **result})
    db.commit()
    return ok(IncomeImportResult(**result).model_dump(mode="json"),
              trace_id=_trace(request))


# ============================================================
# Fluorescent Income
# ============================================================

@router.get("/fluorescent/income")
async def get_fluorescent_income(
    request: Request,
    db: DbSession,
    user: User = Depends(require_perm("fluorescent:view")),
    page: int = 1, size: int = 50, keyword: str | None = None,
    member_id: int | None = None, account_id: int | None = None,
    start: date | None = None, end: date | None = None,
):
    if source_mysql_service.is_source_mysql(db):
        items, total = _source_income(db, user, table="fluorescent_income_archive", amount_column="total_amount", program="fluorescent", page=page, size=size, keyword=keyword)
        return ok({"items": items, "pagination": make_pagination(total, page, size).model_dump()}, trace_id=_trace(request))
    q = IncomeListQuery(
        page=page, size=size, keyword=keyword,
        member_id=member_id, account_id=account_id,
        start=start, end=end,
    )
    items, total = income_service.list_income(db, user, "fluorescent", q)
    return ok(
        {"items": items, "pagination": make_pagination(total, page, size).model_dump()},
        trace_id=_trace(request),
    )


@router.get("/fluorescent/income/stats")
async def get_fluorescent_income_stats(
    request: Request,
    db: DbSession,
    user: User = Depends(require_perm("fluorescent:view")),
):
    if source_mysql_service.is_source_mysql(db):
        return ok(_source_income_stats(db, user, table="fluorescent_income_archive", amount_column="total_amount"), trace_id=_trace(request))
    return ok(
        income_service.income_stats(db, user, "fluorescent"),
        trace_id=_trace(request),
    )


# ============================================================
# Archive (归档 + 标结)
# ============================================================

@router.get("/archive")
async def get_archive(
    request: Request,
    db: DbSession,
    user: User = Depends(require_perm("spark:view-archive")),
    page: int = 1, size: int = 50,
    program_type: str | None = None,
    year: int | None = None, month: int | None = None,
    settlement_status: str | None = None,
):
    q = ArchiveListQuery(
        page=page, size=size, program_type=program_type,
        year=year, month=month, settlement_status=settlement_status,
    )
    items, total = income_service.list_archives(db, user, q)
    return ok(
        {"items": items, "pagination": make_pagination(total, page, size).model_dump()},
        trace_id=_trace(request),
    )


@router.get("/archive/stats")
async def get_archive_stats(
    request: Request,
    db: DbSession,
    user: User = Depends(require_perm("spark:view-archive")),
    program_type: str | None = None,
):
    s = income_service.archive_stats(db, user, program_type)
    return ok(ArchiveStats(**s).model_dump(mode="json"), trace_id=_trace(request))


@router.put("/archive/{archive_id}/settlement")
async def put_archive_settle(
    archive_id: int,
    data: SingleSettlementRequest,
    request: Request,
    db: DbSession,
    user: User = Depends(require_perm("spark:settlement")),
):
    a = income_service.settle_archive(db, user, archive_id, data.remark)
    audit_request(request, db, user=user, action="settlement", module="archive",
                  target_type="archive", target_id=archive_id, detail={"remark": data.remark})
    db.commit()
    db.refresh(a)
    return ok(IncomeArchivePublic.model_validate(a).model_dump(mode="json"),
              trace_id=_trace(request))


@router.post("/archive/batch-settlement")
async def post_archive_batch_settle(
    data: BatchSettlementRequest,
    request: Request,
    db: DbSession,
    user: User = Depends(require_perm("spark:batch-settlement")),
):
    result = income_service.batch_settle(db, user, data)
    audit_request(request, db, user=user, action="batch_settlement", module="archive",
                  detail={"count": len(data.archive_ids), **result})
    db.commit()
    return ok(result, trace_id=_trace(request))
