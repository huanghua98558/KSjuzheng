"""账号资产业务服务 — 软件账号 / KS账号 / 分组 / 任务记录."""
from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import and_, func, or_, select
from sqlalchemy.orm import Session

from app.core.errors import (
    AUTH_403,
    AuthError,
    BizError,
    ConflictError,
    ResourceNotFound,
)
from app.core.tenant_scope import (
    TenantScope,
    apply_to_account_query,
    compute_tenant_scope,
    validate_account_ids_in_scope,
)
from app.models import (
    Account,
    AccountGroup,
    AccountTaskRecord,
    KsAccount,
    McnAuthorization,
    User,
)
from app.schemas.account import (
    AccountCreate,
    AccountListQuery,
    AccountUpdate,
)


_now = lambda: datetime.now(timezone.utc)  # noqa: E731


# ============================================================
# Account CRUD
# ============================================================

def list_accounts(db: Session, user: User, q: AccountListQuery):
    scope = compute_tenant_scope(db, user)
    stmt = select(Account).where(Account.deleted_at.is_(None))
    stmt = apply_to_account_query(stmt, scope, user)

    # 筛选
    if q.keyword:
        like = f"%{q.keyword}%"
        stmt = stmt.where(
            or_(
                Account.kuaishou_id.like(like),
                Account.real_uid.like(like),
                Account.nickname.like(like),
                Account.remark.like(like),
            )
        )
    if q.org_id is not None and scope.unrestricted:
        stmt = stmt.where(Account.organization_id == q.org_id)
    if q.group_id is not None:
        stmt = stmt.where(Account.group_id == q.group_id)
    if q.assigned_user_id is not None:
        stmt = stmt.where(Account.assigned_user_id == q.assigned_user_id)
    if q.status:
        stmt = stmt.where(Account.status == q.status)
    if q.sign_status:
        stmt = stmt.where(Account.sign_status == q.sign_status)
    if q.mcn_status:
        stmt = stmt.where(Account.mcn_status == q.mcn_status)
    if q.commission_min is not None:
        stmt = stmt.where(Account.commission_rate >= q.commission_min)
    if q.commission_max is not None:
        stmt = stmt.where(Account.commission_rate <= q.commission_max)

    # 总数
    count_stmt = select(func.count()).select_from(stmt.subquery())
    total = db.execute(count_stmt).scalar_one()

    # 排序
    sort = (q.sort or "created_at.desc").split(",")[0].strip()
    field, _, direction = sort.partition(".")
    direction = direction or "desc"
    col = getattr(Account, field, Account.created_at)
    stmt = stmt.order_by(col.desc() if direction == "desc" else col.asc())

    # 分页
    stmt = stmt.offset((q.page - 1) * q.size).limit(q.size)
    items = db.execute(stmt).scalars().all()

    return items, total


def get_account(db: Session, user: User, account_id: int) -> Account:
    scope = compute_tenant_scope(db, user)
    stmt = select(Account).where(Account.id == account_id, Account.deleted_at.is_(None))
    stmt = apply_to_account_query(stmt, scope, user)
    a = db.execute(stmt).scalar_one_or_none()
    if not a:
        raise ResourceNotFound("账号不存在或不在您的可见范围")
    return a


def create_account(db: Session, user: User, data: AccountCreate) -> Account:
    org_id = data.organization_id or user.organization_id
    if org_id != user.organization_id and user.role != "super_admin":
        raise AuthError(AUTH_403, message="只能在您所在的机构下创建账号")

    # 防重 (kuaishou_id 唯一)
    if data.kuaishou_id:
        dup = db.execute(
            select(Account).where(
                Account.kuaishou_id == data.kuaishou_id,
                Account.organization_id == org_id,
                Account.deleted_at.is_(None),
            )
        ).scalar_one_or_none()
        if dup:
            raise ConflictError(f"账号 {data.kuaishou_id} 已存在")

    a = Account(
        organization_id=org_id,
        kuaishou_id=data.kuaishou_id,
        real_uid=data.real_uid,
        nickname=data.nickname,
        commission_rate=data.commission_rate,
        assigned_user_id=data.assigned_user_id,
        group_id=data.group_id,
        device_serial=data.device_serial,
        remark=data.remark,
        imported_by_user_id=user.id,
        imported_at=_now(),
    )
    db.add(a)
    db.flush()
    return a


def update_account(db: Session, user: User, account_id: int, data: AccountUpdate) -> Account:
    a = get_account(db, user, account_id)
    for k, v in data.model_dump(exclude_unset=True).items():
        setattr(a, k, v)
    db.flush()
    return a


def delete_account(db: Session, user: User, account_id: int) -> None:
    a = get_account(db, user, account_id)
    a.status = "deleted"
    a.deleted_at = _now()
    db.flush()


# ============================================================
# Batch ops (★ 安全核心)
# ============================================================

