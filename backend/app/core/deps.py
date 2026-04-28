"""FastAPI 依赖注入.

- get_db                  数据库 session
- get_current_user        从 JWT 解出 User (要求登录)
- get_current_user_opt    可选 (未登录返 None)
- require_role            装饰器: 校验角色
"""
from __future__ import annotations

from typing import Annotated

from fastapi import Depends, Header, Request
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.core.errors import AUTH_401, AUTH_423, AuthError
from app.core.security import decode_token
from app.models import User
from app.services import source_mysql_service


# 重导出以方便使用
__all__ = [
    "get_db",
    "DbSession",
    "get_current_user",
    "CurrentUser",
    "get_current_user_opt",
]


DbSession = Annotated[Session, Depends(get_db)]


def _extract_bearer(auth: str | None) -> str | None:
    if not auth:
        return None
    parts = auth.strip().split()
    if len(parts) == 2 and parts[0].lower() == "bearer":
        return parts[1]
    return None


def get_current_user(
    db: DbSession,
    request: Request,
    authorization: Annotated[str | None, Header(alias="Authorization")] = None,
) -> User:
    """硬要求登录. JWT 必须有效 + user 必须 active 未锁."""
    token = _extract_bearer(authorization)
    if not token:
        raise AuthError(AUTH_401, message="未提供身份凭证, 请登录")

    payload = decode_token(token)
    if payload.get("typ") != "access":
        raise AuthError(AUTH_401, message="凭证类型不正确")

    sub = payload.get("sub")
    try:
        user_id = int(sub)
    except (TypeError, ValueError):
        raise AuthError(AUTH_401, message="登录凭证无效, 请重新登录")

    user = source_mysql_service.get_user_by_id(db, user_id) if source_mysql_service.is_source_mysql(db) else db.get(User, user_id)
    if not user or getattr(user, "deleted_at", None) is not None:
        raise AuthError(AUTH_401, message="账号不存在, 请重新登录")
    if not user.is_active:
        raise AuthError(AUTH_423, message="账号已被锁定, 请联系客服")

    # 把 trace 加点 metadata
    request.state.current_user_id = user.id
    request.state.current_org_id = user.organization_id

    return user


CurrentUser = Annotated[User, Depends(get_current_user)]


def get_current_user_opt(
    db: DbSession,
    request: Request,
    authorization: Annotated[str | None, Header(alias="Authorization")] = None,
) -> User | None:
    """可选登录, 未登录返 None (不抛)."""
    token = _extract_bearer(authorization)
    if not token:
        return None
    try:
        payload = decode_token(token)
        if payload.get("typ") != "access":
            return None
        user_id = int(payload.get("sub"))
        user = source_mysql_service.get_user_by_id(db, user_id) if source_mysql_service.is_source_mysql(db) else db.get(User, user_id)
        if not user or getattr(user, "deleted_at", None) is not None or not user.is_active:
            return None
        request.state.current_user_id = user.id
        request.state.current_org_id = user.organization_id
        return user
    except Exception:
        return None
