"""统计 / Dashboard 聚合 API."""
from __future__ import annotations

from datetime import date

from fastapi import APIRouter, Depends, Request

from app.core.audit import audit_request
from app.core.deps import DbSession
from app.core.envelope import ok
from app.core.permissions import require_perm
from app.models import User
from app.schemas.common import IdListRequest, make_pagination
from app.schemas.content import (
    DramaCollectionPublic,
    DramaLinkStatPublic,
    ExternalUrlPublic,
)
from app.schemas.statistics import (
    StatisticsOverview,
    TodayCard,
)
from app.services import (
    high_income_service,
    statistics_service,
)


router = APIRouter()


def _trace(r: Request) -> str:
    return getattr(r.state, "trace_id", "-")


# ============================================================
# Overview / Today
# ============================================================

@router.get("/overview")
async def get_overview(
    request: Request,
    db: DbSession,
    user: User = Depends(require_perm("dashboard:view")),
):
    o = statistics_service.overview(db, user)
    return ok(StatisticsOverview(**o).model_dump(mode="json"), trace_id=_trace(request))


@router.get("/today-cards")
async def get_today_cards(
    request: Request,
    db: DbSession,
    user: User = Depends(require_perm("dashboard:view")),
):
    o = statistics_service.today_card(db, user)
    return ok(TodayCard(**o).model_dump(mode="json"), trace_id=_trace(request))


# ============================================================
# 执行统计
# ============================================================

@router.get("/executions")
async def get_executions(
    request: Request,
    db: DbSession,
    user: User = Depends(require_perm("dashboard:view")),
    start: date | None = None,
    end: date | None = None,
    uid: str | None = None,
    page: int = 1,
    size: int = 50,
):
    items, total = statistics_service.list_executions(
        db, user, start=start, end=end, uid=uid, page=page, size=size,
    )
    return ok(
        {"items": items, "pagination": make_pagination(total, page, size).model_dump()},
        trace_id=_trace(request),
    )


# ============================================================
# Drama Link 统计
# ============================================================

@router.get("/drama-links")
async def get_drama_links(
    request: Request,
    db: DbSession,
    user: User = Depends(require_perm("drama-statistics:view")),
    page: int = 1,
    size: int = 50,
    keyword: str | None = None,
    sort: str = "execute_count.desc",
):
    items, total = statistics_service.list_drama_link_stats(
        db, user, page=page, size=size, keyword=keyword, sort=sort,
    )
    return ok(
        {
            "items": [
                {
                    **DramaLinkStatPublic.model_validate(it).model_dump(mode="json"),
                    "success_rate": it.success_rate,
                }
                for it in items
            ],
            "pagination": make_pagination(total, page, size).model_dump(),
        },
        trace_id=_trace(request),
    )


@router.post("/drama-links/batch-delete")
async def post_drama_links_batch_delete(
    data: IdListRequest,
    request: Request,
    db: DbSession,
    user: User = Depends(require_perm("drama-statistics:batch-delete")),
):
    result = statistics_service.batch_delete_drama_link_stats(db, user, data.ids)
    audit_request(request, db, user=user, action="batch_delete", module="drama-statistics",
                  detail={"count": len(data.ids), **result})
    db.commit()
    return ok(result, trace_id=_trace(request))


@router.post("/drama-links/clear")
async def post_drama_links_clear(
    request: Request,
    db: DbSession,
    user: User = Depends(require_perm("drama-statistics:clear")),
):
    result = statistics_service.clear_drama_link_stats(db, user)
    audit_request(request, db, user=user, action="clear", module="drama-statistics",
                  detail=result)
    db.commit()
    return ok(result, trace_id=_trace(request))


@router.post("/drama-links/rebuild")
async def post_rebuild(
    request: Request,
    db: DbSession,
    user: User = Depends(require_perm("drama-statistics:clear")),
):
    """手动触发聚合重建. 通常 worker 自动跑."""
    org_id = None if (user.role == "super_admin" or user.is_superadmin) else user.organization_id
    n = statistics_service.rebuild_drama_link_stats(db, organization_id=org_id)
    audit_request(request, db, user=user, action="rebuild", module="drama-statistics",
                  detail={"groups": n, "organization_id": org_id})
    db.commit()
    return ok({"rebuilt_groups": n}, trace_id=_trace(request))


# ============================================================
# 收藏记录 (drama_collection_records)
# ============================================================

@router.get("/drama-collections")
async def get_drama_collections(
    request: Request,
    db: DbSession,
    user: User = Depends(require_perm("drama-collection:view")),
    page: int = 1,
    size: int = 50,
    keyword: str | None = None,
):
    items, total = high_income_service.list_drama_collections(
        db, user, page=page, size=size, keyword=keyword,
    )
    return ok(
        {
            "items": [DramaCollectionPublic.model_validate(it).model_dump(mode="json") for it in items],
            "pagination": make_pagination(total, page, size).model_dump(),
        },
        trace_id=_trace(request),
    )


@router.get("/drama-collections/{account_uid}")
async def get_drama_collection_detail(
    account_uid: str,
    request: Request,
    db: DbSession,
    user: User = Depends(require_perm("drama-collection:view")),
):
    detail = high_income_service.get_drama_collection_detail(db, user, account_uid)
    return ok(detail, trace_id=_trace(request))


# ============================================================
# 外部 URL 统计
# ============================================================

@router.get("/external-urls")
async def get_external_urls(
    request: Request,
    db: DbSession,
    user: User = Depends(require_perm("external-stats:view")),
    page: int = 1,
    size: int = 50,
    keyword: str | None = None,
):
    items, total = high_income_service.list_external_urls(
        db, user, page=page, size=size, keyword=keyword,
    )
    return ok(
        {
            "items": [ExternalUrlPublic.model_validate(it).model_dump(mode="json") for it in items],
            "pagination": make_pagination(total, page, size).model_dump(),
        },
        trace_id=_trace(request),
    )
