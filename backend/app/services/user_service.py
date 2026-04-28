"""用户管理业务服务."""
from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.core.errors import (
    AUTH_403,
    AuthError,
    BizError,
    ConflictError,
    ResourceNotFound,
)
from app.core.permissions import invalidate_user_perms
from app.core.security import hash_password
from app.core.tenant_scope import (
    apply_to_user_query,
    compute_tenant_scope,
    validate_user_ids_in_scope,
)
from app.models import (
    DefaultRolePermission,
    User,
    UserButtonPermission,
    UserPagePermission,
)
from app.schemas.user import (
    UserCreate,
    UserPermissionsUpdate,
    UserUpdate,
)


_now = lambda: datetime.now(timezone.utc)  # noqa: E731


_ROLE_LEVEL = {
    "super_admin": 100,
    "operator": 50,
    "captain": 30,
    "normal_user": 10,
}


# ============================================================
# CRUD
# ============================================================

def list_users(
    db: Session,
    user: User,
    *,
    page: int = 1,
    size: int = 20,
    keyword: str | None = None,
    role: str | None = None,
    status: bool | None = None,
    parent_id: int | None = None,
):
    scope = compute_tenant_scope(db, user)
    stmt = select(User).where(User.deleted_at.is_(None))
    stmt = apply_to_user_query(stmt, scope, user)

    if keyword:
        like = f"%{keyword}%"
        stmt = stmt.where(
            or_(
                User.username.like(like),
                User.phone.like(like),
                User.display_name.like(like),
            )
        )
    if role:
        stmt = stmt.where(User.role == role)
    if status is not None:
        stmt = stmt.where(User.is_active.is_(status))
    if parent_id is not None:
        stmt = stmt.where(User.parent_user_id == parent_id)

    total = db.execute(select(func.count()).select_from(stmt.subquery())).scalar_one()
    stmt = stmt.order_by(User.id.desc()).offset((page - 1) * size).limit(size)
    items = db.execute(stmt).scalars().all()
    return items, total


def get_user(db: Session, current: User, user_id: int) -> User:
    scope = compute_tenant_scope(db, current)
    if not scope.unrestricted and user_id not in scope.user_ids:
        raise ResourceNotFound("用户不存在或不在您的范围")
    u = db.get(User, user_id)
    if not u or u.deleted_at:
        raise ResourceNotFound("用户不存在")
    return u


def create_user(db: Session, current: User, data: UserCreate) -> User:
    org_id = data.organization_id or current.organization_id
    if org_id != current.organization_id and current.role != "super_admin":
        raise AuthError(AUTH_403, message="只能在您所在的机构下创建用户")

    if data.role == "super_admin" and current.role != "super_admin":
        raise AuthError(AUTH_403, message="只有超管可创建超管")
    if _ROLE_LEVEL[data.role] >= _ROLE_LEVEL[current.role] and current.role != "super_admin":
        raise AuthError(AUTH_403, message=f"无权创建 {data.role} 等级或更高用户")

    # 防重
    dup = db.execute(select(User).where(User.username == data.username)).scalar_one_or_none()
    if dup:
        raise ConflictError(f"用户名 {data.username} 已存在")
    if data.phone:
        dup2 = db.execute(select(User).where(User.phone == data.phone)).scalar_one_or_none()
        if dup2:
            raise ConflictError(f"手机号 {data.phone} 已注册")

    parent_id = data.parent_user_id or current.id
    parent = db.get(User, parent_id)
    if not parent:
        raise ResourceNotFound("上级用户不存在")
    if parent_id != current.id and current.role != "super_admin":
        # 只能挂在自己或自己下属下
        scope = compute_tenant_scope(db, current)
        if parent_id not in scope.user_ids:
            raise AuthError(AUTH_403, message="无权挂在该上级下")

    u = User(
        organization_id=org_id,
        username=data.username,
        password_hash=hash_password(data.password),
        phone=data.phone,
        display_name=data.display_name or data.username,
        role=data.role,
        level=_ROLE_LEVEL[data.role],
        parent_user_id=parent_id,
        commission_rate=data.commission_rate,
        account_quota=data.account_quota,
        is_active=True,
    )
    db.add(u)
    db.flush()
    return u


