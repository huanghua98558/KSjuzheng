"""租户隔离 — 计算 user 的可见范围, 应用到查询.

对应文档: docs/PERMISSIONS_CATALOG.md §5 + docs/MODULE_SPEC.md 通用规约 §D.

核心 API:
  scope = compute_tenant_scope(user)
  stmt  = apply_tenant_scope_to_account(stmt, scope, user)
  validate_payload_ownership(scope, ids, db, model_class)
"""
from __future__ import annotations

from dataclasses import dataclass, field
from functools import lru_cache

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.core.errors import AUTH_403, BizError
from app.models import Account, User


# ============================================================
# Scope 数据结构
# ============================================================

@dataclass
class TenantScope:
    """单用户可见的范围.

    `unrestricted` = True 时, 全平台 (super_admin).
    否则按 organization_ids + user_ids 过滤.
    """

    unrestricted: bool = False
    organization_ids: list[int] = field(default_factory=list)
    user_ids: list[int] = field(default_factory=list)
    # 'self_only' = normal_user, 'team' = captain/operator
    account_filter: str = "team"


# ============================================================
# 上下级递归
# ============================================================

def _subordinate_user_ids(db: Session, user_id: int, max_depth: int = 5) -> list[int]:
    """获取所有直接 + 间接下属 (深度限 5 层避环)."""
    out = []
    frontier = [user_id]
    visited = {user_id}
    for _depth in range(max_depth):
        if not frontier:
            break
        rows = db.execute(
            select(User.id).where(User.parent_user_id.in_(frontier))
        ).scalars().all()
        new = [r for r in rows if r not in visited]
        if not new:
            break
        out.extend(new)
        visited.update(new)
        frontier = new
    return out


# ============================================================
# 主入口
# ============================================================

def compute_tenant_scope(db: Session, user: User) -> TenantScope:
    """根据 user 角色计算可见范围."""
    # super_admin 全平台
    if user.is_superadmin or user.role == "super_admin":
        return TenantScope(unrestricted=True)

    # 默认: 组织 = 自己的, 用户范围 = 自己 + 下属
    org_ids = [user.organization_id]
    subs = _subordinate_user_ids(db, user.id)
    user_ids = [user.id] + subs

    if user.role == "operator":
        return TenantScope(
            unrestricted=False,
            organization_ids=org_ids,
            user_ids=user_ids,
            account_filter="team",
        )
    if user.role == "captain":
        return TenantScope(
            unrestricted=False,
            organization_ids=org_ids,
            user_ids=user_ids,
            account_filter="team",
        )
    # normal_user
    return TenantScope(
        unrestricted=False,
        organization_ids=org_ids,
        user_ids=[user.id],
        account_filter="self_only",
    )


# ============================================================
# 应用到 query
# ============================================================

def apply_to_account_query(stmt, scope: TenantScope, user: User):
    """给 Account 查询自动追加 WHERE."""
    if scope.unrestricted:
        return stmt

    stmt = stmt.where(Account.organization_id.in_(scope.organization_ids))

    if scope.account_filter == "self_only":
        # normal_user: 仅 assigned_user_id == self
        stmt = stmt.where(Account.assigned_user_id == user.id)
    else:
        # captain / operator: 自己 + 下属 + 未分配 (operator 看)
        if user.role == "operator":
            stmt = stmt.where(
                or_(
                    Account.assigned_user_id.in_(scope.user_ids),
                    Account.assigned_user_id.is_(None),
                )
            )
        else:  # captain
            stmt = stmt.where(Account.assigned_user_id.in_(scope.user_ids))

    return stmt


def apply_to_user_query(stmt, scope: TenantScope, user: User):
    """给 User 查询自动追加 WHERE (用户管理页用)."""
    if scope.unrestricted:
        return stmt
    stmt = stmt.where(User.organization_id.in_(scope.organization_ids))
    # 只能看自己 + 下属 (含自己)
    stmt = stmt.where(User.id.in_(scope.user_ids))
    return stmt


def apply_to_org_query(stmt, scope: TenantScope, user: User):
    """给 Organization 查询追加 WHERE."""
    if scope.unrestricted:
        return stmt
    from app.models import Organization
    stmt = stmt.where(Organization.id.in_(scope.organization_ids))
    return stmt


# ============================================================
# 批量越权校验 (★ 关键)
# ============================================================

def validate_account_ids_in_scope(
    db: Session, scope: TenantScope, user: User, account_ids: list[int]
) -> None:
    """逐 ID 校验是否在范围内, 不在则整批拒.

    用于所有 batch-* 端点. 不允许部分成功.
    """
    if scope.unrestricted:
        return

    if not account_ids:
        return

    stmt = select(Account.id)
    stmt = apply_to_account_query(stmt, scope, user)
    stmt = stmt.where(Account.id.in_(account_ids))
    visible_ids = set(db.execute(stmt).scalars().all())
    requested = set(account_ids)
    invalid = requested - visible_ids
    if invalid:
        raise BizError(
            AUTH_403,
            message=f"部分账号 ID 不在您的可见范围 (共 {len(invalid)} 条)",
            details={"out_of_scope_ids": sorted(invalid)[:10]},
        )


def validate_uids_in_scope(
    db: Session, scope: TenantScope, user: User, uids: list[str]
) -> None:
    """逐 UID 校验. 用于 member-query 等高敏接口."""
    if scope.unrestricted:
        return

    if not uids:
        return

    stmt = select(Account.real_uid)
    stmt = apply_to_account_query(stmt, scope, user)
    stmt = stmt.where(Account.real_uid.in_(uids))
    visible_uids = set(db.execute(stmt).scalars().all())
    requested = set(uids)
    invalid = requested - visible_uids
    if invalid:
        raise BizError(
            AUTH_403,
            message=f"部分 UID 不在您的可见范围 (共 {len(invalid)} 条)",
            details={"out_of_scope_uids": sorted(invalid)[:10]},
        )


def validate_user_ids_in_scope(
    db: Session, scope: TenantScope, _user: User, user_ids: list[int]
) -> None:
    """校验 user_id 是否在 scope.user_ids 内 (改密 / 改权限场景)."""
    if scope.unrestricted:
        return
    visible = set(scope.user_ids)
    invalid = set(user_ids) - visible
    if invalid:
        raise BizError(
            AUTH_403,
            message=f"部分用户 ID 不在您的管理范围 (共 {len(invalid)} 条)",
            details={"out_of_scope_user_ids": sorted(invalid)[:10]},
        )
