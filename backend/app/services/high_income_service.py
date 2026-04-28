"""高转化短剧 + 收藏记录 + 外部 URL 业务服务."""
from __future__ import annotations

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.core.errors import AUTH_403, AuthError, ConflictError, ResourceNotFound
from app.core.tenant_scope import TenantScope, compute_tenant_scope
from app.models import (
    CollectPool,
    DramaCollectionRecord,
    ExternalUrlStat,
    HighIncomeDrama,
    User,
)
from app.schemas.content import HighIncomeDramaCreate


# ============================================================
# HighIncomeDrama
# ============================================================

def _apply_high_scope(stmt, scope: TenantScope, _user: User):
    if scope.unrestricted:
        return stmt
    return stmt.where(HighIncomeDrama.organization_id.in_(scope.organization_ids))


def list_high_income(
    db: Session, user: User, *, page: int = 1, size: int = 50, keyword: str | None = None,
):
    scope = compute_tenant_scope(db, user)
    stmt = select(HighIncomeDrama)
    stmt = _apply_high_scope(stmt, scope, user)
    if keyword:
        stmt = stmt.where(HighIncomeDrama.drama_name.like(f"%{keyword}%"))

    total = db.execute(select(func.count()).select_from(stmt.subquery())).scalar_one()
    stmt = stmt.order_by(HighIncomeDrama.id.desc()).offset((page - 1) * size).limit(size)
    items = db.execute(stmt).scalars().all()
    return items, total


def create_high_income(
    db: Session, user: User, data: HighIncomeDramaCreate
) -> HighIncomeDrama:
    org_id = user.organization_id
    existing = db.execute(
        select(HighIncomeDrama)
        .where(HighIncomeDrama.organization_id == org_id)
        .where(HighIncomeDrama.drama_name == data.drama_name)
    ).scalar_one_or_none()
    if existing:
        raise ConflictError(f"剧 {data.drama_name} 已在高转化清单")

    h = HighIncomeDrama(
        organization_id=org_id,
        drama_name=data.drama_name,
        source_program=data.source_program,
        source_income_id=data.source_income_id,
        income_amount=data.income_amount,
        notes=data.notes,
        added_by_user_id=user.id,
    )
    db.add(h)
    db.flush()
    return h


def delete_high_income(db: Session, user: User, hid: int) -> None:
    scope = compute_tenant_scope(db, user)
    h = db.get(HighIncomeDrama, hid)
    if not h:
        raise ResourceNotFound("条目不存在")
    if not scope.unrestricted and h.organization_id not in scope.organization_ids:
        raise AuthError(AUTH_403, message="不在您的可见范围")
    db.delete(h)
    db.flush()


def get_high_income(db: Session, user: User, hid: int) -> HighIncomeDrama:
    scope = compute_tenant_scope(db, user)
    h = db.get(HighIncomeDrama, hid)
    if not h:
        raise ResourceNotFound("条目不存在")
    if not scope.unrestricted and h.organization_id not in scope.organization_ids:
        raise AuthError(AUTH_403, message="不在您的可见范围")
    return h


def get_high_income_links(db: Session, user: User, hid: int) -> list[CollectPool]:
    """跳到收藏池查相同 drama_name 的链接."""
    h = get_high_income(db, user, hid)
    rows = db.execute(
        select(CollectPool)
        .where(CollectPool.organization_id == h.organization_id)
        .where(CollectPool.drama_name == h.drama_name)
        .where(CollectPool.deleted_at.is_(None))
    ).scalars().all()
    return rows


# ============================================================
# DramaCollectionRecord
# ============================================================

def list_drama_collections(
    db: Session, user: User, *, page: int = 1, size: int = 50, keyword: str | None = None,
):
    scope = compute_tenant_scope(db, user)
    stmt = select(DramaCollectionRecord)
    if not scope.unrestricted:
        stmt = stmt.where(
            DramaCollectionRecord.organization_id.in_(scope.organization_ids)
        )
        if scope.account_filter == "self_only":
            # normal_user: 仅自己的账号
            from app.models import Account
            sub = (
                select(Account.id)
                .where(Account.assigned_user_id == user.id)
            )
            stmt = stmt.where(DramaCollectionRecord.account_id.in_(sub))
    if keyword:
        like = f"%{keyword}%"
        stmt = stmt.where(
            or_(
                DramaCollectionRecord.account_uid.like(like),
                DramaCollectionRecord.account_name.like(like),
            )
        )
    total = db.execute(select(func.count()).select_from(stmt.subquery())).scalar_one()
    stmt = (
        stmt.order_by(DramaCollectionRecord.total_count.desc())
        .offset((page - 1) * size)
        .limit(size)
    )
    items = db.execute(stmt).scalars().all()
    return items, total


def get_drama_collection_detail(db: Session, user: User, account_uid: str) -> dict:
    scope = compute_tenant_scope(db, user)
    stmt = select(DramaCollectionRecord).where(
        DramaCollectionRecord.account_uid == account_uid
    )
    if not scope.unrestricted:
        stmt = stmt.where(
            DramaCollectionRecord.organization_id.in_(scope.organization_ids)
        )
    r = db.execute(stmt).scalar_one_or_none()
    if not r:
        raise ResourceNotFound("无该 UID 的收藏记录")
    return {
        "account_uid": r.account_uid,
        "account_name": r.account_name,
        "total_count": r.total_count,
        "spark_count": r.spark_count,
        "firefly_count": r.firefly_count,
        "fluorescent_count": r.fluorescent_count,
        "last_collected_at": r.last_collected_at.isoformat() if r.last_collected_at else None,
    }


# ============================================================
# ExternalUrlStat
# ============================================================

def list_external_urls(
    db: Session, user: User, *, page: int = 1, size: int = 50, keyword: str | None = None,
):
    scope = compute_tenant_scope(db, user)
    stmt = select(ExternalUrlStat)
    if not scope.unrestricted:
        stmt = stmt.where(
            or_(
                ExternalUrlStat.organization_id.in_(scope.organization_ids),
                ExternalUrlStat.organization_id.is_(None),
            )
        )
    if keyword:
        stmt = stmt.where(ExternalUrlStat.url.like(f"%{keyword}%"))
    total = db.execute(select(func.count()).select_from(stmt.subquery())).scalar_one()
    stmt = (
        stmt.order_by(ExternalUrlStat.reference_count.desc())
        .offset((page - 1) * size)
        .limit(size)
    )
    items = db.execute(stmt).scalars().all()
    return items, total
