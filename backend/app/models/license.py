"""L13 SaaS 卡密 (License).

激活流程:
  1. 客户端 exe 首启输入卡密 + 手机号
  2. 客户端计算 fingerprint = sha256(cpu_id + mb_sn + disk_sn)[:32]
  3. POST /api/client/auth/activate
     - 服务器校验 license_key 存在 + 未过期 + 未绑定其他指纹
     - 绑定 device_fingerprint
     - 返 JWT + refresh + plan + expires_at

后续登录: 校验 fingerprint == license.device_fingerprint, 不匹配 → AUTH_498.
"""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base
from app.models._mixins import IDMixin, TimestampMixin


class License(Base, IDMixin, TimestampMixin):
    """卡密 — 一卡一指纹一用户."""

    __tablename__ = "licenses"

    # 卡密本体
    license_key: Mapped[str] = mapped_column(
        String(64), unique=True, nullable=False, index=True
    )

    # 套餐
    plan_tier: Mapped[str] = mapped_column(
        String(32), default="basic", nullable=False
    )  # basic / pro / team / enterprise
    max_accounts: Mapped[int] = mapped_column(Integer, default=10, nullable=False)
    features_json: Mapped[str | None] = mapped_column(Text, nullable=True)  # 启用的特性 list

    # 时效
    issued_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    activated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    # 设备绑定 (激活后写入)
    device_fingerprint: Mapped[str | None] = mapped_column(
        String(64), nullable=True, index=True
    )
    device_os_info: Mapped[str | None] = mapped_column(Text, nullable=True)
    client_version: Mapped[str | None] = mapped_column(String(32), nullable=True)

    # 关联用户 / 租户 (激活后填充)
    bound_user_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("users.id"), nullable=True, index=True
    )
    bound_organization_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("organizations.id"), nullable=True, index=True
    )
    bound_phone: Mapped[str | None] = mapped_column(String(32), nullable=True)

    # 状态
    status: Mapped[str] = mapped_column(
        String(20), default="unused", nullable=False, index=True
    )  # unused / active / expired / revoked / locked
    revoke_reason: Mapped[str | None] = mapped_column(Text, nullable=True)

    # 审计
    created_by_user_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("users.id"), nullable=True
    )

    @property
    def is_expired(self) -> bool:
        from datetime import timezone
        exp = self.expires_at
        if exp is None:
            return True
        if exp.tzinfo is None:
            exp = exp.replace(tzinfo=timezone.utc)
        return datetime.now(timezone.utc) > exp

    @property
    def is_active_now(self) -> bool:
        return self.status == "active" and not self.is_expired
