"""审计日志查询服务."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from sqlalchemy import and_, func, select
from sqlalchemy.orm import Session

from app.core.tenant_scope import compute_tenant_scope
from app.models import OperationLog, User


def list_logs(
    db: Session,
    user: User,
    *,
    page: int = 1,
    size: int = 50,
    user_filter: str | None = None,
    action: str | None = None,
    module: str | None = None,
    start: datetime | None = None,
    end: datetime | None = None,
):
    scope = compute_tenant_scope(db, user)
    stmt = select(OperationLog)
    if not scope.unrestricted:
        stmt = stmt.where(OperationLog.organization_id.in_(scope.organization_ids))

    if user_filter:
        stmt = stmt.join(User, User.id == OperationLog.user_id).where(
            User.username.like(f"%{user_filter}%")
        )
    if action:
        stmt = stmt.where(OperationLog.action == action)
    if module:
        stmt = stmt.where(OperationLog.module == module)
    if start:
        stmt = stmt.where(OperationLog.created_at >= start)
    if end:
        stmt = stmt.where(OperationLog.created_at <= end)

    total = db.execute(select(func.count()).select_from(stmt.subquery())).scalar_one()
    stmt = (
        stmt.order_by(OperationLog.id.desc())
        .offset((page - 1) * size)
        .limit(size)
    )
    items = db.execute(stmt).scalars().all()
    return items, total


def stats(db: Session, user: User) -> dict:
    """近 7 天聚合 + by_module + by_action top 5."""
    scope = compute_tenant_scope(db, user)
    base = select(OperationLog)
    if not scope.unrestricted:
        base = base.where(OperationLog.organization_id.in_(scope.organization_ids))

    total = db.execute(select(func.count()).select_from(base.subquery())).scalar_one()

    # by_module
    mod_stmt = (
        select(OperationLog.module, func.count())
        .group_by(OperationLog.module)
        .order_by(func.count().desc())
        .limit(20)
    )
    if not scope.unrestricted:
        mod_stmt = mod_stmt.where(OperationLog.organization_id.in_(scope.organization_ids))
    by_module = {m: c for m, c in db.execute(mod_stmt).all()}

    # by_action
    act_stmt = (
        select(OperationLog.action, func.count())
        .group_by(OperationLog.action)
        .order_by(func.count().desc())
        .limit(10)
    )
    if not scope.unrestricted:
        act_stmt = act_stmt.where(OperationLog.organization_id.in_(scope.organization_ids))
    by_action = {a: c for a, c in db.execute(act_stmt).all()}

    # last 7d
    cutoff = datetime.now(timezone.utc) - timedelta(days=7)
    day_stmt = (
        select(func.date(OperationLog.created_at).label("d"), func.count())
        .where(OperationLog.created_at >= cutoff)
        .group_by("d")
        .order_by("d")
    )
    if not scope.unrestricted:
        day_stmt = day_stmt.where(OperationLog.organization_id.in_(scope.organization_ids))
    last_7d = [{"date": str(d), "count": c} for d, c in db.execute(day_stmt).all()]

    return {
        "total": total,
        "by_module": by_module,
        "by_action": by_action,
        "last_7d": last_7d,
    }
