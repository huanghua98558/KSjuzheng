"""Dashboard / 统计聚合服务."""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

from sqlalchemy import and_, case, desc, func, select, text
from sqlalchemy.orm import Session

from app.core.tenant_scope import (
    TenantScope,
    apply_to_account_query,
    compute_tenant_scope,
)
from app.models import Account, AccountTaskRecord, DramaLinkStatistic, User


def _scope_filter_account_task(stmt, scope: TenantScope, user: User):
    if scope.unrestricted:
        return stmt
    stmt = stmt.where(AccountTaskRecord.organization_id.in_(scope.organization_ids))
    if scope.account_filter == "self_only":
        sub = select(Account.id).where(Account.assigned_user_id == user.id)
        stmt = stmt.where(AccountTaskRecord.account_id.in_(sub))
    elif user.role == "captain":
        sub = select(Account.id).where(Account.assigned_user_id.in_(scope.user_ids))
        stmt = stmt.where(AccountTaskRecord.account_id.in_(sub))
    # operator: 整个机构都可见, 不再加 account 过滤
    return stmt


# ============================================================
# Overview
# ============================================================

def overview(db: Session, user: User) -> dict:
    scope = compute_tenant_scope(db, user)
    today = date.today()

    # 账号总数
    acc_stmt = select(func.count()).select_from(Account).where(Account.deleted_at.is_(None))
    if not scope.unrestricted:
        acc_stmt = acc_stmt.where(Account.organization_id.in_(scope.organization_ids))
        if scope.account_filter == "self_only":
            acc_stmt = acc_stmt.where(Account.assigned_user_id == user.id)
    total_accounts = db.execute(acc_stmt).scalar_one() or 0

    mcn_stmt = acc_stmt.where(Account.mcn_status == "authorized")
    mcn_accounts = db.execute(mcn_stmt).scalar_one() or 0

    # 总执行
    exec_stmt = select(func.count()).select_from(AccountTaskRecord)
    exec_stmt = _scope_filter_account_task(exec_stmt, scope, user)
    total_executions = db.execute(exec_stmt).scalar_one() or 0

    # 今日
    today_stmt = (
        select(
            func.count().label("c"),
            func.sum(case((AccountTaskRecord.success.is_(True), 1), else_=0)).label("s"),
        )
        .select_from(AccountTaskRecord)
        .where(func.date(AccountTaskRecord.created_at) == today)
    )
    today_stmt = _scope_filter_account_task(today_stmt, scope, user)
    row = db.execute(today_stmt).one()
    today_executions = row.c or 0
    today_success = int(row.s or 0)
    today_fail = max(0, today_executions - today_success)
    today_rate = round(today_success / today_executions, 4) if today_executions else 0.0

    # 近 7 天趋势
    cutoff = datetime.now(timezone.utc) - timedelta(days=7)
    trend_stmt = (
        select(
            func.date(AccountTaskRecord.created_at).label("d"),
            func.count().label("c"),
            func.sum(case((AccountTaskRecord.success.is_(True), 1), else_=0)).label("s"),
        )
        .where(AccountTaskRecord.created_at >= cutoff)
        .group_by("d")
        .order_by("d")
    )
    trend_stmt = _scope_filter_account_task(trend_stmt, scope, user)
    trend_rows = db.execute(trend_stmt).all()
    trend_7d = [
        {
            "date": str(r.d),
            "count": int(r.c or 0),
            "success": int(r.s or 0),
            "fail": max(0, int(r.c or 0) - int(r.s or 0)),
        }
        for r in trend_rows
    ]

    # 30 天成功 / 失败比例
    cutoff_30 = datetime.now(timezone.utc) - timedelta(days=30)
    s_stmt = (
        select(
            func.sum(case((AccountTaskRecord.success.is_(True), 1), else_=0)).label("s"),
            func.sum(case((AccountTaskRecord.success.is_(False), 1), else_=0)).label("f"),
        )
        .where(AccountTaskRecord.created_at >= cutoff_30)
    )
    s_stmt = _scope_filter_account_task(s_stmt, scope, user)
    sr = db.execute(s_stmt).one()
    success_ratio_30d = {
        "success": int(sr.s or 0),
        "fail": int(sr.f or 0),
    }

    return {
        "total_accounts": total_accounts,
        "mcn_accounts": mcn_accounts,
        "total_executions": total_executions,
        "today_executions": today_executions,
        "today_success": today_success,
        "today_fail": today_fail,
        "today_success_rate": today_rate,
        "trend_7d": trend_7d,
        "success_ratio_30d": success_ratio_30d,
    }


