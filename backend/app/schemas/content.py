"""短剧池 / 高转化 / 链接统计 / 收藏记录 / 外部 URL schemas."""
from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


# ============================================================
# CollectPool
# ============================================================

class CollectPoolPublic(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    organization_id: int
    drama_name: str
    drama_url: str
    platform: str | None = None
    auth_code: str | None = None
    status: str = "active"
    abnormal_reason: str | None = None
    imported_by_user_id: int | None = None
    created_at: datetime
    updated_at: datetime


class CollectPoolCreate(BaseModel):
    drama_name: str = Field(..., min_length=1, max_length=200)
    drama_url: str = Field(..., min_length=1, max_length=1000)
    platform: str | None = Field(None, max_length=50)
    auth_code: str | None = None


class CollectPoolUpdate(BaseModel):
    drama_name: str | None = None
    drama_url: str | None = None
    platform: str | None = None
    auth_code: str | None = None
    status: Literal["active", "abnormal"] | None = None
    abnormal_reason: str | None = None


class CollectPoolBatchImport(BaseModel):
    """批量导入 — 一行一条 (drama_name, drama_url, platform?, auth_code?)."""

    items: list[CollectPoolCreate] = Field(..., min_length=1, max_length=10000)


class CollectPoolDeduplicateAndCopy(BaseModel):
    source_auth_code: str
    target_auth_code: str
    keep_source: bool = True


class CollectPoolListQuery(BaseModel):
    page: int = 1
    size: int = 50
    keyword: str | None = None
    platform: str | None = None
    auth_code: str | None = None
    status: Literal["active", "abnormal", "deleted"] | None = None
    abnormal: Literal["url_empty", "non_kuaishou", "chinese_in_url"] | None = None
    start: datetime | None = None
    end: datetime | None = None


# ============================================================
# HighIncomeDramas
# ============================================================

class HighIncomeDramaPublic(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    organization_id: int
    drama_name: str
    source_program: str | None = None
    source_income_id: int | None = None
    income_amount: float | None = None
    notes: str | None = None
    added_by_user_id: int | None = None
    created_at: datetime


class HighIncomeDramaCreate(BaseModel):
    drama_name: str = Field(..., min_length=1, max_length=200)
    source_program: Literal["firefly", "spark", "fluorescent", "manual"] = "manual"
    source_income_id: int | None = None
    income_amount: float | None = None
    notes: str | None = None


# ============================================================
# DramaLinkStatistic
# ============================================================

class DramaLinkStatPublic(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    organization_id: int
    drama_url: str
    drama_name: str | None = None
    task_type: str | None = None
    execute_count: int = 0
    success_count: int = 0
    failed_count: int = 0
    account_count: int = 0
    success_rate: float = 0.0
    last_executed_at: datetime | None = None


# ============================================================
# DramaCollectionRecord
# ============================================================

class DramaCollectionPublic(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    organization_id: int
    account_id: int | None = None
    account_uid: str
    account_name: str | None = None
    total_count: int = 0
    spark_count: int = 0
    firefly_count: int = 0
    fluorescent_count: int = 0
    last_collected_at: datetime | None = None


# ============================================================
# ExternalUrlStat
# ============================================================

class ExternalUrlPublic(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    organization_id: int | None = None
    url: str
    source_platform: str | None = None
    reference_count: int = 0
    last_seen_at: datetime | None = None
