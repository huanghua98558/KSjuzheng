"""短剧收藏池业务服务 — CRUD + 异常检测 + 批量导入 + 去重复制."""
from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Iterable

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.core.errors import AUTH_403, AuthError, ConflictError, ResourceNotFound
from app.core.tenant_scope import TenantScope, compute_tenant_scope
from app.models import CollectPool, User
from app.schemas.content import (
    CollectPoolBatchImport,
    CollectPoolCreate,
    CollectPoolListQuery,
    CollectPoolUpdate,
)


_now = lambda: datetime.now(timezone.utc)  # noqa: E731

# 异常 URL 检测
_KS_URL_RE = re.compile(r"(kuaishou\.com|kwai|gifshow|ksapi|ndcimgs)", re.IGNORECASE)
_CHINESE_RE = re.compile(r"[\u4e00-\u9fff]")


def detect_abnormal(url: str) -> str | None:
    """返异常原因或 None."""
    if not url or not url.strip():
        return "url_empty"
    s = url.strip()
    if _CHINESE_RE.search(s):
        return "chinese_in_url"
    # 非快手且非典型平台前缀
    if not _KS_URL_RE.search(s):
        # douyin / chengxing 也允许, 仅 unknown 才算
        if not re.search(r"(douyin|tiktok|chengxing|cxt|shoubo)", s, re.IGNORECASE):
            return "non_kuaishou"
    return None


def _apply_scope(stmt, scope: TenantScope, _user: User):
    if scope.unrestricted:
        return stmt
    return stmt.where(CollectPool.organization_id.in_(scope.organization_ids))


def list_pool(
    db: Session, user: User, q: CollectPoolListQuery
) -> tuple[list[CollectPool], int]:
    scope = compute_tenant_scope(db, user)
    stmt = select(CollectPool).where(CollectPool.deleted_at.is_(None))
    stmt = _apply_scope(stmt, scope, user)

    if q.keyword:
        like = f"%{q.keyword}%"
        stmt = stmt.where(
            or_(
                CollectPool.drama_name.like(like),
                CollectPool.drama_url.like(like),
            )
        )
    if q.platform:
        stmt = stmt.where(CollectPool.platform == q.platform)
    if q.auth_code:
        stmt = stmt.where(CollectPool.auth_code == q.auth_code)
    if q.status:
        stmt = stmt.where(CollectPool.status == q.status)
    if q.abnormal:
        stmt = stmt.where(CollectPool.abnormal_reason == q.abnormal)
    if q.start:
        stmt = stmt.where(CollectPool.created_at >= q.start)
    if q.end:
        stmt = stmt.where(CollectPool.created_at <= q.end)

    total = db.execute(select(func.count()).select_from(stmt.subquery())).scalar_one()
    stmt = stmt.order_by(CollectPool.id.desc()).offset((q.page - 1) * q.size).limit(q.size)
    items = db.execute(stmt).scalars().all()
    return items, total


def get_one(db: Session, user: User, pool_id: int) -> CollectPool:
    scope = compute_tenant_scope(db, user)
    stmt = select(CollectPool).where(
        CollectPool.id == pool_id, CollectPool.deleted_at.is_(None)
    )
    stmt = _apply_scope(stmt, scope, user)
    p = db.execute(stmt).scalar_one_or_none()
    if not p:
        raise ResourceNotFound("收藏池条目不存在或不在您的范围")
    return p


def create_one(
    db: Session, user: User, data: CollectPoolCreate, organization_id: int | None = None
) -> CollectPool:
    org_id = organization_id or user.organization_id
    if org_id != user.organization_id and user.role != "super_admin":
        raise AuthError(AUTH_403, message="只能在您的机构下添加")

    # 同 org + url + auth_code 防重 (允许同 URL 在不同 auth_code 下)
    existing = db.execute(
        select(CollectPool)
        .where(CollectPool.organization_id == org_id)
        .where(CollectPool.drama_url == data.drama_url)
        .where(CollectPool.auth_code == data.auth_code)
        .where(CollectPool.deleted_at.is_(None))
    ).scalar_one_or_none()
    if existing:
        raise ConflictError(f"该 URL 已在收藏池: {data.drama_url[:60]}")

    abnormal = detect_abnormal(data.drama_url)
    p = CollectPool(
        organization_id=org_id,
        drama_name=data.drama_name,
        drama_url=data.drama_url,
        platform=data.platform,
        auth_code=data.auth_code,
        status="abnormal" if abnormal else "active",
        abnormal_reason=abnormal,
        imported_by_user_id=user.id,
    )
    db.add(p)
    db.flush()
    return p


def update_one(db: Session, user: User, pool_id: int, data: CollectPoolUpdate) -> CollectPool:
    p = get_one(db, user, pool_id)
    payload = data.model_dump(exclude_unset=True)
    new_url = payload.get("drama_url")
    if new_url and new_url != p.drama_url:
        # 重新检测异常
        abnormal = detect_abnormal(new_url)
        payload["status"] = "abnormal" if abnormal else "active"
        payload["abnormal_reason"] = abnormal
    for k, v in payload.items():
        setattr(p, k, v)
    db.flush()
    return p


def delete_one(db: Session, user: User, pool_id: int) -> None:
    p = get_one(db, user, pool_id)
    p.status = "deleted"
    p.deleted_at = _now()
    db.flush()