def today_card(db: Session, user: User) -> dict:
    """轻量版 — 给 Dashboard 顶部卡片用. 不含 trend."""
    o = overview(db, user)
    # 加 avg_duration_ms
    scope = compute_tenant_scope(db, user)
    today = date.today()
    avg_stmt = (
        select(func.avg(AccountTaskRecord.duration_ms))
        .select_from(AccountTaskRecord)
        .where(func.date(AccountTaskRecord.created_at) == today)
    )
    avg_stmt = _scope_filter_account_task(avg_stmt, scope, user)
    avg = db.execute(avg_stmt).scalar() or 0.0
    return {
        "total_accounts": o["total_accounts"],
        "mcn_accounts": o["mcn_accounts"],
        "today_executions": o["today_executions"],
        "today_success": o["today_success"],
        "today_fail": o["today_fail"],
        "today_success_rate": o["today_success_rate"],
        "avg_duration_ms": round(float(avg), 2),
    }


# ============================================================
# 执行统计 (按日期 / UID)
# ============================================================

def list_executions(
    db: Session, user: User,
    *, start: date | None = None, end: date | None = None,
    uid: str | None = None,
    page: int = 1, size: int = 50,
) -> tuple[list[dict], int]:
    scope = compute_tenant_scope(db, user)

    base = (
        select(
            func.date(AccountTaskRecord.created_at).label("d"),
            func.count().label("c"),
            func.sum(case((AccountTaskRecord.success.is_(True), 1), else_=0)).label("s"),
            func.sum(case((AccountTaskRecord.success.is_(False), 1), else_=0)).label("f"),
            func.avg(AccountTaskRecord.duration_ms).label("avg_d"),
        )
    )
    base = _scope_filter_account_task(base, scope, user)
    if start:
        base = base.where(func.date(AccountTaskRecord.created_at) >= start)
    if end:
        base = base.where(func.date(AccountTaskRecord.created_at) <= end)
    if uid:
        # join account on real_uid
        sub = select(Account.id).where(Account.real_uid == uid)
        base = base.where(AccountTaskRecord.account_id.in_(sub))

    grouped = base.group_by("d").order_by(text("d DESC"))

    total = db.execute(
        select(func.count()).select_from(grouped.subquery())
    ).scalar_one()

    rows = db.execute(grouped.offset((page - 1) * size).limit(size)).all()
    items = []
    for r in rows:
        c = int(r.c or 0)
        s = int(r.s or 0)
        items.append({
            "date": str(r.d),
            "exec_count": c,
            "success_count": s,
            "fail_count": int(r.f or 0),
            "success_rate": round(s / c, 4) if c else 0.0,
            "avg_duration_ms": round(float(r.avg_d or 0), 2),
        })
    return items, total


# ============================================================
# Drama Link 统计
# ============================================================

def list_drama_link_stats(
    db: Session, user: User,
    *, page: int = 1, size: int = 50, keyword: str | None = None,
    sort: str = "execute_count.desc",
):
    scope = compute_tenant_scope(db, user)
    stmt = select(DramaLinkStatistic)
    if not scope.unrestricted:
        stmt = stmt.where(
            DramaLinkStatistic.organization_id.in_(scope.organization_ids)
        )
    if keyword:
        like = f"%{keyword}%"
        stmt = stmt.where(
            (DramaLinkStatistic.drama_url.like(like))
            | (DramaLinkStatistic.drama_name.like(like))
        )
    total = db.execute(select(func.count()).select_from(stmt.subquery())).scalar_one()

    field, _, direction = sort.partition(".")
    direction = direction or "desc"
    col = getattr(DramaLinkStatistic, field, DramaLinkStatistic.execute_count)
    stmt = stmt.order_by(col.desc() if direction == "desc" else col.asc())
    stmt = stmt.offset((page - 1) * size).limit(size)
    items = db.execute(stmt).scalars().all()
    return items, total


