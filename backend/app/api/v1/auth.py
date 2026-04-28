"""认证端点: /api/client/auth/*."""
from __future__ import annotations

from fastapi import APIRouter, Request

from app.core.deps import CurrentUser, DbSession
from app.core.envelope import ok
from app.schemas.auth import (
    ActivateRequest,
    ActivateResponse,
    HeartbeatRequest,
    HeartbeatResponse,
    LoginRequest,
    LoginResponse,
    RefreshRequest,
    RefreshResponse,
    UserPublic,
)
from app.services import auth_service


router = APIRouter()


def _trace(request: Request) -> str:
    return getattr(request.state, "trace_id", "-")


def _client_ip(request: Request) -> str | None:
    if request.client:
        return request.client.host
    return None


@router.post("/login")
async def post_login(req: LoginRequest, request: Request, db: DbSession):
    """密码登录 (用户名 / 手机号).

    返 access + refresh.
    """
    user, access, refresh, refresh_exp = auth_service.login(
        db,
        username=req.username,
        phone=req.phone,
        password=req.password,
        fingerprint=req.fingerprint,
        user_agent=request.headers.get("user-agent"),
        ip=_client_ip(request),
    )

    plan_tier = None
    from app.services.auth_service import _find_active_license_for_user
    license = _find_active_license_for_user(db, user.id)
    if license:
        plan_tier = license.plan_tier

    payload = LoginResponse(
        token=access,
        refresh_token=refresh,
        expires_at=refresh_exp,
        user=UserPublic(
            id=user.id,
            username=user.username,
            organization_id=user.organization_id,
            display_name=user.display_name,
            phone=user.phone,
            is_superadmin=user.is_superadmin,
            must_change_pw=user.must_change_pw,
            role="admin" if user.is_superadmin else "operator",
        ),
        plan_tier=plan_tier,
    ).model_dump(mode="json")

    return ok(payload, trace_id=_trace(request))


@router.post("/activate")
async def post_activate(req: ActivateRequest, request: Request, db: DbSession):
    """卡密首次激活."""
    user, license, access, refresh, refresh_exp, initial_pw = auth_service.activate(
        db,
        license_key=req.license_key,
        phone=req.phone,
        fingerprint=req.fingerprint,
        client_version=req.client_version,
        os_info=req.os_info,
        user_agent=request.headers.get("user-agent"),
        ip=_client_ip(request),
    )

    payload = ActivateResponse(
        token=access,
        refresh_token=refresh,
        expires_at=refresh_exp,
        user=UserPublic(
            id=user.id,
            username=user.username,
            organization_id=user.organization_id,
            display_name=user.display_name,
            phone=user.phone,
            is_superadmin=user.is_superadmin,
            must_change_pw=user.must_change_pw,
            role="admin" if user.is_superadmin else "operator",
        ),
        plan_tier=license.plan_tier,
        license_expires_at=license.expires_at,
        initial_password=initial_pw,
    ).model_dump(mode="json")

    return ok(payload, trace_id=_trace(request))


@router.post("/refresh")
async def post_refresh(req: RefreshRequest, request: Request, db: DbSession):
    """用 refresh_token 换新 access (滚动续期, 老 refresh 作废)."""
    new_access, new_refresh, refresh_exp = auth_service.refresh(
        db,
        refresh_token=req.refresh_token,
        fingerprint=req.fingerprint,
    )
    payload = RefreshResponse(
        token=new_access,
        refresh_token=new_refresh,
        expires_at=refresh_exp,
    ).model_dump(mode="json")
    return ok(payload, trace_id=_trace(request))


@router.post("/heartbeat")
async def post_heartbeat(
    req: HeartbeatRequest,
    request: Request,
    db: DbSession,
    user: CurrentUser,
):
    """每 5min 心跳, 校验 license + 返服务器时间."""
    info = auth_service.heartbeat(db, user=user, fingerprint=req.fingerprint)
    from datetime import datetime, timezone, timedelta
    payload = HeartbeatResponse(
        server_time=datetime.now(timezone(timedelta(hours=8))),
        server_version="0.1.0",
        license_status=info["license_status"],
        expires_at=info["expires_at"],
        days_left=info["days_left"],
    ).model_dump(mode="json")
    return ok(payload, trace_id=_trace(request))


@router.get("/me")
async def get_me(request: Request, user: CurrentUser):
    """当前登录用户资料."""
    payload = UserPublic(
        id=user.id,
        username=user.username,
        organization_id=user.organization_id,
        display_name=user.display_name,
        phone=user.phone,
        is_superadmin=user.is_superadmin,
        must_change_pw=user.must_change_pw,
        role="admin" if user.is_superadmin else "operator",
    ).model_dump(mode="json")
    return ok(payload, trace_id=_trace(request))


@router.post("/logout")
async def post_logout(request: Request, user: CurrentUser, db: DbSession):
    """登出 — 把当前用户所有 session 标 revoked. 下次 refresh 即失败."""
    from sqlalchemy import update
    from app.models import UserSession
    db.execute(
        update(UserSession)
        .where(UserSession.user_id == user.id)
        .where(UserSession.revoked.is_(False))
        .values(revoked=True)
    )
    db.commit()
    return ok({"logged_out": True}, trace_id=_trace(request))