def batch_import(db: Session, user: User, data: CollectPoolBatchImport) -> dict:
    """跳过同 org + url 已存在条目, 跳过空 URL."""
    org_id = user.organization_id
    inserted = 0
    skipped_dup = 0
    skipped_invalid = 0
    abnormal_count = 0

    # 一次查同 org + 同 auth_code 集合 (per-auth_code 去重)
    auth_code_filter = data.items[0].auth_code if data.items else None
    exist_urls_q = (
        select(CollectPool.drama_url)
        .where(CollectPool.organization_id == org_id)
        .where(CollectPool.deleted_at.is_(None))
    )
    if auth_code_filter is not None:
        exist_urls_q = exist_urls_q.where(CollectPool.auth_code == auth_code_filter)
    else:
        exist_urls_q = exist_urls_q.where(CollectPool.auth_code.is_(None))
    exist_urls = set(db.execute(exist_urls_q).scalars().all())

    for item in data.items:
        url = (item.drama_url or "").strip()
        if not url:
            skipped_invalid += 1
            continue
        if url in exist_urls:
            skipped_dup += 1
            continue
        abnormal = detect_abnormal(url)
        p = CollectPool(
            organization_id=org_id,
            drama_name=item.drama_name,
            drama_url=url,
            platform=item.platform,
            auth_code=item.auth_code,
            status="abnormal" if abnormal else "active",
            abnormal_reason=abnormal,
            imported_by_user_id=user.id,
        )
        db.add(p)
        exist_urls.add(url)
        inserted += 1
        if abnormal:
            abnormal_count += 1
    db.flush()
    return {
        "inserted": inserted,
        "skipped_duplicate": skipped_dup,
        "skipped_invalid": skipped_invalid,
        "abnormal_count": abnormal_count,
    }


def deduplicate_and_copy(
    db: Session, user: User, source_auth_code: str, target_auth_code: str,
    keep_source: bool = True,
) -> dict:
    """把 source_auth_code 下的去重 URL 复制到 target_auth_code.

    如 keep_source=False, 删除 source 条目.
    """
    org_id = user.organization_id

    # 取 source 全集
    src_rows = db.execute(
        select(CollectPool)
        .where(CollectPool.organization_id == org_id)
        .where(CollectPool.auth_code == source_auth_code)
        .where(CollectPool.deleted_at.is_(None))
    ).scalars().all()

    # 已属 target 的 url (去重)
    target_existing_urls = set(db.execute(
        select(CollectPool.drama_url)
        .where(CollectPool.organization_id == org_id)
        .where(CollectPool.auth_code == target_auth_code)
        .where(CollectPool.deleted_at.is_(None))
    ).scalars().all())

    inserted = 0
    skipped = 0
    for src in src_rows:
        if src.drama_url in target_existing_urls:
            skipped += 1
            continue
        new = CollectPool(
            organization_id=org_id,
            drama_name=src.drama_name,
            drama_url=src.drama_url,
            platform=src.platform,
            auth_code=target_auth_code,
            status=src.status,
            abnormal_reason=src.abnormal_reason,
            imported_by_user_id=user.id,
        )
        db.add(new)
        target_existing_urls.add(src.drama_url)
        inserted += 1

    if not keep_source:
        for src in src_rows:
            src.status = "deleted"
            src.deleted_at = _now()

    db.flush()
    return {
        "inserted": inserted,
        "skipped_duplicate": skipped,
        "deleted_source": len(src_rows) if not keep_source else 0,
    }


def refresh_status(db: Session, user: User, ids: list[int] | None = None) -> dict:
    """重新检测一批 URL 异常状态. None=全量本机构."""
    scope = compute_tenant_scope(db, user)
    stmt = select(CollectPool).where(CollectPool.deleted_at.is_(None))
    stmt = _apply_scope(stmt, scope, user)
    if ids:
        stmt = stmt.where(CollectPool.id.in_(ids))
    rows = db.execute(stmt).scalars().all()
    changed = 0
    for r in rows:
        ab = detect_abnormal(r.drama_url)
        new_status = "abnormal" if ab else "active"
        if r.status != new_status or r.abnormal_reason != ab:
            r.status = new_status
            r.abnormal_reason = ab
            changed += 1
    db.flush()
    return {"checked": len(rows), "changed": changed}


def batch_delete(db: Session, user: User, ids: list[int]) -> dict:
    scope = compute_tenant_scope(db, user)
    if not scope.unrestricted:
        # 校验 ids 都在范围内
        in_scope = set(db.execute(
            select(CollectPool.id)
            .where(CollectPool.id.in_(ids))
            .where(CollectPool.organization_id.in_(scope.organization_ids))
        ).scalars().all())
        invalid = set(ids) - in_scope
        if invalid:
            raise AuthError(
                AUTH_403,
                message=f"部分条目不在您的可见范围 (共 {len(invalid)} 条)",
            )

    affected = 0
    now = _now()
    for pid in ids:
        p = db.get(CollectPool, pid)
        if p and not p.deleted_at:
            p.status = "deleted"
            p.deleted_at = now
            affected += 1
    db.flush()
    return {"success_count": affected, "failed_count": len(ids) - affected}
