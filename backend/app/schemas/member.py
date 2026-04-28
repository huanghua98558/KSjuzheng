"""成员 / 违规作品 schemas."""
from __future__ import annotations

from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


# ============================================================
# OrgMember
# ============================================================

class OrgMemberPublic(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    organization_id: int
    member_id: int
    user_id: int | None = None
    account_id: int | None = None
    nickname: str | None = None
    avatar: str | None = None
    fans_count: int = 0
    broker_name: str | None = None
    cooperation_type: str | None = None
    content_category: str | None = None
    mcn_level: str | None = None
    renewal_status: str | None = None
    contract_expires_at: date | None = None
    synced_at: datetime | None = None


# ============================================================
# Spark / Firefly / Fluorescent Member
# ============================================================

class SparkMemberPublic(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    organization_id: int
    member_id: int
    account_id: int | None = None
    nickname: str | None = None
    fans_count: int = 0
    broker_name: str | None = None
    task_count: int = 0
    hidden: bool = False
    first_release_id: str | None = None
    synced_at: datetime | None = None


class FireflyMemberPublic(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    organization_id: int
    member_id: int
    account_id: int | None = None
    nickname: str | None = None
    fans_count: int = 0
    broker_name: str | None = None
    total_amount: float = 0.0
    org_task_num: int = 0
    hidden: bool = False
    synced_at: datetime | None = None


class FluorescentMemberPublic(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    organization_id: int
    member_id: int
    account_id: int | None = None
    nickname: str | None = None
    fans_count: int = 0
    broker_name: str | None = None
    total_amount: float = 0.0
    org_task_num: int = 0
    synced_at: datetime | None = None


# ============================================================
# MemberQuery (★ 高敏)
# ============================================================

class MemberQueryRequest(BaseModel):
    """按 UID 列表查询. 严格白名单: 全部 UID 必须在 scope.account_uids."""

    uids: list[str] = Field(..., min_length=1, max_length=200)
    start: date | None = None
    end: date | None = None
    program_type: Literal["all", "spark", "firefly", "fluorescent"] = "all"


class MemberQueryRow(BaseModel):
    uid: str
    nickname: str | None = None
    fans_count: int = 0
    program_type: str = ""
    total_income: float = 0.0
    total_tasks: int = 0
    last_income_date: date | None = None


class MemberQueryResponse(BaseModel):
    items: list[MemberQueryRow]
    summary: dict


# ============================================================
# Violation
# ============================================================

class ViolationPhotoPublic(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    organization_id: int
    account_id: int | None = None
    work_id: str
    uid: str | None = None
    thumbnail: str | None = None
    description: str | None = None
    business_type: str | None = None
    violation_reason: str | None = None
    view_count: int = 0
    like_count: int = 0
    appeal_status: str | None = None
    appeal_reason: str | None = None
    published_at: datetime | None = None
    detected_at: datetime | None = None
    created_at: datetime


class ViolationUpdate(BaseModel):
    appeal_status: Literal["none", "submitted", "approved", "rejected"] | None = None
    appeal_reason: str | None = None
    description: str | None = None


class ViolationListQuery(BaseModel):
    page: int = 1
    size: int = 50
    keyword: str | None = None
    business_type: str | None = None
    appeal_status: str | None = None
    start: datetime | None = None
    end: datetime | None = None