def batch_delete_drama_link_stats(db: Session, user: User, ids: list[int]) -> dict:
    scope = compute_tenant_scope(db, user)
    if not scope.unrestricted:
        in_scope = set(db.execute(
            select(DramaLinkStatistic.id)
            .where(DramaLinkStatistic.id.in_(ids))
            .where(DramaLinkStatistic.organization_id.in_(scope.organization_ids))
        ).scalars().all())
        invalid = set(ids) - in_scope
        if invalid:
            from app.core.errors import AUTH_403, AuthError
            raise AuthError(AUTH_403, message=f"部分条目不在范围 ({len(invalid)} 条)")

    affected = 0
    for did in ids:
        d = db.get(DramaLinkStatistic, did)
        if d:
            db.delete(d)
            affected += 1
    db.flush()
    return {"success_count": affected, "failed_count": len(ids) - affected}


def clear_drama_link_stats(db: Session, user: User) -> dict:
    """清空当前 scope 内全部链接统计 (super_admin 限定)."""
    if user.role != "super_admin" and not user.is_superadmin:
        from app.core.errors import AUTH_403, AuthError
        raise AuthError(AUTH_403, message="只有超管可清空")
    n = db.query(DramaLinkStatistic).delete()
    db.flush()
    return {"deleted": n}


# ============================================================
# 维护: 重新聚合 drama_link_statistics (worker 用)
# ============================================================

def rebuild_drama_link_stats(db: Session, organization_id: int | None = None) -> int:
    """完全重算指定 (or all) 机构的 drama_link_statistics. 由 worker 每 N 分钟跑."""
    real_stmt = select(func.count(DramaLinkStatistic.id)).where(
        ~DramaLinkStatistic.drama_url.like("placeholder://%")
    )
    if organization_id is not None:
        real_stmt = real_stmt.where(DramaLinkStatistic.organization_id == organization_id)
    if db.execute(real_stmt).scalar_one() > 0:
        return 0

    where = []
    if organization_id is not None:
        where.append(AccountTaskRecord.organization_id == organization_id)

    stmt = (
        select(
            AccountTaskRecord.organization_id.label("org_id"),
            AccountTaskRecord.drama_id.label("did"),
            AccountTaskRecord.drama_name.label("dn"),
            AccountTaskRecord.task_type.label("task_type"),
            func.count().label("c"),
            func.sum(case((AccountTaskRecord.success.is_(True), 1), else_=0)).label("s"),
            func.sum(case((AccountTaskRecord.success.is_(False), 1), else_=0)).label("f"),
            func.count(func.distinct(AccountTaskRecord.account_id)).label("acc"),
            func.max(AccountTaskRecord.created_at).label("last"),
        )
        .group_by(
            AccountTaskRecord.organization_id,
            AccountTaskRecord.drama_id,
            AccountTaskRecord.drama_name,
            AccountTaskRecord.task_type,
        )
    )
    for w in where:
        stmt = stmt.where(w)

    rows = db.execute(stmt).all()

    # Keep imported real-link rows stable; only placeholder rows are refreshed.
    n = 0
    for r in rows:
        if not r.dn:
            continue
        task_type = r.task_type or "unknown"
        existing = db.execute(
            select(DramaLinkStatistic)
            .where(DramaLinkStatistic.organization_id == r.org_id)
            .where(DramaLinkStatistic.drama_name == r.dn)
            .where(DramaLinkStatistic.task_type == task_type)
            .order_by(DramaLinkStatistic.id.asc())
        ).scalars().first()
        if existing:
            if existing.drama_url.startswith("placeholder://"):
                existing.execute_count = int(r.c or 0)
                existing.success_count = int(r.s or 0)
                existing.failed_count = int(r.f or 0)
                existing.account_count = int(r.acc or 0)
                existing.last_executed_at = r.last
        else:
            d = DramaLinkStatistic(
                organization_id=r.org_id,
                drama_url=f"placeholder://{task_type}/{r.dn}",
                drama_name=r.dn,
                task_type=task_type,
                execute_count=int(r.c or 0),
                success_count=int(r.s or 0),
                failed_count=int(r.f or 0),
                account_count=int(r.acc or 0),
                last_executed_at=r.last,
            )
            db.add(d)
        n += 1
    db.flush()
    return n
