"""成员 API — org/spark/firefly/fluorescent + member-query."""
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
from app.schemas.member import (
    FireflyMemberPublic,
    FluorescentMemberPublic,
    MemberQueryRequest,
    MemberQueryResponse,
    MemberQueryRow,
    OrgMemberPublic,
    SparkMemberPublic,
)
from app.services import member_service
from app.services import source_mysql_service


router = APIRouter()


def _trace(r: Request) -> str:
    return getattr(r.state, "trace_id", "-")


def _member_dict(row, *, program: str) -> dict:
    return {
        "id": row["id"] if "id" in row else row["member_id"],
        "organization_id": row["org_id"],
        "member_id": row["member_id"],
        "account_id": None,
        "nickname": row["member_name"],
        "avatar": row["member_head"] if "member_head" in row else None,
        "fans_count": row["fans_count"] or 0,
        "broker_name": row["broker_name"],
        "total_amount": float(row["total_amount"] or 0),
        "org_task_num": row["org_task_num"] or 0,
        "task_count": row["org_task_num"] or 0,
        "hidden": False,
        "in_limit": bool(row["in_limit"]) if "in_limit" in row else False,
        "program_type": program,
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
    }


def _source_members(db, user, *, table: str, program: str, page: int, size: int, keyword: str | None):
    where = []
    params = {}
    if not user.is_superadmin:
        where.append("org_id = :org_id")
        params["org_id"] = user.organization_id
    if keyword:
        where.append("(CAST(member_id AS CHAR) LIKE :kw OR member_name LIKE :kw)")
        params["kw"] = f"%{keyword}%"
    sql_where = " AND ".join(where) if where else "1=1"
    total = int(db.execute(text(f"SELECT COUNT(*) FROM {table} WHERE {sql_where}"), params).scalar_one())
    order_col = "id" if table == "spark_members" else "member_id"
    rows = db.execute(
        text(f"SELECT * FROM {table} WHERE {sql_where} ORDER BY total_amount DESC, {order_col} DESC LIMIT :limit OFFSET :offset"),
        {**params, "limit": size, "offset": max(page - 1, 0) * size},
    ).mappings().all()
    return [_member_dict(row, program=program) for row in rows], total


# ============================================================
# OrgMember
# ============================================================

@router.get("/org-members")
async def list_org_members(
    request: Request,
    db: DbSession,
    user: User = Depends(require_perm("org-member:view")),
    page: int = 1, size: int = 50, keyword: str | None = None,
    renewal_status: str | None = None, cooperation_type: str | None = None,
):
    items, total = member_service.list_org_members(
        db, user, page=page, size=size, keyword=keyword,
        renewal_status=renewal_status, cooperation_type=cooperation_type,
    )
    return ok(
        {
            "items": [OrgMemberPublic.model_validate(it).model_dump(mode="json") for it in items],
            "pagination": make_pagination(total, page, size).model_dump(),
        },
        trace_id=_trace(request),
    )


# ============================================================
# Spark
# ============================================================

@router.get("/spark/members")
async def list_spark_members(
    request: Request,
    db: DbSession,
    user: User = Depends(require_perm("spark:view-monthly")),
    page: int = 1, size: int = 50, keyword: str | None = None,
):
    if source_mysql_service.is_source_mysql(db):
        items, total = _source_members(db, user, table="spark_members", program="spark", page=page, size=size, keyword=keyword)
        return ok({"items": items, "pagination": make_pagination(total, page, size).model_dump()}, trace_id=_trace(request))
    items, total = member_service.list_spark_members(
        db, user, page=page, size=size, keyword=keyword,
    )
    return ok(
        {
            "items": [SparkMemberPublic.model_validate(it).model_dump(mode="json") for it in items],
            "pagination": make_pagination(total, page, size).model_dump(),
        },
        trace_id=_trace(request),
    )


# ============================================================
# Firefly
# ============================================================

@router.get("/firefly/members")
async def list_firefly_members(
    request: Request,
    db: DbSession,
    user: User = Depends(require_perm("firefly:view-monthly")),
    page: int = 1, size: int = 50, keyword: str | None = None,
):
    if source_mysql_service.is_source_mysql(db):
        items, total = _source_members(db, user, table="fluorescent_members", program="firefly", page=page, size=size, keyword=keyword)
        return ok({"items": items, "pagination": make_pagination(total, page, size).model_dump()}, trace_id=_trace(request))
    items, total = member_service.list_firefly_members(
        db, user, page=page, size=size, keyword=keyword,
    )
    return ok(
        {
            "items": [FireflyMemberPublic.model_validate(it).model_dump(mode="json") for it in items],
            "pagination": make_pagination(total, page, size).model_dump(),
        },
        trace_id=_trace(request),
    )


# ============================================================
# Fluorescent
# ============================================================

@router.get("/fluorescent/members")
async def list_fluorescent_members(
    request: Request,
    db: DbSession,
    user: User = Depends(require_perm("fluorescent:view")),
    page: int = 1, size: int = 50, keyword: str | None = None,
):
    if source_mysql_service.is_source_mysql(db):
        items, total = _source_members(db, user, table="fluorescent_members", program="fluorescent", page=page, size=size, keyword=keyword)
        return ok({"items": items, "pagination": make_pagination(total, page, size).model_dump()}, trace_id=_trace(request))
    items, total = member_service.list_fluorescent_members(
        db, user, page=page, size=size, keyword=keyword,
    )
    return ok(
        {
            "items": [
                FluorescentMemberPublic.model_validate(it).model_dump(mode="json")
                for it in items
            ],
            "pagination": make_pagination(total, page, size).model_dump(),
        },
        trace_id=_trace(request),
    )


# ============================================================
# ★ Member Query (高敏: UID 必须全部在 scope, 整批拒)
# ============================================================

@router.post("/member-query")
async def post_member_query(
    data: MemberQueryRequest,
    request: Request,
    db: DbSession,
    user: User = Depends(require_perm("member-query:execute")),
):
    """按 UID 列表查收益. 严格白名单, 部分越权 → 整批 403."""
    result = member_service.member_query(db, user, data)
    audit_request(
        request, db, user=user, action="execute", module="member-query",
        detail={
            "uid_count": len(data.uids),
            "program": data.program_type,
            "first_uid": data.uids[0] if data.uids else None,
        },
    )
    db.commit()

    rows_models = [
        MemberQueryRow(**r).model_dump(mode="json") for r in result["items"]
    ]
    return ok(
        {"items": rows_models, "summary": result["summary"]},
        trace_id=_trace(request),
    )