def batch_authorize(db: Session, user: User, ids: list[int]) -> dict:
    """批量授权 MCN. 在 TenantScope 内逐 ID 校验, 整批拒部分越权."""
    scope = compute_tenant_scope(db, user)
    validate_account_ids_in_scope(db, scope, user, ids)

    affected = 0
    for aid in ids:
        a = db.get(Account, aid)
        if not a or a.deleted_at:
            continue
        # 写 mcn_authorizations
        existing = db.execute(
            select(McnAuthorization)
            .where(McnAuthorization.account_id == aid)
            .where(McnAuthorization.organization_id == a.organization_id)
        ).scalar_one_or_none()
        if existing:
            existing.mcn_status = "authorized"
            existing.authorized_at = _now()
            existing.revoked_at = None
        else:
            db.add(McnAuthorization(
                account_id=aid,
                organization_id=a.organization_id,
                mcn_status="authorized",
                sign_status="signed",
                authorized_at=_now(),
            ))
        a.mcn_status = "authorized"
        affected += 1
    db.flush()
    return {"success_count": affected, "failed_count": len(ids) - affected}


def batch_revoke(db: Session, user: User, ids: list[int]) -> dict:
    scope = compute_tenant_scope(db, user)
    validate_account_ids_in_scope(db, scope, user, ids)

    affected = 0
    for aid in ids:
        a = db.get(Account, aid)
        if not a:
            continue
        a.mcn_status = "revoked"
        existing = db.execute(
            select(McnAuthorization)
            .where(McnAuthorization.account_id == aid)
        ).scalar_one_or_none()
        if existing:
            existing.mcn_status = "revoked"
            existing.revoked_at = _now()
        affected += 1
    db.flush()
    return {"success_count": affected, "failed_count": len(ids) - affected}


def batch_assign_user(
    db: Session, user: User, ids: list[int], assigned_user_id: int
) -> dict:
    scope = compute_tenant_scope(db, user)
    validate_account_ids_in_scope(db, scope, user, ids)
    # 校验目标 user 也在范围内
    if not scope.unrestricted and assigned_user_id not in scope.user_ids:
        raise AuthError(AUTH_403, message="目标用户不在您的管理范围")

    target = db.get(User, assigned_user_id)
    if not target or target.deleted_at:
        raise ResourceNotFound("目标用户不存在")

    for aid in ids:
        a = db.get(Account, aid)
        if a:
            a.assigned_user_id = assigned_user_id
    db.flush()
    return {"success_count": len(ids), "failed_count": 0}


def batch_set_group(
    db: Session, user: User, ids: list[int], group_id: int | None
) -> dict:
    scope = compute_tenant_scope(db, user)
    validate_account_ids_in_scope(db, scope, user, ids)

    if group_id is not None:
        g = db.get(AccountGroup, group_id)
        if not g:
            raise ResourceNotFound("分组不存在")
        if not scope.unrestricted and g.organization_id not in scope.organization_ids:
            raise AuthError(AUTH_403, message="目标分组不在您的机构")

    for aid in ids:
        a = db.get(Account, aid)
        if a:
            a.group_id = group_id
    db.flush()
    return {"success_count": len(ids), "failed_count": 0}


def batch_set_status(
    db: Session, user: User, ids: list[int], status: str
) -> dict:
    scope = compute_tenant_scope(db, user)
    validate_account_ids_in_scope(db, scope, user, ids)
    for aid in ids:
        a = db.get(Account, aid)
        if a:
            a.status = status
    db.flush()
    return {"success_count": len(ids), "failed_count": 0}


def batch_set_commission(
    db: Session, user: User, ids: list[int], rate: float
) -> dict:
    scope = compute_tenant_scope(db, user)
    validate_account_ids_in_scope(db, scope, user, ids)
    for aid in ids:
        a = db.get(Account, aid)
        if a:
            a.commission_rate = rate
    db.flush()
    return {"success_count": len(ids), "failed_count": 0}


def batch_delete(db: Session, user: User, ids: list[int]) -> dict:
    scope = compute_tenant_scope(db, user)
    validate_account_ids_in_scope(db, scope, user, ids)
    now = _now()
    for aid in ids:
        a = db.get(Account, aid)
        if a and not a.deleted_at:
            a.status = "deleted"
            a.deleted_at = now
    db.flush()
    return {"success_count": len(ids), "failed_count": 0}


# ============================================================
# 任务记录
# ============================================================

def list_account_tasks(
    db: Session, user: User, account_id: int, page: int = 1, size: int = 50
):
    """单账号的任务记录."""
    a = get_account(db, user, account_id)
    stmt = (
        select(AccountTaskRecord)
        .where(AccountTaskRecord.account_id == account_id)
        .order_by(AccountTaskRecord.created_at.desc())
    )
    total = db.execute(
        select(func.count()).select_from(stmt.subquery())
    ).scalar_one()
    items = db.execute(
        stmt.offset((page - 1) * size).limit(size)
    ).scalars().all()
    return items, total
