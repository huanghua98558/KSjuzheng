"""统计 / Dashboard schemas."""
from __future__ import annotations

from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel


class TrendPoint(BaseModel):
    date: str  # 'YYYY-MM-DD'
    count: int = 0
    success: int = 0
    fail: int = 0


class SuccessRatio(BaseModel):
    success: int = 0
    fail: int = 0


class StatisticsOverview(BaseModel):
    total_accounts: int
    mcn_accounts: int
    total_executions: int
    today_executions: int
    today_success: int = 0
    today_fail: int = 0
    today_success_rate: float = 0.0
    trend_7d: list[TrendPoint] = []
    success_ratio_30d: SuccessRatio = SuccessRatio()


class TodayCard(BaseModel):
    total_accounts: int
    mcn_accounts: int
    today_executions: int
    today_success: int = 0
    today_fail: int = 0
    today_success_rate: float = 0.0
    avg_duration_ms: float = 0.0


class ExecutionStatRow(BaseModel):
    date: str
    exec_count: int = 0
    success_count: int = 0
    fail_count: int = 0
    success_rate: float = 0.0
    avg_duration_ms: float = 0.0


class ExecutionStatsQuery(BaseModel):
    start: date | None = None
    end: date | None = None
    uid: str | None = None
    page: int = 1
    size: int = 50
