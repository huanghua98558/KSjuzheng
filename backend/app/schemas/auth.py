"""认证相关 schema."""
from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class UserPublic(BaseModel):
    """对外暴露的 user 资料 (脱敏, 不含 password / hash)."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    username: str
    organization_id: int
    display_name: str | None = None
    phone: str | None = None
    is_superadmin: bool = False
    must_change_pw: bool = False
    role: Literal["admin", "operator", "viewer"] = "operator"


# ---- 登录 ----

class LoginRequest(BaseModel):
    username: str | None = Field(None, max_length=50)
    phone: str | None = Field(None, max_length=32)
    password: str = Field(..., min_length=1, max_length=128)
    fingerprint: str | None = Field(None, max_length=64)
    client_version: str | None = None


class LoginResponse(BaseModel):
    token: str
    refresh_token: str
    expires_at: datetime
    user: UserPublic
    plan_tier: str | None = None


# ---- 激活 (卡密) ----

class ActivateRequest(BaseModel):
    license_key: str = Field(..., min_length=8, max_length=64)
    phone: str = Field(..., max_length=32)
    fingerprint: str = Field(..., min_length=8, max_length=64)
    client_version: str | None = None
    os_info: str | None = None


class ActivateResponse(BaseModel):
    token: str
    refresh_token: str
    expires_at: datetime
    user: UserPublic
    plan_tier: str
    license_expires_at: datetime
    initial_password: str | None = None  # 首次激活: 系统生成密码, 提示用户保存


# ---- Refresh ----

class RefreshRequest(BaseModel):
    refresh_token: str
    fingerprint: str | None = None


class RefreshResponse(BaseModel):
    token: str
    refresh_token: str | None = None  # 滚动续期 (rotation), 旧 refresh 作废
    expires_at: datetime


# ---- Heartbeat ----

class HeartbeatRequest(BaseModel):
    fingerprint: str | None = None


class HeartbeatResponse(BaseModel):
    server_time: datetime
    server_version: str
    license_status: Literal["active", "expiring_soon", "expired"]
    expires_at: datetime | None = None
    days_left: int | None = None
