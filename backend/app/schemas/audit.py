"""审计 schemas."""
from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict


class OperationLogPublic(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    user_id: int | None = None
    organization_id: int | None = None
    action: str
    module: str
    target_type: str | None = None
    target_id: str | None = None
    detail: str | None = None
    ip: str | None = None
    user_agent: str | None = None
    trace_id: str | None = None
    success: int = 1
    created_at: datetime


class AuditLogQuery(BaseModel):
    page: int = 1
    size: int = 50
    user: str | None = None
    action: str | None = None
    module: str | None = None
    target_type: str | None = None
    start: datetime | None = None
    end: datetime | None = None


class AuditLogStats(BaseModel):
    total: int
    by_module: dict[str, int]
    by_action: dict[str, int]
    last_7d: list[dict]
