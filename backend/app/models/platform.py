"""L0 平台层 — 全局配置 / 服务状态.

跨租户 (organization_id 为空) 的全局信息.
"""
from __future__ import annotations

from sqlalchemy import Boolean, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base
from app.models._mixins import IDMixin, TimestampMixin


class GlobalConfig(Base, IDMixin, TimestampMixin):
    """app_config 等价 — key/value 全局配置.

    沿用 ks_automation 现有 app_config 设计:
      - value 用 TEXT 存原值
      - value_type 用于客户端 coerce
      - description 给运维看
    """

    __tablename__ = "global_configs"

    key: Mapped[str] = mapped_column(String(200), unique=True, nullable=False, index=True)
    value: Mapped[str] = mapped_column(Text, nullable=False, default="")
    value_type: Mapped[str] = mapped_column(
        String(16), default="string", nullable=False
    )  # string / int / float / bool / json
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    is_secret: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)


class ServiceStatus(Base, IDMixin, TimestampMixin):
    """服务在线状态 — 启动时记录, /readyz 用."""

    __tablename__ = "service_statuses"

    service_name: Mapped[str] = mapped_column(String(100), nullable=False)
    status: Mapped[str] = mapped_column(String(32), default="ok", nullable=False)
    detail: Mapped[str | None] = mapped_column(Text, nullable=True)
