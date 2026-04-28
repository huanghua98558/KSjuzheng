"""审计工具.

API:
  audit_log(db, *, user, action, module, ...)        函数式
  audit_request(request, db, *, action, module, ...) 含 IP / trace_id 自动取
  @audited(action='...', module='...')               装饰器 (尚未启用, Phase 2A 用函数式)
"""
from __future__ import annotations

import json
from typing import Any

from sqlalchemy.orm import Session

from app.core.logging import logger
from app.models import OperationLog, User


def audit_log(
    db: Session,
    *,
    user: User | None,
    action: str,
    module: str,
    target_type: str | None = None,
    target_id: str | int | None = None,
    detail: dict | None = None,
    ip: str | None = None,
    user_agent: str | None = None,
    trace_id: str | None = None,
    success: bool = True,
) -> OperationLog:
    """写一条审计. 由 service / api 显式调."""
    detail_json = None
    if detail:
        try:
            detail_json = json.dumps(detail, ensure_ascii=False, default=str)
        except Exception:
            detail_json = str(detail)[:1000]

    log = OperationLog(
        user_id=user.id if user else None,
        organization_id=user.organization_id if user else None,
        action=action,
        module=module,
        target_type=target_type,
        target_id=str(target_id) if target_id is not None else None,
        detail=detail_json,
        ip=ip,
        user_agent=user_agent,
        trace_id=trace_id,
        success=1 if success else 0,
    )
    db.add(log)
    # 注: caller 负责 db.commit() (一般和业务事务一起)
    return log


def audit_request(
    request: Any,  # fastapi.Request
    db: Session,
    *,
    user: User | None,
    action: str,
    module: str,
    target_type: str | None = None,
    target_id: str | int | None = None,
    detail: dict | None = None,
    success: bool = True,
) -> OperationLog:
    """从 FastAPI request 自动取 IP / UA / trace_id."""
    ip = None
    if request.client:
        ip = request.client.host
    user_agent = request.headers.get("user-agent")
    trace_id = getattr(request.state, "trace_id", None)

    return audit_log(
        db,
        user=user,
        action=action,
        module=module,
        target_type=target_type,
        target_id=target_id,
        detail=detail,
        ip=ip,
        user_agent=user_agent,
        trace_id=trace_id,
        success=success,
    )
