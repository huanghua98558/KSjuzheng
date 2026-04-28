"""账号资产层 schemas."""
from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


# ============================================================
# Account
# ============================================================

class AccountPublic(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    organization_id: int
    assigned_user_id: int | None = None
    group_id: int | None = None
    kuaishou_id: str | None = None
    real_uid: str | None = None
    nickname: str | None = None
    status: str = "active"
    mcn_status: str | None = None
    sign_status: str | None = None
    cookie_status: str | None = None
    cookie_last_success_at: datetime | None = None
    commission_rate: float
    device_serial: str | None = None
    remark: str | None = None
    created_at: datetime
    updated_at: datetime


class AccountCreate(BaseModel):
    organization_id: int | None = None  # None 自动取 user 的 org
    kuaishou_id: str | None = Field(None, max_length=64)
    real_uid: str | None = Field(None, max_length=32)
    nickname: str | None = Field(None, max_length=100)
    commission_rate: float = Field(0.80, ge=0.0, le=1.0)
    assigned_user_id: int | None = None
    group_id: int | None = None
    remark: str | None = None
    device_serial: str | None = None


class AccountUpdate(BaseModel):
    nickname: str | None = None
    status: Literal["active", "disabled"] | None = None
    commission_rate: float | None = Field(None, ge=0.0, le=1.0)
    assigned_user_id: int | None = None
    group_id: int | None = None
    remark: str | None = None


class AccountListQuery(BaseModel):
    page: int = 1
    size: int = 20
    keyword: str | None = None
    org_id: int | None = None
    group_id: int | None = None
    assigned_user_id: int | None = None
    status: Literal["active", "disabled", "deleted"] | None = None
    sign_status: str | None = None
    mcn_status: str | None = None
    commission_min: float | None = None
    commission_max: float | None = None
    sort: str = "created_at.desc"


class AccountBatchAuthorize(BaseModel):
    ids: list[int] = Field(..., min_length=1, max_length=500)


class AccountBatchAssign(BaseModel):
    ids: list[int] = Field(..., min_length=1, max_length=500)
    assigned_user_id: int


class AccountBatchSetGroup(BaseModel):
    ids: list[int] = Field(..., min_length=1, max_length=500)
    group_id: int | None = None


class AccountBatchCommission(BaseModel):
    ids: list[int] = Field(..., min_length=1, max_length=500)
    commission_rate: float = Field(..., ge=0.0, le=1.0)


class AccountBatchStatus(BaseModel):
    ids: list[int] = Field(..., min_length=1, max_length=500)
    status: Literal["active", "disabled"]


# ============================================================
# AccountGroup
# ============================================================

class AccountGroupPublic(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    organization_id: int
    owner_user_id: int | None
    name: str
    color: str | None = None


class AccountGroupCreate(BaseModel):
    name: str = Field(..., max_length=100)
    color: str | None = None


# ============================================================
# KsAccount
# ============================================================

class KsAccountPublic(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    organization_id: int | None
    account_name: str | None = None
    kuaishou_uid: str
    device_code: str | None = None
    created_at: datetime


# ============================================================
# CloudCookie
# ============================================================

class CloudCookiePublic(BaseModel):
    """对外: 默认不返回明文 cookie. 仅 cookie_preview."""

    model_config = ConfigDict(from_attributes=True)
    id: int
    organization_id: int
    assigned_user_id: int | None = None
    account_id: int | None = None
    uid: str | None = None
    nickname: str | None = None
    owner_code: str | None = None
    cookie_preview: str | None = None
    login_status: str = "unknown"
    last_success_at: datetime | None = None
    created_at: datetime


class CloudCookieCreate(BaseModel):
    uid: str | None = Field(None, max_length=32)
    nickname: str | None = Field(None, max_length=100)
    owner_code: str | None = None
    cookie: str = Field(..., min_length=10)  # 明文, 后端加密
    organization_id: int | None = None


class CloudCookieUpdate(BaseModel):
    nickname: str | None = None
    owner_code: str | None = None
    assigned_user_id: int | None = None
    account_id: int | None = None
    login_status: str | None = None


class CloudCookieReveal(BaseModel):
    cookie_plaintext: str
    revealed_at: datetime


class CloudCookieBatchUpdateOwner(BaseModel):
    ids: list[int] = Field(..., min_length=1)
    owner_code: str
