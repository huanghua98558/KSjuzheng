"""用户管理 API."""
from __future__ import annotations

from fastapi import APIRouter, Depends, Request

from app.core.audit import audit_request
from app.core.deps import CurrentUser, DbSession
from app.models import User
from app.core.envelope import ok
from app.core.permissions import require_perm
from app.schemas.common import make_pagination
from app.schemas.user import (
    UserCommissionUpdate,
    UserCommissionVisibility,
    UserCreate,
    UserDetail,
    UserPasswordReset,
    UserPermissionsUpdate,
    UserPermissionsView,
    UserRoleUpdate,
    UserStatusUpdate,
    UserUpdate,
)
from app.services import user_service


router = APIRouter()


def _trace(r: Request) -> str:
    return getattr(r.state, "trace_id", "-")


@router.get("")
async def list_users(
    request: Request,
    db: DbSession,
    user: User = Depends(require_perm("user:view")),
    page: int = 1,
    size: int = 20,
    keyword: str | None = None,
    role: str | None = None,
    is_active: bool | None = None,
    parent_id: int | None = None,
):
    items, total = user_service.list_users(
        db, user, page=page, size=size, keyword=keyword,
        role=role, status=is_active, parent_id=parent_id,
    )
    return ok(
        {
            "items": [UserDetail.model_validate(u).model_dump(mode="json") for u in items],
            "pagination": make_pagination(total, page, size).model_dump(),
        },
        trace_id=_trace(request),
    )


@router.get("/me")
async def get_me_alias(request: Request, user: CurrentUser):
    """/users/me 别名 - 兼容前端旧调用,等价于 /auth/me."""
    return ok(
        UserDetail.model_validate(user).model_dump(mode="json"),
        trace_id=_trace(request),
    )


@router.get("/{user_id}")
async def get_user(
    user_id: int,
    request: Request,
    db: DbSession,
    user: User = Depends(require_perm("user:view")),
):
    u = user_service.get_user(db, user, user_id)
    return ok(UserDetail.model_validate(u).model_dump(mode="json"), trace_id=_trace(request))


@router.post("")
async def post_user(
    data: UserCreate,
    request: Request,
    db: DbSession,
    user: User = Depends(require_perm("user:create")),
):
    u = user_service.create_user(db, user, data)
    audit_request(
        request, db, user=user, action="create", module="user",
        target_type="user", target_id=u.id,
        detail={"username": u.username, "role": u.role},
    )
    db.commit()
    db.refresh(u)
    return ok(UserDetail.model_validate(u).model_dump(mode="json"), trace_id=_trace(request))


@router.put("/{user_id}")
async def put_user(
    user_id: int,
    data: UserUpdate,
    request: Request,
    db: DbSession,
    user: User = Depends(require_perm("user:edit")),
):
    u = user_service.update_user(db, user, user_id, data)
    audit_request(request, db, user=user, action="update", module="user",
                  target_type="user", target_id=user_id,
                  detail=data.model_dump(exclude_unset=True))
    db.commit()
    db.refresh(u)
    return ok(UserDetail.model_validate(u).model_dump(mode="json"), trace_id=_trace(request))


@router.put("/{user_id}/status")
async def put_user_status(
    user_id: int,
    data: UserStatusUpdate,
    request: Request,
    db: DbSession,
    user: User = Depends(require_perm("user:edit")),
):
    u = user_service.update_user_status(db, user, user_id, data.is_active)
    audit_request(request, db, user=user, action="status_change", module="user",
                  target_type="user", target_id=user_id, detail={"is_active": data.is_active})
    db.commit()
    db.refresh(u)
    return ok(UserDetail.model_validate(u).model_dump(mode="json"), trace_id=_trace(request))


@router.post("/{user_id}/reset-password")
async def post_reset_password(
    user_id: int,
    data: UserPasswordReset,
    request: Request,
    db: DbSession,
    user: User = Depends(require_perm("user:reset-password")),
):
    user_service.reset_password(db, user, user_id, data.new_password)
    audit_request(request, db, user=user, action="reset_password", module="user",
                  target_type="user", target_id=user_id)
    db.commit()
    return ok({"reset": True}, trace_id=_trace(request))


@router.put("/{user_id}/role")
async def put_user_role(
    user_id: int,
    data: UserRoleUpdate,
    request: Request,
    db: DbSession,
    user: User = Depends(require_perm("user:set-role")),
):
    u = user_service.update_role(db, user, user_id, data.role)
    audit_request(request, db, user=user, action="change_role", module="user",
                  target_type="user", target_id=user_id, detail={"new_role": data.role})
    db.commit()
    db.refresh(u)
    return ok(UserDetail.model_validate(u).model_dump(mode="json"), trace_id=_trace(request))


@router.put("/{user_id}/commission-rate")
async def put_commission_rate(
    user_id: int,
    data: UserCommissionUpdate,
    request: Request,
    db: DbSession,
    user: User = Depends(require_perm("user:set-commission")),
):
    u = user_service.update_commission(db, user, user_id, data.commission_rate)
    audit_request(request, db, user=user, action="change_commission", module="user",
                  target_type="user", target_id=user_id, detail={"rate": data.commission_rate})
    db.commit()
    db.refresh(u)
    return ok(UserDetail.model_validate(u).model_dump(mode="json"), trace_id=_trace(request))


@router.put("/{user_id}/commission-visibility")
async def put_commission_visibility(
    user_id: int,
    data: UserCommissionVisibility,
    request: Request,
    db: DbSession,
    user: User = Depends(require_perm("user:set-commission-visibility")),
):
    u = user_service.update_commission_visibility(
        db, user, user_id, **data.model_dump(exclude_unset=True)
    )
    audit_request(request, db, user=user, action="change_visibility", module="user",
                  target_type="user", target_id=user_id,
                  detail=data.model_dump(exclude_unset=True))
    db.commit()
    db.refresh(u)
    return ok(UserDetail.model_validate(u).model_dump(mode="json"), trace_id=_trace(request))


@router.get("/{user_id}/permissions")
async def get_user_permissions(
    user_id: int,
    request: Request,
    db: DbSession,
    user: User = Depends(require_perm("user:view")),
):
    view = user_service.get_user_permissions_view(db, user, user_id)
    return ok(UserPermissionsView(**view).model_dump(mode="json"), trace_id=_trace(request))


@router.put("/{user_id}/permissions")
async def put_user_permissions(
    user_id: int,
    data: UserPermissionsUpdate,
    request: Request,
    db: DbSession,
    user: User = Depends(require_perm("user:set-permissions")),
):
    user_service.update_user_permissions(db, user, user_id, data)
    audit_request(request, db, user=user, action="set_permissions", module="user",
                  target_type="user", target_id=user_id, detail=data.model_dump())
    db.commit()
    return ok({"updated": True}, trace_id=_trace(request))
