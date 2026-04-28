"""高转化短剧 API."""
from __future__ import annotations

from fastapi import APIRouter, Depends, Request

from app.core.audit import audit_request
from app.core.deps import DbSession
from app.core.envelope import ok
from app.core.permissions import require_perm
from app.models import User
from app.schemas.common import make_pagination
from app.schemas.content import (
    CollectPoolPublic,
    HighIncomeDramaCreate,
    HighIncomeDramaPublic,
)
from app.services import high_income_service


router = APIRouter()


def _trace(r: Request) -> str:
    return getattr(r.state, "trace_id", "-")


@router.get("")
async def list_high(
    request: Request,
    db: DbSession,
    user: User = Depends(require_perm("high-income:view")),
    page: int = 1, size: int = 50, keyword: str | None = None,
):
    items, total = high_income_service.list_high_income(
        db, user, page=page, size=size, keyword=keyword,
    )
    return ok(
        {
            "items": [HighIncomeDramaPublic.model_validate(h).model_dump(mode="json") for h in items],
            "pagination": make_pagination(total, page, size).model_dump(),
        },
        trace_id=_trace(request),
    )


@router.post("")
async def create_high(
    data: HighIncomeDramaCreate,
    request: Request,
    db: DbSession,
    user: User = Depends(require_perm("high-income:create")),
):
    h = high_income_service.create_high_income(db, user, data)
    audit_request(request, db, user=user, action="create", module="high-income",
                  target_type="high_income", target_id=h.id,
                  detail={"drama_name": h.drama_name, "src": h.source_program})
    db.commit()
    db.refresh(h)
    return ok(HighIncomeDramaPublic.model_validate(h).model_dump(mode="json"),
              trace_id=_trace(request))


@router.delete("/{hid}")
async def delete_high(
    hid: int,
    request: Request,
    db: DbSession,
    user: User = Depends(require_perm("high-income:delete")),
):
    high_income_service.delete_high_income(db, user, hid)
    audit_request(request, db, user=user, action="delete", module="high-income",
                  target_type="high_income", target_id=hid)
    db.commit()
    return ok({"deleted": True}, trace_id=_trace(request))


@router.get("/{hid}/links")
async def get_high_links(
    hid: int,
    request: Request,
    db: DbSession,
    user: User = Depends(require_perm("high-income:view")),
):
    """跳到收藏池查相同 drama_name 的链接."""
    rows = high_income_service.get_high_income_links(db, user, hid)
    return ok(
        [CollectPoolPublic.model_validate(p).model_dump(mode="json") for p in rows],
        trace_id=_trace(request),
    )
