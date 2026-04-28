"""L2 用户层 — 内部用户 (运营 / 管理员 / 队长 / 普通用户)."""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.db import Base
from app.models._mixins import IDMixin, SoftDeleteMixin, TimestampMixin


class User(Base, IDMixin, TimestampMixin, SoftDeleteMixin):
    """系统用户.

    可通过 username 或 phone 登录, 一个 User 必属于一个 Organization.
    """

    __tablename__ = "users"

    organization_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("organizations.id"), nullable=False, index=True
    )

    # 凭证
    username: Mapped[str] = mapped_column(
        String(50), unique=True, nullable=False, index=True
    )
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    phone: Mapped[str | None] = mapped_column(String(32), unique=True, nullable=True, index=True)
    email: Mapped[str | None] = mapped_column(String(200), nullable=True)

    # 资料
    display_name: Mapped[str | None] = mapped_column(String(100), nullable=True)
    avatar_url: Mapped[str | None] = mapped_column(String(500), nullable=True)

    # ★ 角色与上下级 (RBAC + 团队结构)
    role: Mapped[str] = mapped_column(
        String(20), default="normal_user", nullable=False, index=True
    )  # super_admin / operator / captain / normal_user
    level: Mapped[int] = mapped_column(Integer, default=10, nullable=False)
    parent_user_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("users.id"), nullable=True, index=True
    )

    # ★ 收益相关
    commission_rate: Mapped[float] = mapped_column(Float, default=0.80, nullable=False)
    commission_rate_visible: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    commission_amount_visible: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    total_income_visible: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    # ★ 配额
    account_quota: Mapped[int | None] = mapped_column(Integer, nullable=True)

    # 状态
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    is_superadmin: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    must_change_pw: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    # 安全
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_login_ip: Mapped[str | None] = mapped_column(String(64), nullable=True)
    failed_login_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    locked_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    # 关系
    organization: Mapped["Organization"] = relationship(  # noqa: F821
        back_populates="users", lazy="joined"
    )


class UserSession(Base, IDMixin, TimestampMixin):
    """活跃 session — refresh token + 硬件指纹绑定."""

    __tablename__ = "user_sessions"

    user_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("users.id"), nullable=False, index=True
    )

    jti: Mapped[str] = mapped_column(String(64), unique=True, nullable=False, index=True)

    fingerprint: Mapped[str | None] = mapped_column(String(64), nullable=True)
    user_agent: Mapped[str | None] = mapped_column(Text, nullable=True)
    ip: Mapped[str | None] = mapped_column(String(64), nullable=True)

    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    revoked: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    last_seen_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
