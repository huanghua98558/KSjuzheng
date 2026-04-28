"""权限引擎.

API:
  load_user_perms(db, user_id) -> set[str]      读全部权限点 (cache 5min)
  user_has_perm(db, user, code) -> bool
  require_perm(*codes)                          FastAPI dependency, raise AUTH_403 if missing

设计:
  - super_admin / is_superadmin = True 时直接放行
  - 其他 user: 角色默认权限 + 用户级 grant + 用户级 deny override
"""
from __future__ import annotations

import time
from typing import Any, Callable

from fastapi import Depends
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.deps import CurrentUser, DbSession
from app.core.errors import AUTH_403, AuthError
from app.models import (
    DefaultRolePermission,
    User,
    UserButtonPermission,
    UserPagePermission,
)


# ============================================================
# Cache (in-memory, 5min TTL, 单进程)
# ============================================================

_PERM_CACHE: dict[int, tuple[float, set[str]]] = {}
_TTL_SEC = 300


def _now() -> float:
    return time.time()


def invalidate_user_perms(user_id: int) -> None:
    """改用户权限后调用."""
    _PERM_CACHE.pop(user_id, None)


def invalidate_all() -> None:
    _PERM_CACHE.clear()


# ============================================================
# 加载权限
# ============================================================

def load_user_perms(db: Session, user: User) -> set[str]:
    """返该 user 的全部权限 code (page + button 合并)."""
    if user.is_superadmin or user.role == "super_admin":
        return {"*"}  # 通配, user_has_perm 见 * 直接 True

    cached = _PERM_CACHE.get(user.id)
    if cached and (_now() - cached[0]) < _TTL_SEC:
        return cached[1]

    perms: set[str] = set()

    # 1. 角色默认
    role_rows = db.execute(
        select(DefaultRolePermission.permission_code).where(
            DefaultRolePermission.role == user.role
        )
    ).scalars().all()
    perms.update(role_rows)

    # 2. 用户级 page perm 显式 grant/deny
    page_rows = db.execute(
        select(
            UserPagePermission.permission_code, UserPagePermission.granted
        ).where(UserPagePermission.user_id == user.id)
    ).all()
    for code, granted in page_rows:
        if granted:
            perms.add(code)
        else:
            perms.discard(code)

    # 3. 用户级 button perm
    btn_rows = db.execute(
        select(
            UserButtonPermission.permission_code, UserButtonPermission.granted
        ).where(UserButtonPermission.user_id == user.id)
    ).all()
    for code, granted in btn_rows:
        if granted:
            perms.add(code)
        else:
            perms.discard(code)

    _PERM_CACHE[user.id] = (_now(), perms)
    return perms


def user_has_perm(db: Session, user: User, code: str) -> bool:
    perms = load_user_perms(db, user)
    if "*" in perms:
        return True
    return code in perms


def user_has_any_perm(db: Session, user: User, codes: tuple[str, ...]) -> bool:
    perms = load_user_perms(db, user)
    if "*" in perms:
        return True
    return any(c in perms for c in codes)


# ============================================================
# FastAPI dependency
# ============================================================

def require_perm(*codes: str) -> Callable:
    """FastAPI dependency: 用户必须拥有任一 code, 否则 403."""

    def _dep(db: DbSession, user: CurrentUser) -> User:
        if not user_has_any_perm(db, user, codes):
            raise AuthError(
                AUTH_403,
                message="无此操作权限",
                details={"required_any_of": list(codes)},
            )
        return user

    return _dep


# 别名 (装饰器风格的同步包装可以另写, 这里 dependency 即可覆盖大多数场景)
RequirePerm = require_perm
