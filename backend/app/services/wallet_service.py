"""钱包结算资料服务."""
from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.errors import AUTH_403, AuthError, ResourceNotFound
from app.core.tenant_scope import compute_tenant_scope
from app.models import User, WalletProfile
from app.schemas.income import WalletUpdate


def get_my_wallet(db: Session, user: User) -> WalletProfile:
    w = db.execute(
        select(WalletProfile).where(WalletProfile.user_id == user.id)
    ).scalar_one_or_none()
    if not w:
        # 自动创建空 profile
        w = WalletProfile(user_id=user.id)
        db.add(w)
        db.flush()
    return w


def update_my_wallet(db: Session, user: User, data: WalletUpdate) -> WalletProfile:
    w = get_my_wallet(db, user)
    for k, v in data.model_dump(exclude_unset=True).items():
        setattr(w, k, v)
    db.flush()
    return w


def get_user_wallet(db: Session, viewer: User, user_id: int) -> WalletProfile:
    """super_admin / 授权运营 看别人的钱包."""
    if user_id == viewer.id:
        return get_my_wallet(db, viewer)

    if not viewer.is_superadmin and viewer.role != "super_admin":
        # 只有 super_admin 能看别人钱包 (按 PERMISSIONS_CATALOG)
        raise AuthError(AUTH_403, message="无权查看他人钱包")

    w = db.execute(
        select(WalletProfile).where(WalletProfile.user_id == user_id)
    ).scalar_one_or_none()
    if not w:
        target = db.get(User, user_id)
        if not target:
            raise ResourceNotFound("用户不存在")
        w = WalletProfile(user_id=user_id)
        db.add(w)
        db.flush()
    return w


def update_user_wallet(
    db: Session, viewer: User, user_id: int, data: WalletUpdate
) -> WalletProfile:
    if user_id == viewer.id:
        return update_my_wallet(db, viewer, data)
    if not viewer.is_superadmin and viewer.role != "super_admin":
        raise AuthError(AUTH_403, message="无权修改他人钱包")
    w = get_user_wallet(db, viewer, user_id)
    for k, v in data.model_dump(exclude_unset=True).items():
        setattr(w, k, v)
    db.flush()
    return w
