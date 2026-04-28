"""系统配置 API — basic / role-defaults / about."""
from __future__ import annotations

from fastapi import APIRouter, Depends, Request

from app.core.audit import audit_request
from app.core.deps import CurrentUser, DbSession
from app.core.envelope import ok
from app.core.permissions import require_perm
from app.models import User
from app.schemas.settings import (
    AboutInfo,
    RoleDefaultsListResponse,
    RoleDefaultsUpdate,
    SettingsBasic,
)
from app.services import settings_service


router = APIRouter()


def _trace(r: Request) -> str:
    return getattr(r.state, "trace_id", "-")


@router.get("/basic")
async def get_basic(
    request: Request,
    user: User = Depends(require_perm("settings:view-basic")),
):
    info = settings_service.get_basic()
    return ok(SettingsBasic(**info).model_dump(mode="json"), trace_id=_trace(request))


@router.get("/about")
async def get_about(
    request: Request,
    user: CurrentUser,
):
    """所有登录用户可看 (无 require_perm)."""
    info = settings_service.get_about()
    return ok(AboutInfo(**info).model_dump(mode="json"), trace_id=_trace(request))


@router.get("/role-defaults")
async def get_role_defaults(
    request: Request,
    db: DbSession,
    user: User = Depends(require_perm("settings:view-role-defaults")),
):
    info = settings_service.list_role_defaults(db)
    return ok(RoleDefaultsListResponse(**info).model_dump(mode="json"),
              trace_id=_trace(request))


@router.put("/role-defaults")
async def put_role_defaults(
    data: RoleDefaultsUpdate,
    request: Request,
    db: DbSession,
    user: User = Depends(require_perm("settings:edit-role-defaults")),
):
    result = settings_service.update_role_defaults(db, data)
    audit_request(request, db, user=user, action="update", module="settings",
                  target_type="role_defaults", target_id=data.role, detail=result)
    db.commit()
    return ok(result, trace_id=_trace(request))