def update_user(db: Session, current: User, user_id: int, data: UserUpdate) -> User:
    u = get_user(db, current, user_id)
    if u.id != current.id and current.role not in ("super_admin", "operator"):
        raise AuthError(AUTH_403, message="无权改其他用户资料")
    for k, v in data.model_dump(exclude_unset=True).items():
        setattr(u, k, v)
    db.flush()
    return u


def update_user_status(db: Session, current: User, user_id: int, is_active: bool) -> User:
    u = get_user(db, current, user_id)
    if u.id == current.id:
        raise BizError(AUTH_403, message="不能改变自己的启用状态")
    u.is_active = is_active
    db.flush()
    return u


def reset_password(db: Session, current: User, user_id: int, new_password: str) -> User:
    u = get_user(db, current, user_id)
    u.password_hash = hash_password(new_password)
    u.must_change_pw = True
    db.flush()
    return u


def update_role(db: Session, current: User, user_id: int, new_role: str) -> User:
    if current.role != "super_admin":
        raise AuthError(AUTH_403, message="只有超管可改角色")
    u = get_user(db, current, user_id)
    u.role = new_role
    u.level = _ROLE_LEVEL.get(new_role, 10)
    db.flush()
    invalidate_user_perms(u.id)
    return u


def update_commission(db: Session, current: User, user_id: int, rate: float) -> User:
    u = get_user(db, current, user_id)
    u.commission_rate = rate
    db.flush()
    return u


def update_commission_visibility(
    db: Session, current: User, user_id: int, **flags: bool | None
) -> User:
    u = get_user(db, current, user_id)
    for k, v in flags.items():
        if v is not None:
            setattr(u, k, v)
    db.flush()
    return u


# ============================================================
# 权限
# ============================================================

def get_user_permissions_view(db: Session, current: User, user_id: int) -> dict:
    """返回该用户的权限快照 (角色默认 + 用户级 grant/deny + effective)."""
    u = get_user(db, current, user_id)
    role_page = db.execute(
        select(DefaultRolePermission.permission_code)
        .where(DefaultRolePermission.role == u.role)
        .where(DefaultRolePermission.permission_type == "page")
    ).scalars().all()
    role_btn = db.execute(
        select(DefaultRolePermission.permission_code)
        .where(DefaultRolePermission.role == u.role)
        .where(DefaultRolePermission.permission_type == "button")
    ).scalars().all()

    user_page_grants = []
    user_page_denies = []
    for code, granted in db.execute(
        select(UserPagePermission.permission_code, UserPagePermission.granted)
        .where(UserPagePermission.user_id == user_id)
    ).all():
        (user_page_grants if granted else user_page_denies).append(code)

    user_btn_grants = []
    user_btn_denies = []
    for code, granted in db.execute(
        select(UserButtonPermission.permission_code, UserButtonPermission.granted)
        .where(UserButtonPermission.user_id == user_id)
    ).all():
        (user_btn_grants if granted else user_btn_denies).append(code)

    effective = set(role_page) | set(role_btn)
    effective.update(user_page_grants)
    effective.update(user_btn_grants)
    effective -= set(user_page_denies)
    effective -= set(user_btn_denies)

    return {
        "role_default_page": list(role_page),
        "role_default_button": list(role_btn),
        "user_page_grants": user_page_grants,
        "user_page_denies": user_page_denies,
        "user_button_grants": user_btn_grants,
        "user_button_denies": user_btn_denies,
        "effective": sorted(effective),
    }


def update_user_permissions(
    db: Session, current: User, user_id: int, data: UserPermissionsUpdate
) -> None:
    """覆盖式更新用户级 grant/deny."""
    u = get_user(db, current, user_id)

    # 删除当前用户级 perm
    db.query(UserPagePermission).filter(UserPagePermission.user_id == user_id).delete()
    db.query(UserButtonPermission).filter(UserButtonPermission.user_id == user_id).delete()

    for code in data.page_grants:
        db.add(UserPagePermission(user_id=user_id, permission_code=code, granted=1))
    for code in data.page_denies:
        db.add(UserPagePermission(user_id=user_id, permission_code=code, granted=0))
    for code in data.button_grants:
        db.add(UserButtonPermission(user_id=user_id, permission_code=code, granted=1))
    for code in data.button_denies:
        db.add(UserButtonPermission(user_id=user_id, permission_code=code, granted=0))

    db.flush()
    invalidate_user_perms(user_id)
