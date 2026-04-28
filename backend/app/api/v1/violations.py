"""违规作品 API."""
from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends, Request

from app.core.audit import audit_request
from app.core.deps import DbSession
from app.core.envelope import ok
from app.core.permissions import require_perm
from app.models import User
from app.schemas.common import make_pagination
from app.schemas.member import (
    ViolationListQuery,
    ViolationPhotoPublic,
    ViolationUpdate,
)
from app.services import member_service


router = APIRouter()


def _trace(r: Request) -> str:
    return getattr(r.state, "trace_id", "-")


@router.get("")
async def list_violations(
    request: Request,
    db: DbSession,
    user: User = Depends(require_perm("violation:view")),
    page: int = 1, size: int = 50, keyword: str | None = None,
    business_type: str | None = None, appeal_status: str | None = None,
    start: datetime | None = None, end: datetime | None = None,
):
    q = ViolationListQuery(
        page=page, size=size, keyword=keyword,
        business_type=business_type, appeal_status=appeal_status,
        start=start, end=end,
    )
    items, total = member_service.list_violations(db, user, q)
    return ok(
        {
            "items": [ViolationPhotoPublic.model_validate(v).model_dump(mode="json") for v in items],
            "pagination": make_pagination(total, page, size).model_dump(),
        },
        trace_id=_trace(request),
    )


@router.put("/{vid}")
async def put_violation(
    vid: int,
    data: ViolationUpdate,
    request: Request,
    db: DbSession,
    user: User = Depends(require_perm("violation:edit")),
):
    v = member_service.update_violation(db, user, vid, data)
    audit_request(request, db, user=user, action="update", module="violation",
                  target_type="violation", target_id=vid,
                  detail=data.model_dump(exclude_unset=True))
    db.commit()
    db.refresh(v)
    return ok(ViolationPhotoPublic.model_validate(v).model_dump(mode="json"),
              trace_id=_trace(request))


@router.delete("/{vid}")
async def delete_violation(
    vid: int,
    request: Request,
    db: DbSession,
    user: User = Depends(require_perm("violation:delete")),
):
    member_service.delete_violation(db, user, vid)
    audit_request(request, db, user=user, action="delete", module="violation",
                  target_type="violation", target_id=vid)
    db.commit()
    return ok({"deleted": True}, trace_id=_trace(request))
