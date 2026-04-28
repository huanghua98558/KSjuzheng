"""审计日志查询 API."""
from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends, Request

from app.core.deps import CurrentUser, DbSession
from app.models import User
from app.core.envelope import ok
from app.core.permissions import require_perm
from app.schemas.audit import AuditLogStats, OperationLogPublic
from app.schemas.common import make_pagination
from app.services import audit_service


router = APIRouter()


def _trace(r: Request) -> str:
    return getattr(r.state, "trace_id", "-")


@router.get("")
async def list_logs(
    request: Request,
    db: DbSession,
    user: User = Depends(require_perm("audit-log:view")),
    page: int = 1,
    size: int = 50,
    user_filter: str | None = None,
    action: str | None = None,
    module: str | None = None,
    start: datetime | None = None,
    end: datetime | None = None,
):
    items, total = audit_service.list_logs(
        db, user, page=page, size=size, user_filter=user_filter,
        action=action, module=module, start=start, end=end,
    )
    return ok(
        {
            "items": [OperationLogPublic.model_validate(it).model_dump(mode="json") for it in items],
            "pagination": make_pagination(total, page, size).model_dump(),
        },
        trace_id=_trace(request),
    )


@router.get("/stats")
async def get_stats(
    request: Request,
    db: DbSession,
    user: User = Depends(require_perm("audit-log:view")),
):
    s = audit_service.stats(db, user)
    return ok(AuditLogStats(**s).model_dump(mode="json"), trace_id=_trace(request))
