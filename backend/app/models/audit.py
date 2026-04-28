"""L8 运维审计层 + 用户级权限覆盖.

- OperationLog          所有写操作审计
- UserPagePermission    用户级 page perm 覆盖 (优先于角色默认)
- UserButtonPermission  用户级 button perm 覆盖
- DefaultRolePermission 角色默认权限模板
"""
from __future__ import annotations

from sqlalchemy import ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base
from app.models._mixins import IDMixin, TimestampMixin


class OperationLog(Base, IDMixin, TimestampMixin):
    """所有写操作 + 登录登出 + reveal cookie 等敏感读操作."""

    __tablename__ = "operation_logs"

    user_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("users.id"), nullable=True, index=True
    )
    organization_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("organizations.id"), nullable=True, index=True
    )

    action: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    module: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    target_type: Mapped[str | None] = mapped_column(String(50), nullable=True)
    target_id: Mapped[str | None] = mapped_column(String(100), nullable=True, index=True)

    detail: Mapped[str | None] = mapped_column(Text, nullable=True)  # JSON
    ip: Mapped[str | None] = mapped_column(String(64), nullable=True)
    user_agent: Mapped[str | None] = mapped_column(String(255), nullable=True)
    trace_id: Mapped[str | None] = mapped_column(String(16), nullable=True, index=True)

    success: Mapped[bool] = mapped_column(Integer, default=1, nullable=False)


class UserPagePermission(Base, IDMixin):
    """用户级 page perm 覆盖. 优先于角色默认."""

    __tablename__ = "user_page_permissions"

    user_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("users.id"), nullable=False, index=True
    )
    permission_code: Mapped[str] = mapped_column("page_key", String(100), nullable=False)
    granted: Mapped[int] = mapped_column("is_allowed", Integer, default=1, nullable=False)
    # granted=1 显式赋予, 0 显式拒绝 (覆盖默认)

    __table_args__ = (
        UniqueConstraint("user_id", "page_key", name="uq_user_page_perm"),
    )


class UserButtonPermission(Base, IDMixin):
    __tablename__ = "user_button_permissions"

    user_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("users.id"), nullable=False, index=True
    )
    permission_code: Mapped[str] = mapped_column("button_key", String(100), nullable=False)
    granted: Mapped[int] = mapped_column("is_allowed", Integer, default=1, nullable=False)

    __table_args__ = (
        UniqueConstraint("user_id", "button_key", name="uq_user_btn_perm"),
    )


class DefaultRolePermission(Base, IDMixin):
    """角色默认权限模板. 由 init_db / 设置页改."""

    __tablename__ = "default_role_permissions"

    role: Mapped[str] = mapped_column(String(20), nullable=False, index=True)
    permission_type: Mapped[str] = mapped_column(String(50), nullable=False)
    # 'page' / 'button'
    permission_code: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    granted: Mapped[int] = mapped_column(Integer, default=1, nullable=False)

    __table_args__ = (
        UniqueConstraint("role", "permission_type", "permission_code",
                         name="uq_role_perm_type_code"),
    )
