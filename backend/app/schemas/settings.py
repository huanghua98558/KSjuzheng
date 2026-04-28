"""公告 + 系统配置 schemas."""
from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


# ============================================================
# Announcement
# ============================================================

class AnnouncementPublic(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    organization_id: int | None = None
    title: str
    content: str
    level: str = "info"
    pinned: bool = False
    active: bool = True
    start_at: datetime | None = None
    end_at: datetime | None = None
    created_by_user_id: int | None = None
    created_at: datetime


class AnnouncementCreate(BaseModel):
    organization_id: int | None = None
    title: str = Field(..., min_length=1, max_length=200)
    content: str = Field(..., min_length=1)
    level: Literal["info", "warning", "urgent"] = "info"
    pinned: bool = False
    active: bool = True
    start_at: datetime | None = None
    end_at: datetime | None = None


class AnnouncementUpdate(BaseModel):
    title: str | None = None
    content: str | None = None
    level: Literal["info", "warning", "urgent"] | None = None
    pinned: bool | None = None
    active: bool | None = None
    start_at: datetime | None = None
    end_at: datetime | None = None


# ============================================================
# Settings — Basic
# ============================================================

class SettingsBasic(BaseModel):
    """系统基本信息 — 给设置页 + 关于页用."""

    app_name: str
    app_version: str
    app_env: str
    timezone: str
    db_url_masked: str  # 例: 'sqlite:///./data/ksjuzheng.db' or 'postgresql+psycopg://***@host:5432/db'
    has_crypto: bool
    has_redis: bool
    cors_origins: list[str]
    server_time: datetime


class SettingsBasicUpdate(BaseModel):
    """改部分非敏感配置."""

    cors_origins: list[str] | None = None
    log_level: str | None = None


class AboutInfo(BaseModel):
    name: str
    version: str
    build_date: str | None = None
    license: str = "Internal"
    description: str = "KS矩阵后端 — KS184 业务中台 + AI 自动化"
    links: dict = Field(default_factory=lambda: {
        "blueprint": "docs/服务器后端完整蓝图_含AI自动化v1.md",
        "api_doc": "/docs",
    })


# ============================================================
# Role-defaults — 默认权限模板
# ============================================================

class RoleDefaultsRow(BaseModel):
    role: str
    permission_type: Literal["page", "button"]
    permission_code: str


class RoleDefaultsListResponse(BaseModel):
    items: list[RoleDefaultsRow]
    role_summary: dict  # {role: {page: int, button: int}}


class RoleDefaultsUpdate(BaseModel):
    role: Literal["super_admin", "operator", "captain", "normal_user"]
    page_codes: list[str] = Field(default_factory=list)
    button_codes: list[str] = Field(default_factory=list)
