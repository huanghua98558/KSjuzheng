"""收益结算 + 钱包 schemas."""
from __future__ import annotations

from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


# ============================================================
# 通用收益记录
# ============================================================

class IncomeRecordPublic(BaseModel):
    """单条收益明细. 注意: commission_rate / commission_amount / total_amount
    会按 user.commission_*_visible 在 service 层脱敏 (None)."""

    model_config = ConfigDict(from_attributes=True)
    id: int
    organization_id: int
    program_type: str | None = None
    member_id: int
    account_id: int | None = None
    task_id: str | None = None
    task_name: str | None = None
    income_amount: float | None = None
    commission_rate: float | None = None
    commission_amount: float | None = None
    income_date: date | None = None
    settlement_status: str | None = None
    archived_year_month: str | None = None
    created_at: datetime


class IncomeListQuery(BaseModel):
    page: int = 1
    size: int = 50
    keyword: str | None = None
    member_id: int | None = None
    account_id: int | None = None
    settlement_status: str | None = None
    start: date | None = None
    end: date | None = None
    archived_year_month: str | None = None  # '2026-04'


class IncomeStats(BaseModel):
    total_amount: float = 0.0
    settled_amount: float = 0.0
    pending_amount: float = 0.0
    record_count: int = 0
    member_count: int = 0
    by_month: list[dict] = Field(default_factory=list)


# ============================================================
# Excel 导入
# ============================================================

class IncomeImportItem(BaseModel):
    member_id: int
    task_id: str | None = None
    task_name: str | None = None
    income_amount: float = 0.0
    commission_rate: float | None = None
    commission_amount: float | None = None
    income_date: date | None = None
    archived_year_month: str | None = None


class IncomeImportRequest(BaseModel):
    program_type: Literal["spark", "firefly", "fluorescent"]
    items: list[IncomeImportItem] = Field(..., min_length=1, max_length=10000)


class IncomeImportResult(BaseModel):
    inserted: int
    skipped: int
    errors: list[str] = Field(default_factory=list)


# ============================================================
# 归档 + 结算
# ============================================================

class IncomeArchivePublic(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    organization_id: int
    program_type: str
    year: int
    month: int
    member_id: int
    account_id: int | None = None
    total_amount: float | None = None
    commission_rate: float | None = None
    commission_amount: float | None = None
    settlement_status: str = "pending"
    archived_at: datetime | None = None


class ArchiveListQuery(BaseModel):
    page: int = 1
    size: int = 50
    program_type: Literal["spark", "firefly", "fluorescent"] | None = None
    year: int | None = None
    month: int | None = None
    settlement_status: str | None = None


class BatchSettlementRequest(BaseModel):
    archive_ids: list[int] = Field(..., min_length=1, max_length=500)
    remark: str | None = None


class SingleSettlementRequest(BaseModel):
    remark: str | None = None


class ArchiveStats(BaseModel):
    total_count: int = 0
    settled_count: int = 0
    pending_count: int = 0
    total_amount: float = 0.0
    settled_amount: float = 0.0


# ============================================================
# 钱包
# ============================================================

class WalletPublic(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    user_id: int
    alipay_name: str | None = None
    alipay_account: str | None = None
    bank_name: str | None = None
    bank_account: str | None = None
    real_name: str | None = None
    notes: str | None = None
    created_at: datetime
    updated_at: datetime


class WalletUpdate(BaseModel):
    alipay_name: str | None = None
    alipay_account: str | None = None
    bank_name: str | None = None
    bank_account: str | None = None
    real_name: str | None = None
    notes: str | None = None
