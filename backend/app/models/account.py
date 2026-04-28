"""L3 账号资产层 — 软件账号 / KS账号 / 云Cookie / 分组 / 邀约 / 任务记录."""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    BLOB,
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base
from app.models._mixins import IDMixin, SoftDeleteMixin, TimestampMixin


# ============================================================
# 软件账号 (主表)
# ============================================================

class Account(Base, IDMixin, TimestampMixin, SoftDeleteMixin):
    """软件账号 — KS184 称 'accounts', 是矩阵主资源."""

    __tablename__ = "accounts"

    # ★ 双隔离边界
    organization_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("organizations.id"), nullable=False, index=True
    )
    assigned_user_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("users.id"), nullable=True, index=True
    )
    group_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("account_groups.id"), nullable=True, index=True
    )

    # 快手账号身份
    kuaishou_id: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    real_uid: Mapped[str | None] = mapped_column(String(32), nullable=True, index=True)
    nickname: Mapped[str | None] = mapped_column(String(100), nullable=True)

    # 状态
    status: Mapped[str] = mapped_column(
        String(20), default="active", nullable=False, index=True
    )  # active / disabled / deleted
    mcn_status: Mapped[str | None] = mapped_column(String(20), nullable=True, index=True)
    sign_status: Mapped[str | None] = mapped_column(String(20), nullable=True, index=True)
    cookie_status: Mapped[str | None] = mapped_column(String(20), nullable=True)
    cookie_last_success_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    # 收益相关
    commission_rate: Mapped[float] = mapped_column(Float, default=0.80, nullable=False)

    # 设备
    device_serial: Mapped[str | None] = mapped_column(String(64), nullable=True)

    # 元数据
    remark: Mapped[str | None] = mapped_column(Text, nullable=True)
    imported_by_user_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("users.id"), nullable=True
    )
    imported_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


# ============================================================
# 分组
# ============================================================

class AccountGroup(Base, IDMixin, TimestampMixin):
    __tablename__ = "account_groups"

    organization_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("organizations.id"), nullable=False, index=True
    )
    owner_user_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("users.id"), nullable=True, index=True
    )
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    color: Mapped[str | None] = mapped_column(String(20), nullable=True)


# ============================================================
# KS 账号 / 设备绑定
# ============================================================

class KsAccount(Base, IDMixin, TimestampMixin):
    __tablename__ = "ks_accounts"

    organization_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("organizations.id"), nullable=True, index=True
    )
    account_name: Mapped[str | None] = mapped_column(String(100), nullable=True)
    kuaishou_uid: Mapped[str] = mapped_column(
        String(32), unique=True, nullable=False, index=True
    )
    device_code: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)


# ============================================================
# 云端 Cookie 账号
# ============================================================

class KuaishouAccountBinding(Base, IDMixin, TimestampMixin):
    __tablename__ = "kuaishou_account_bindings"

    source_id: Mapped[int | None] = mapped_column(Integer, unique=True, nullable=True, index=True)
    account_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("accounts.id"), nullable=True, index=True
    )
    user_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("users.id"), nullable=True, index=True
    )

    kuaishou_id: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    machine_id: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    operator_account: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    bind_time: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_used_time: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    status: Mapped[str] = mapped_column(String(20), default="active", nullable=False, index=True)
    remark: Mapped[str | None] = mapped_column(String(255), nullable=True)


class CloudCookieAccount(Base, IDMixin, TimestampMixin):
    """云端 Cookie 加密入库, 默认对外脱敏.

    AES-256-GCM 加密: cookie_ciphertext = enc(plain), iv 随机, tag 校验.
    """

    __tablename__ = "cloud_cookie_accounts"

    organization_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("organizations.id"), nullable=False, index=True
    )
    assigned_user_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("users.id"), nullable=True, index=True
    )
    account_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("accounts.id"), nullable=True, index=True
    )

    uid: Mapped[str | None] = mapped_column(String(32), nullable=True, index=True)
    nickname: Mapped[str | None] = mapped_column(String(100), nullable=True)
    owner_code: Mapped[str | None] = mapped_column(String(50), nullable=True, index=True)

    cookie_ciphertext: Mapped[bytes | None] = mapped_column(BLOB, nullable=True)
    cookie_iv: Mapped[bytes | None] = mapped_column(BLOB, nullable=True)
    cookie_tag: Mapped[bytes | None] = mapped_column(BLOB, nullable=True)
    cookie_preview: Mapped[str | None] = mapped_column(String(80), nullable=True)
    # 形如 "ses=eyJ***...***"
    login_status: Mapped[str] = mapped_column(
        String(20), default="unknown", nullable=False, index=True
    )  # valid / expired / unknown
    last_success_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    imported_by_user_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("users.id"), nullable=True
    )


# ============================================================
# MCN 授权状态
# ============================================================

class McnAuthorization(Base, IDMixin, TimestampMixin):
    __tablename__ = "mcn_authorizations"

    account_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("accounts.id"), nullable=False, index=True
    )
    organization_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("organizations.id"), nullable=False, index=True
    )
    mcn_status: Mapped[str | None] = mapped_column(String(20), nullable=True)
    sign_status: Mapped[str | None] = mapped_column(String(20), nullable=True)
    invite_status: Mapped[str | None] = mapped_column(String(20), nullable=True)
    authorized_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    invited_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    __table_args__ = (
        UniqueConstraint("account_id", "organization_id", name="uq_mcn_auth_acc_org"),
    )


# ============================================================
# 邀约记录
# ============================================================

class InvitationRecord(Base, IDMixin, TimestampMixin):
    __tablename__ = "invitation_records"

    account_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("accounts.id"), nullable=False, index=True
    )
    organization_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("organizations.id"), nullable=False, index=True
    )
    invite_type: Mapped[str | None] = mapped_column(String(32), nullable=True)
    status: Mapped[str | None] = mapped_column(String(20), nullable=True)
    result: Mapped[str | None] = mapped_column(Text, nullable=True)


# ============================================================
# 任务执行记录
# ============================================================

class AccountTaskRecord(Base, IDMixin, TimestampMixin):
    """每条任务执行结果. Dashboard 聚合用."""

    __tablename__ = "account_task_records"

    account_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("accounts.id"), nullable=False, index=True
    )
    organization_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("organizations.id"), nullable=False, index=True
    )
    task_type: Mapped[str] = mapped_column(String(32), nullable=False)
    drama_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    drama_name: Mapped[str | None] = mapped_column(String(200), nullable=True)
    success: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    duration_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
