"""机构 (Organization) 业务服务 — 仅 super_admin 可创建/删除."""
from __future__ import annotations

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.core.errors import AUTH_403, AuthError, ConflictError, ResourceNotFound
from app.core.tenant_scope import apply_to_org_query, compute_tenant_scope
from app.models import Organization, User
from app.schemas.user import OrganizationCreate, OrganizationUpdate


def list_orgs(db: Session, user: User, *, page: int = 1, size: int = 20, keyword: str | None = None):
    scope = compute_tenant_scope(db, user)
    stmt = select(Organization).where(Organization.deleted_at.is_(None))
    stmt = apply_to_org_query(stmt, scope, user)
    if keyword:
        like = f"%{keyword}%"
        stmt = stmt.where(
            or_(
                Organization.name.like(like),
                Organization.org_code.like(like),
                Organization.contact_phone.like(like),
            )
        )
    total = db.execute(select(func.count()).select_from(stmt.subquery())).scalar_one()
    stmt = stmt.order_by(Organization.id.desc()).offset((page - 1) * size).limit(size)
    items = db.execute(stmt).scalars().all()
    return items, total


def get_org(db: Session, user: User, org_id: int) -> Organization:
    scope = compute_tenant_scope(db, user)
    if not scope.unrestricted and org_id not in scope.organization_ids:
        raise ResourceNotFound("机构不存在或不在您的范围")
    o = db.get(Organization, org_id)
    if not o or o.deleted_at:
        raise ResourceNotFound("机构不存在")
    return o


def create_org(db: Session, user: User, data: OrganizationCreate) -> Organization:
    if user.role != "super_admin" and not user.is_superadmin:
        raise AuthError(AUTH_403, message="只有超管可创建机构")

    dup = db.execute(
        select(Organization).where(Organization.org_code == data.org_code)
    ).scalar_one_or_none()
    if dup:
        raise ConflictError(f"机构代码 {data.org_code} 已存在")

    o = Organization(**data.model_dump())
    db.add(o)
    db.flush()
    return o


def update_org(db: Session, user: User, org_id: int, data: OrganizationUpdate) -> Organization:
    o = get_org(db, user, org_id)
    if user.role != "super_admin" and not user.is_superadmin:
        raise AuthError(AUTH_403, message="只有超管可修改机构")
    for k, v in data.model_dump(exclude_unset=True).items():
        setattr(o, k, v)
    db.flush()
    return o


def delete_org(db: Session, user: User, org_id: int) -> None:
    if user.role != "super_admin" and not user.is_superadmin:
        raise AuthError(AUTH_403, message="只有超管可删除机构")
    from datetime import datetime, timezone
    o = get_org(db, user, org_id)
    o.deleted_at = datetime.now(timezone.utc)
    o.is_active = False
    db.flush()
