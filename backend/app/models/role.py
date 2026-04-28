"""L2 角色与权限.

简化 RBAC:
  Role     角色 (admin / operator / viewer / 自定义)
  Permission 资源-动作 (e.g. account:read, drama:publish)
  RolePermission 多对多
  UserRole       多对多 (一个 user 可有多角色)
"""
from __future__ import annotations

from sqlalchemy import Boolean, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base
from app.models._mixins import IDMixin, TimestampMixin


class Role(Base, IDMixin, TimestampMixin):
    """角色 — 系统内置 + 租户自定义."""

    __tablename__ = "roles"

    organization_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("organizations.id"), nullable=True, index=True
    )
    code: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    is_builtin: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    __table_args__ = (
        UniqueConstraint("organization_id", "code", name="uq_role_org_code"),
    )


class Permission(Base, IDMixin, TimestampMixin):
    """权限点 — 形如 "account:read" "drama:publish"."""

    __tablename__ = "permissions"

    code: Mapped[str] = mapped_column(String(100), unique=True, nullable=False, index=True)
    resource: Mapped[str] = mapped_column(String(50), nullable=False)  # account / drama / ...
    action: Mapped[str] = mapped_column(String(50), nullable=False)    # read / write / publish ...
    description: Mapped[str | None] = mapped_column(Text, nullable=True)


class RolePermission(Base, IDMixin):
    """角色↔权限 多对多."""

    __tablename__ = "role_permissions"

    role_id: Mapped[int] = mapped_column(Integer, ForeignKey("roles.id"), nullable=False)
    permission_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("permissions.id"), nullable=False
    )

    __table_args__ = (
        UniqueConstraint("role_id", "permission_id", name="uq_role_perm"),
    )


class UserRole(Base, IDMixin):
    """用户↔角色 多对多."""

    __tablename__ = "user_roles"

    user_id: Mapped[int] = mapped_column(Integer, ForeignKey("users.id"), nullable=False)
    role_id: Mapped[int] = mapped_column(Integer, ForeignKey("roles.id"), nullable=False)

    __table_args__ = (
        UniqueConstraint("user_id", "role_id", name="uq_user_role"),
    )
