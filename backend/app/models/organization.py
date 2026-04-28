"""L1 租户机构层 — 数据隔离的核心边界.

KS184 蓝图核心: 几乎所有 L3-L7 数据通过 organization_id 过滤.
我们 AI 层 (L9-L11) 也默认按租户隔离, 跨租户聚合需显式开关.
"""
from __future__ import annotations

from sqlalchemy import Boolean, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.db import Base
from app.models._mixins import IDMixin, SoftDeleteMixin, TimestampMixin


class Organization(Base, IDMixin, TimestampMixin, SoftDeleteMixin):
    """MCN 机构 / 团队 / 工作室.

    一个 Organization 拥有:
      - 多个 User (L2)
      - 多个 Account (L3)
      - 多套 Plan / Task (L4 / L5)
      - 独立的 AI 记忆 / 决策池
    """

    __tablename__ = "organizations"

    name: Mapped[str] = mapped_column(String(200), nullable=False)
    org_code: Mapped[str] = mapped_column(
        String(50), unique=True, nullable=False, index=True
    )  # 例: 'huanghua', 'cpkj888'
    org_type: Mapped[str] = mapped_column(
        String(32), default="mcn", nullable=False
    )  # mcn / studio / personal

    # 联系人
    contact_name: Mapped[str | None] = mapped_column(String(100), nullable=True)
    contact_phone: Mapped[str | None] = mapped_column(String(32), nullable=True)
    contact_email: Mapped[str | None] = mapped_column(String(200), nullable=True)

    # 套餐 / 限额
    plan_tier: Mapped[str] = mapped_column(
        String(32), default="basic", nullable=False
    )  # basic / pro / team / enterprise
    max_accounts: Mapped[int] = mapped_column(Integer, default=10, nullable=False)
    max_users: Mapped[int] = mapped_column(Integer, default=3, nullable=False)

    # 租户级配置 JSON (覆盖全局 default)
    settings_json: Mapped[str | None] = mapped_column(Text, nullable=True)

    # 状态
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    # 关系 — 延迟加载, 避免循环 import
    users: Mapped[list["User"]] = relationship(  # noqa: F821
        back_populates="organization", lazy="selectin"
    )
