"""Chengxing/CXT list and import service."""
from __future__ import annotations

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.core.errors import ResourceNotFound
from app.core.tenant_scope import compute_tenant_scope
from app.models import CxtUser, CxtVideo, User
from app.schemas.cxt import CxtUserImportRequest, CxtVideoImportRequest


def _apply_org_scope(stmt, model, db: Session, user: User):
    scope = compute_tenant_scope(db, user)
    if scope.unrestricted:
        return stmt
    return stmt.where(model.organization_id.in_(scope.organization_ids))


def list_users(
    db: Session,
    user: User,
    *,
    page: int = 1,
    size: int = 50,
    keyword: str | None = None,
    status: str | None = None,
):
    stmt = select(CxtUser)
    stmt = _apply_org_scope(stmt, CxtUser, db, user)
    if keyword:
        like = f"%{keyword}%"
        stmt = stmt.where(
            or_(
                CxtUser.platform_uid.like(like),
                CxtUser.username.like(like),
                CxtUser.auth_code.like(like),
                CxtUser.note.like(like),
            )
        )
    if status:
        stmt = stmt.where(CxtUser.status == status)

    total = db.execute(select(func.count()).select_from(stmt.subquery())).scalar_one()
    items = db.execute(
        stmt.order_by(CxtUser.id.desc()).offset((page - 1) * size).limit(size)
    ).scalars().all()
    return items, total


def import_users(db: Session, user: User, data: CxtUserImportRequest) -> dict:
    created = 0
    updated = 0
    org_id = user.organization_id
    for item in data.items:
        existing = db.execute(
            select(CxtUser)
            .where(CxtUser.organization_id == org_id)
            .where(CxtUser.platform_uid == item.platform_uid)
        ).scalar_one_or_none()
        if existing:
            existing.username = item.username
            existing.auth_code = item.auth_code
            existing.note = item.note
            existing.status = item.status
            updated += 1
        else:
            db.add(CxtUser(organization_id=org_id, **item.model_dump()))
            created += 1
    db.flush()
    return {"created": created, "updated": updated}


def list_videos(
    db: Session,
    user: User,
    *,
    page: int = 1,
    size: int = 50,
    keyword: str | None = None,
    platform: str | None = None,
):
    stmt = select(CxtVideo)
    stmt = _apply_org_scope(stmt, CxtVideo, db, user)
    if keyword:
        like = f"%{keyword}%"
        stmt = stmt.where(
            or_(
                CxtVideo.title.like(like),
                CxtVideo.author.like(like),
                CxtVideo.aweme_id.like(like),
                CxtVideo.description.like(like),
            )
        )
    if platform:
        stmt = stmt.where(CxtVideo.platform == platform)

    total = db.execute(select(func.count()).select_from(stmt.subquery())).scalar_one()
    items = db.execute(
        stmt.order_by(CxtVideo.id.desc()).offset((page - 1) * size).limit(size)
    ).scalars().all()
    return items, total


def get_video(db: Session, user: User, video_id: int) -> CxtVideo:
    stmt = select(CxtVideo).where(CxtVideo.id == video_id)
    stmt = _apply_org_scope(stmt, CxtVideo, db, user)
    row = db.execute(stmt).scalar_one_or_none()
    if not row:
        raise ResourceNotFound("CXT video not found")
    return row


def import_videos(db: Session, user: User, data: CxtVideoImportRequest) -> dict:
    created = 0
    updated = 0
    org_id = user.organization_id
    for item in data.items:
        payload = item.model_dump()
        existing = None
        if item.aweme_id:
            existing = db.execute(
                select(CxtVideo)
                .where(CxtVideo.platform == item.platform)
                .where(CxtVideo.aweme_id == item.aweme_id)
            ).scalar_one_or_none()
        if existing:
            for key, value in payload.items():
                setattr(existing, key, value)
            existing.organization_id = org_id
            updated += 1
        else:
            db.add(CxtVideo(organization_id=org_id, **payload))
            created += 1
    db.flush()
    return {"created": created, "updated": updated}
