"""公告 + 系统配置 + 默认权限模板 服务."""
from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.crypto import HAS_CRYPTO
from app.core.errors import AUTH_403, AuthError, ResourceNotFound
from app.core.permissions import invalidate_all
from app.core.tenant_scope import compute_tenant_scope
from app.models import (
    Announcement,
    DefaultRolePermission,
    Permission,
    User,
)
from app.schemas.settings import (
    AnnouncementCreate,
    AnnouncementUpdate,
    RoleDefaultsUpdate,
)


_now = lambda: datetime.now(timezone.utc)  # noqa: E731


# ============================================================
# Announcement
# ============================================================

def list_announcements(
    db: Session, user: User,
    *, page: int = 1, size: int = 50, active_only: bool = False,
):
    scope = compute_tenant_scope(db, user)
    stmt = select(Announcement)
    if not scope.unrestricted:
        stmt = stmt.where(
            or_(
                Announcement.organization_id.in_(scope.organization_ids),
                Announcement.organization_id.is_(None),  # 全平台公告
            )
        )
    if active_only:
        stmt = stmt.where(Announcement.active.is_(True))
        now = _now()
        # 只过期内
        stmt = stmt.where(
            or_(Announcement.start_at.is_(None), Announcement.start_at <= now)
        ).where(
            or_(Announcement.end_at.is_(None), Announcement.end_at >= now)
        )
    total = db.execute(select(func.count()).select_from(stmt.subquery())).scalar_one()
    stmt = (
        stmt.order_by(Announcement.pinned.desc(), Announcement.id.desc())
        .offset((page - 1) * size).limit(size)
    )
    items = db.execute(stmt).scalars().all()
    return items, total


def list_active(db: Session, user: User) -> list[Announcement]:
    items, _ = list_announcements(db, user, page=1, size=20, active_only=True)
    return items


def create_announcement(
    db: Session, user: User, data: AnnouncementCreate
) -> Announcement:
    org_id = data.organization_id
    if org_id is None and user.role != "super_admin" and not user.is_superadmin:
        # 非超管: 默认本机构, 不可发全平台公告
        org_id = user.organization_id
    if org_id is not None and org_id != user.organization_id and user.role != "super_admin":
        raise AuthError(AUTH_403, message="无权在该机构发布公告")

    a = Announcement(
        organization_id=org_id,
        title=data.title,
        content=data.content,
        level=data.level,
        pinned=data.pinned,
        active=data.active,
        start_at=data.start_at,
        end_at=data.end_at,
        created_by_user_id=user.id,
    )
    db.add(a)
    db.flush()
    return a


def get_announcement(db: Session, user: User, aid: int) -> Announcement:
    scope = compute_tenant_scope(db, user)
    a = db.get(Announcement, aid)
    if not a:
        raise ResourceNotFound("公告不存在")
    if not scope.unrestricted:
        if a.organization_id is not None and a.organization_id not in scope.organization_ids:
            raise AuthError(AUTH_403, message="不在您的可见范围")
    return a


def update_announcement(
    db: Session, user: User, aid: int, data: AnnouncementUpdate
) -> Announcement:
    a = get_announcement(db, user, aid)
    # 修改全平台公告 仅超管
    if a.organization_id is None and user.role != "super_admin":
        raise AuthError(AUTH_403, message="只有超管可改全平台公告")
    for k, v in data.model_dump(exclude_unset=True).items():
        setattr(a, k, v)
    db.flush()
    return a


def delete_announcement(db: Session, user: User, aid: int) -> None:
    a = get_announcement(db, user, aid)
    if a.organization_id is None and user.role != "super_admin":
        raise AuthError(AUTH_403, message="只有超管可删全平台公告")
    db.delete(a)
    db.flush()


# ============================================================
# Settings — Basic
# ============================================================

def get_basic() -> dict:
    """返脱敏后的服务基本信息."""
    db_url = settings.DATABASE_URL
    # 脱敏 DB URL
    if "@" in db_url:
        # postgresql+psycopg://user:pass@host... → postgresql+psycopg://***@host...
        prefix, _, tail = db_url.partition("://")
        creds, _, host_part = tail.rpartition("@")
        masked = f"{prefix}://***@{host_part}" if creds else db_url
    else:
        masked = db_url

    return {
        "app_name": settings.APP_NAME,
        "app_version": settings.APP_VERSION,
        "app_env": settings.APP_ENV,
        "timezone": settings.TIMEZONE,
        "db_url_masked": masked,
        "has_crypto": HAS_CRYPTO,
        "has_redis": bool(settings.REDIS_URL),
        "cors_origins": settings.cors_origins_list,
        "server_time": _now(),
    }


def get_about() -> dict:
    return {
        "name": settings.APP_NAME,
        "version": settings.APP_VERSION,
        "license": "Internal",
        "description": "KS矩阵后端 — KS184 业务中台 + AI 自动化",
        "links": {
            "blueprint": "docs/服务器后端完整蓝图_含AI自动化v1.md",
            "api_doc": "/docs",
        },
    }


# ============================================================
# Role-defaults
# ============================================================

def list_role_defaults(db: Session) -> dict:
    rows = db.execute(select(DefaultRolePermission)).scalars().all()
    items = [
        {
            "role": r.role,
            "permission_type": r.permission_type,
            "permission_code": r.permission_code,
        }
        for r in rows
    ]
    summary: dict = {}
    for r in rows:
        summary.setdefault(r.role, {"page": 0, "button": 0})
        summary[r.role][r.permission_type] += 1
    return {"items": items, "role_summary": summary}


def update_role_defaults(db: Session, data: RoleDefaultsUpdate) -> dict:
    """覆盖式: 删该 role 旧的 → 重新插入. 同时 invalidate perm cache."""
    # 校验 perm 都存在
    all_codes = set(data.page_codes) | set(data.button_codes)
    if all_codes:
        existing = set(db.execute(
            select(Permission.code).where(Permission.code.in_(all_codes))
        ).scalars().all())
        invalid = all_codes - existing
        if invalid:
            raise ResourceNotFound(f"未知权限 code: {sorted(invalid)[:5]}")

    # 覆盖删
    db.query(DefaultRolePermission).filter(
        DefaultRolePermission.role == data.role
    ).delete()

    for code in data.page_codes:
        db.add(DefaultRolePermission(
            role=data.role, permission_type="page", permission_code=code,
        ))
    for code in data.button_codes:
        db.add(DefaultRolePermission(
            role=data.role, permission_type="button", permission_code=code,
        ))
    db.flush()

    # 影响所有 role=this 的用户
    invalidate_all()

    return {
        "role": data.role,
        "page_count": len(data.page_codes),
        "button_count": len(data.button_codes),
    }
