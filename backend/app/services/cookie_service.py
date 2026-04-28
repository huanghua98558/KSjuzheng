"""云端 Cookie 业务服务 — 加密 / 解密 / 脱敏 / 隔离."""
from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.core.crypto import decrypt_str, encrypt_str
from app.core.errors import AUTH_403, AuthError, ConflictError, ResourceNotFound
from app.core.tenant_scope import (
    TenantScope,
    compute_tenant_scope,
    validate_account_ids_in_scope,
)
from app.models import CloudCookieAccount, User
from app.schemas.account import CloudCookieCreate, CloudCookieUpdate


_now = lambda: datetime.now(timezone.utc)  # noqa: E731


def _apply_scope(stmt, scope: TenantScope, user: User):
    if scope.unrestricted:
        return stmt
    stmt = stmt.where(CloudCookieAccount.organization_id.in_(scope.organization_ids))
    if scope.account_filter == "self_only":
        stmt = stmt.where(CloudCookieAccount.assigned_user_id == user.id)
    return stmt


def list_cookies(
    db: Session,
    user: User,
    *,
    page: int = 1,
    size: int = 50,
    keyword: str | None = None,
    owner_code: str | None = None,
    status: str | None = None,
):
    scope = compute_tenant_scope(db, user)
    stmt = select(CloudCookieAccount)
    stmt = _apply_scope(stmt, scope, user)

    if keyword:
        like = f"%{keyword}%"
        stmt = stmt.where(
            or_(
                CloudCookieAccount.uid.like(like),
                CloudCookieAccount.nickname.like(like),
                CloudCookieAccount.owner_code.like(like),
            )
        )
    if owner_code:
        stmt = stmt.where(CloudCookieAccount.owner_code == owner_code)
    if status:
        stmt = stmt.where(CloudCookieAccount.login_status == status)

    total = db.execute(select(func.count()).select_from(stmt.subquery())).scalar_one()
    stmt = (
        stmt.order_by(CloudCookieAccount.id.desc())
        .offset((page - 1) * size)
        .limit(size)
    )
    items = db.execute(stmt).scalars().all()
    return items, total


def get_cookie(db: Session, user: User, cookie_id: int) -> CloudCookieAccount:
    scope = compute_tenant_scope(db, user)
    stmt = select(CloudCookieAccount).where(CloudCookieAccount.id == cookie_id)
    stmt = _apply_scope(stmt, scope, user)
    c = db.execute(stmt).scalar_one_or_none()
    if not c:
        raise ResourceNotFound("Cookie 不存在或不在您的范围")
    return c


def create_cookie(db: Session, user: User, data: CloudCookieCreate) -> CloudCookieAccount:
    org_id = data.organization_id or user.organization_id
    if org_id != user.organization_id and user.role != "super_admin":
        raise AuthError(AUTH_403, message="只能在您所在的机构下创建 Cookie")

    ciphertext, iv, tag, preview = encrypt_str(data.cookie)

    c = CloudCookieAccount(
        organization_id=org_id,
        uid=data.uid,
        nickname=data.nickname,
        owner_code=data.owner_code,
        cookie_ciphertext=ciphertext,
        cookie_iv=iv,
        cookie_tag=tag,
        cookie_preview=preview,
        login_status="unknown",
        imported_by_user_id=user.id,
    )
    db.add(c)
    db.flush()
    return c


def update_cookie(
    db: Session, user: User, cookie_id: int, data: CloudCookieUpdate
) -> CloudCookieAccount:
    c = get_cookie(db, user, cookie_id)
    for k, v in data.model_dump(exclude_unset=True).items():
        setattr(c, k, v)
    db.flush()
    return c


def delete_cookie(db: Session, user: User, cookie_id: int) -> None:
    c = get_cookie(db, user, cookie_id)
    db.delete(c)
    db.flush()


def reveal_cookie_plaintext(db: Session, user: User, cookie_id: int) -> str:
    """高敏: 返明文. 调用方必须装 require_perm('cloud-cookie:reveal-plaintext')."""
    c = get_cookie(db, user, cookie_id)
    if not c.cookie_ciphertext or not c.cookie_iv or not c.cookie_tag:
        raise ResourceNotFound("Cookie 数据不完整")
    return decrypt_str(c.cookie_ciphertext, c.cookie_iv, c.cookie_tag)


def batch_update_owner(
    db: Session, user: User, ids: list[int], owner_code: str
) -> dict:
    scope = compute_tenant_scope(db, user)
    if not scope.unrestricted:
        # 校验所有 ids 都在范围内
        stmt = (
            select(CloudCookieAccount.id)
            .where(CloudCookieAccount.organization_id.in_(scope.organization_ids))
            .where(CloudCookieAccount.id.in_(ids))
        )
        visible = set(db.execute(stmt).scalars().all())
        invalid = set(ids) - visible
        if invalid:
            raise AuthError(
                AUTH_403,
                message=f"部分 Cookie 不在您的可见范围 (共 {len(invalid)} 条)",
            )

    affected = 0
    for cid in ids:
        c = db.get(CloudCookieAccount, cid)
        if c:
            c.owner_code = owner_code
            affected += 1
    db.flush()
    return {"success_count": affected, "failed_count": len(ids) - affected}


def batch_delete(db: Session, user: User, ids: list[int]) -> dict:
    scope = compute_tenant_scope(db, user)
    if not scope.unrestricted:
        stmt = (
            select(CloudCookieAccount.id)
            .where(CloudCookieAccount.organization_id.in_(scope.organization_ids))
            .where(CloudCookieAccount.id.in_(ids))
        )
        visible = set(db.execute(stmt).scalars().all())
        invalid = set(ids) - visible
        if invalid:
            raise AuthError(AUTH_403, message="部分 Cookie 不在您的可见范围")

    for cid in ids:
        c = db.get(CloudCookieAccount, cid)
        if c:
            db.delete(c)
    db.flush()
    return {"success_count": len(ids), "failed_count": 0}
