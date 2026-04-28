"""公告 API."""
from __future__ import annotations

from fastapi import APIRouter, Depends, Request

from app.core.audit import audit_request
from app.core.deps import CurrentUser, DbSession
from app.core.envelope import ok
from app.core.permissions import require_perm
from app.models import User
from app.schemas.common import make_pagination
from app.schemas.settings import (
    AnnouncementCreate,
    AnnouncementPublic,
    AnnouncementUpdate,
)
from app.services import settings_service


router = APIRouter()


def _trace(r: Request) -> str:
    return getattr(r.state, "trace_id", "-")


@router.get("")
async def list_announcements(
    request: Request,
    db: DbSession,
    user: User = Depends(require_perm("announcement:view")),
    page: int = 1,
    size: int = 50,
):
    items, total = settings_service.list_announcements(
        db, user, page=page, size=size, active_only=False,
    )
    return ok(
        {
            "items": [AnnouncementPublic.model_validate(a).model_dump(mode="json") for a in items],
            "pagination": make_pagination(total, page, size).model_dump(),
        },
        trace_id=_trace(request),
    )


@router.get("/active")
async def list_active(
    request: Request,
    db: DbSession,
    user: CurrentUser,
):
    """所有登录用户都看自己的有效公告 (不需 announcement:view, 默认开)."""
    items = settings_service.list_active(db, user)
    return ok(
        [AnnouncementPublic.model_validate(a).model_dump(mode="json") for a in items],
        trace_id=_trace(request),
    )


@router.post("")
async def post_announcement(
    data: AnnouncementCreate,
    request: Request,
    db: DbSession,
    user: User = Depends(require_perm("announcement:create")),
):
    a = settings_service.create_announcement(db, user, data)
    audit_request(request, db, user=user, action="create", module="announcement",
                  target_type="announcement", target_id=a.id,
                  detail={"title": a.title, "level": a.level, "org": a.organization_id})
    db.commit()
    db.refresh(a)
    return ok(AnnouncementPublic.model_validate(a).model_dump(mode="json"),
              trace_id=_trace(request))


@router.put("/{aid}")
async def put_announcement(
    aid: int,
    data: AnnouncementUpdate,
    request: Request,
    db: DbSession,
    user: User = Depends(require_perm("announcement:edit")),
):
    a = settings_service.update_announcement(db, user, aid, data)
    audit_request(request, db, user=user, action="update", module="announcement",
                  target_type="announcement", target_id=aid,
                  detail=data.model_dump(exclude_unset=True))
    db.commit()
    db.refresh(a)
    return ok(AnnouncementPublic.model_validate(a).model_dump(mode="json"),
              trace_id=_trace(request))


@router.delete("/{aid}")
async def delete_announcement(
    aid: int,
    request: Request,
    db: DbSession,
    user: User = Depends(require_perm("announcement:delete")),
):
    settings_service.delete_announcement(db, user, aid)
    audit_request(request, db, user=user, action="delete", module="announcement",
                  target_type="announcement", target_id=aid)
    db.commit()
    return ok({"deleted": True}, trace_id=_trace(request))
