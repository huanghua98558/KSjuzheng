"""任务记录写入 + 简单查询 service.

被 publish 流程 (Phase 3) 调用. 此处提供写 API + worker 用聚合.
"""
from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy.orm import Session

from app.models import AccountTaskRecord


def write_task_record(
    db: Session,
    *,
    account_id: int,
    organization_id: int,
    task_type: str,
    success: bool,
    drama_id: int | None = None,
    drama_name: str | None = None,
    duration_ms: int | None = None,
    error_message: str | None = None,
) -> AccountTaskRecord:
    """记录一条任务执行结果. 调用方负责 db.commit()."""
    r = AccountTaskRecord(
        account_id=account_id,
        organization_id=organization_id,
        task_type=task_type,
        drama_id=drama_id,
        drama_name=drama_name,
        success=success,
        duration_ms=duration_ms,
        error_message=error_message,
    )
    db.add(r)
    db.flush()
    return r
