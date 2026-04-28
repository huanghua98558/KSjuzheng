"""短剧收藏池 API."""
from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends, Request

from app.core.audit import audit_request
from app.core.deps import DbSession
from app.core.envelope import ok
from app.core.permissions import require_perm
from app.models import User
from app.schemas.common import IdListRequest, make_pagination
from app.schemas.content import (
    CollectPoolBatchImport,
    CollectPoolCreate,
    CollectPoolDeduplicateAndCopy,
    CollectPoolListQuery,
    CollectPoolPublic,
    CollectPoolUpdate,
)
from app.services import collect_pool_service


router = APIRouter()


def _trace(r: Request) -> str:
    return getattr(r.state, "trace_id", "-")


@router.get("")
async def list_pool(
    request: Request,
    db: DbSession,
    user: User = Depends(require_perm("collect-pool:view")),
    page: int = 1,
    size: int = 50,
    keyword: str | None = None,
    platform: str | None = None,
    auth_code: str | None = None,
    status: str | None = None,
    abnormal: str | None = None,
    start: datetime | None = None,
    end: datetime | None = None,
):
    q = CollectPoolListQuery(
        page=page, size=size, keyword=keyword, platform=platform,
        auth_code=auth_code, status=status, abnormal=abnormal,
        start=start, end=end,
    )
    items, total = collect_pool_service.list_pool(db, user, q)
    return ok(
        {
            "items": [CollectPoolPublic.model_validate(p).model_dump(mode="json") for p in items],
            "pagination": make_pagination(total, page, size).model_dump(),
        },
        trace_id=_trace(request),
    )


@router.post("")
async def post_pool(
    data: CollectPoolCreate,
    request: Request,
    db: DbSession,
    user: User = Depends(require_perm("collect-pool:create")),
):
    p = collect_pool_service.create_one(db, user, data)
    audit_request(request, db, user=user, action="create", module="collect-pool",
                  target_type="collect_pool", target_id=p.id,
                  detail={"drama_name": p.drama_name, "url": p.drama_url[:100]})
    db.commit()
    db.refresh(p)
    return ok(CollectPoolPublic.model_validate(p).model_dump(mode="json"),
              trace_id=_trace(request))


@router.put("/{pool_id}")
async def put_pool(
    pool_id: int,
    data: CollectPoolUpdate,
    request: Request,
    db: DbSession,
    user: User = Depends(require_perm("collect-pool:edit")),
):
    p = collect_pool_service.update_one(db, user, pool_id, data)
    audit_request(request, db, user=user, action="update", module="collect-pool",
                  target_type="collect_pool", target_id=pool_id,
                  detail=data.model_dump(exclude_unset=True))
    db.commit()
    db.refresh(p)
    return ok(CollectPoolPublic.model_validate(p).model_dump(mode="json"),
              trace_id=_trace(request))


@router.delete("/{pool_id}")
async def delete_pool(
    pool_id: int,
    request: Request,
    db: DbSession,
    user: User = Depends(require_perm("collect-pool:batch-delete")),
):
    collect_pool_service.delete_one(db, user, pool_id)
    audit_request(request, db, user=user, action="delete", module="collect-pool",
                  target_type="collect_pool", target_id=pool_id)
    db.commit()
    return ok({"deleted": True}, trace_id=_trace(request))


@router.post("/batch-import")
async def post_batch_import(
    data: CollectPoolBatchImport,
    request: Request,
    db: DbSession,
    user: User = Depends(require_perm("collect-pool:batch-import")),
):
    result = collect_pool_service.batch_import(db, user, data)
    audit_request(request, db, user=user, action="batch_import", module="collect-pool",
                  detail={"requested": len(data.items), **result})
    db.commit()
    return ok(result, trace_id=_trace(request))


@router.post("/deduplicate-and-copy")
async def post_dedup(
    data: CollectPoolDeduplicateAndCopy,
    request: Request,
    db: DbSession,
    user: User = Depends(require_perm("collect-pool:deduplicate")),
):
    result = collect_pool_service.deduplicate_and_copy(
        db, user,
        source_auth_code=data.source_auth_code,
        target_auth_code=data.target_auth_code,
        keep_source=data.keep_source,
    )
    audit_request(request, db, user=user, action="deduplicate", module="collect-pool",
                  detail={"src": data.source_auth_code, "tgt": data.target_auth_code, **result})
    db.commit()
    return ok(result, trace_id=_trace(request))


@router.post("/refresh-status")
async def post_refresh(
    data: IdListRequest | None = None,
    *,
    request: Request,
    db: DbSession,
    user: User = Depends(require_perm("collect-pool:refresh-status")),
):
    ids = data.ids if data else None
    result = collect_pool_service.refresh_status(db, user, ids)
    audit_request(request, db, user=user, action="refresh_status", module="collect-pool",
                  detail=result)
    db.commit()
    return ok(result, trace_id=_trace(request))


@router.post("/batch-delete")
async def post_batch_delete(
    data: IdListRequest,
    request: Request,
    db: DbSession,
    user: User = Depends(require_perm("collect-pool:batch-delete")),
):
    result = collect_pool_service.batch_delete(db, user, data.ids)
    audit_request(request, db, user=user, action="batch_delete", module="collect-pool",
                  detail={"count": len(data.ids), **result})
    db.commit()
    return ok(result, trace_id=_trace(request))
