"""用户管理 + 机构 schemas."""
from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


# ============================================================
# User
# ============================================================

class UserDetail(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    organization_id: int
    username: str
    phone: str | None = None
    email: str | None = None
    display_name: str | None = None
    role: str
    level: int
    parent_user_id: int | None = None
    commission_rate: float
    commission_rate_visible: bool = True
    commission_amount_visible: bool = True
    total_income_visible: bool = True
    account_quota: int | None = None
    is_active: bool
    is_superadmin: bool
    must_change_pw: bool
    last_login_at: datetime | None = None
    created_at: datetime


class UserCreate(BaseModel):
    username: str = Field(..., min_length=2, max_length=50)
    password: str = Field(..., min_length=6, max_length=128)
    phone: str | None = None
    display_name: str | None = None
    organization_id: int | None = None  # 默认取 creator 的
    role: Literal["operator", "captain", "normal_user"] = "normal_user"
    parent_user_id: int | None = None
    commission_rate: float = Field(0.80, ge=0.0, le=1.0)
    account_quota: int | None = None


class UserUpdate(BaseModel):
    display_name: str | None = None
    phone: str | None = None
    email: str | None = None


class UserStatusUpdate(BaseModel):
    is_active: bool


class UserPasswordReset(BaseModel):
    new_password: str = Field(..., min_length=6, max_length=128)


class UserCommissionUpdate(BaseModel):
    commission_rate: float = Field(..., ge=0.0, le=1.0)


class UserCommissionVisibility(BaseModel):
    commission_rate_visible: bool | None = None
    commission_amount_visible: bool | None = None
    total_income_visible: bool | None = None


class UserRoleUpdate(BaseModel):
    role: Literal["super_admin", "operator", "captain", "normal_user"]


class UserPermissionsUpdate(BaseModel):
    page_grants: list[str] = Field(default_factory=list)
    page_denies: list[str] = Field(default_factory=list)
    button_grants: list[str] = Field(default_factory=list)
    button_denies: list[str] = Field(default_factory=list)


class UserPermissionsView(BaseModel):
    role_default_page: list[str]
    role_default_button: list[str]
    user_page_grants: list[str]
    user_page_denies: list[str]
    user_button_grants: list[str]
    user_button_denies: list[str]
    effective: list[str]


# ============================================================
# Organization
# ============================================================

class OrganizationPublic(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    name: str
    org_code: str
    org_type: str
    contact_name: str | None = None
    contact_phone: str | None = None
    contact_email: str | None = None
    plan_tier: str
    max_accounts: int
    max_users: int
    is_active: bool
    notes: str | None = None
    created_at: datetime


class OrganizationCreate(BaseModel):
    name: str = Field(..., max_length=200)
    org_code: str = Field(..., max_length=50)
    org_type: str = "mcn"
    contact_name: str | None = None
    contact_phone: str | None = None
    contact_email: str | None = None
    plan_tier: str = "basic"
    max_accounts: int = 10
    max_users: int = 3
    notes: str | None = None


class OrganizationUpdate(BaseModel):
    name: str | None = None
    contact_name: str | None = None
    contact_phone: str | None = None
    contact_email: str | None = None
    plan_tier: str | None = None
    max_accounts: int | None = None
    max_users: int | None = None
    is_active: bool | None = None
    notes: str | None = None
