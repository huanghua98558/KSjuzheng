"""APScheduler 单实例 + 4 个调度任务.

设计:
  - BackgroundScheduler 单进程内, 不引入 Celery (Phase 1-2)
  - 每个 job 拿独立 db session, 自己 commit
  - log 全打 logger (含 trace_id 留空)
  - 失败不要 crash 主进程 — 全 try/except
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
import threading

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger
from sqlalchemy import select

from app.core.config import settings
from app.core.db import get_session_factory
from app.core.logging import logger
from app.models import (
    Account,
    AccountTaskRecord,
    CloudCookieAccount,
    FireflyIncome,
    FluorescentIncome,
    IncomeArchive,
    McnAuthorization,
    SparkIncome,
)
from app.services.statistics_service import rebuild_drama_link_stats


_scheduler: BackgroundScheduler | None = None
_lock = threading.Lock()


# ============================================================
# Job 1: aggregate_drama_stats — \u6bcf 10min
# ============================================================

def job_aggregate_drama_stats():
    Session = get_session_factory()
    with Session() as db:
        try:
            n = rebuild_drama_link_stats(db, organization_id=None)
            db.commit()
            logger.info(f"[worker.aggregate_drama_stats] rebuilt {n} groups")
        except Exception as ex:
            db.rollback()
            logger.error(f"[worker.aggregate_drama_stats] failed: {ex}", exc_info=True)


# ============================================================
# Job 2: cookie_status_refresher — \u6bcf 30min
# ============================================================

def job_cookie_status_refresher():
    """\u626b\u63cf last_success_at > 6h \u672a\u66f4\u65b0\u7684 cookie, \u6807 stale.

    \u771f\u5b9e\u9a8c\u8bc1\u9700\u5728\u5ba2\u6237\u7aef\u8df3\u63a5\u5feb\u624b\u63a5\u53e3 (\u540e\u7aef\u4ec5 metadata).
    """
    Session = get_session_factory()
    with Session() as db:
        try:
            cutoff = datetime.now(timezone.utc) - timedelta(hours=6)
            stale_q = (
                select(CloudCookieAccount)
                .where(CloudCookieAccount.login_status == "valid")
                .where(
                    (CloudCookieAccount.last_success_at.is_(None))
                    | (CloudCookieAccount.last_success_at < cutoff)
                )
            )
            n = 0
            for c in db.execute(stale_q).scalars().all():
                c.login_status = "unknown"
                n += 1
            if n:
                db.commit()
            logger.info(f"[worker.cookie_status_refresher] marked {n} stale cookies as unknown")
        except Exception as ex:
            db.rollback()
            logger.error(f"[worker.cookie_status_refresher] failed: {ex}", exc_info=True)


# ============================================================
# Job 3: sync_mcn_authorization — \u6bcf 1h
# ============================================================

def job_sync_mcn_authorization():
    """\u6bcf 1h \u540c\u6b65 MCN \u6388\u6743\u72b6\u6001.

    Phase 2 stub: \u4ec5\u626b\u672c\u5730 mcn_authorizations 7\u5929\u672a\u5237\u65b0\u8005, \u6807\u70ba\u9700\u91cd\u8bd5.
    Phase 3 \u5e94\u63a5\u5165 mcn_client.verify_mcn() \u62c9\u53d6\u771f\u5b9e\u72b6\u6001.
    """
    Session = get_session_factory()
    with Session() as db:
        try:
            cutoff = datetime.now(timezone.utc) - timedelta(days=7)
            stale = db.execute(
                select(McnAuthorization)
                .where(McnAuthorization.mcn_status == "authorized")
                .where(McnAuthorization.authorized_at < cutoff)
                .limit(20)
            ).scalars().all()
            for ma in stale:
                ma.invite_status = "stale_check_needed"
            if stale:
                db.commit()
            logger.info(
                f"[worker.sync_mcn_authorization] flagged {len(stale)} stale MCN auths"
                " (\u5b9e\u9645\u540c\u6b65\u5728 Phase 3 \u63a5\u5165)"
            )
        except Exception as ex:
            db.rollback()
            logger.error(f"[worker.sync_mcn_authorization] failed: {ex}", exc_info=True)


# ============================================================
# Job 4: income_archive_builder — \u6bcf\u65e5 02:00
# ============================================================

def job_income_archive_builder():
    """\u4ee5\u4e0a\u4e2a\u6708\u4e3a\u5355\u4f4d, \u4ece spark/firefly \u660e\u7ec6\u91cd\u5efa income_archives.

    \u53ea\u8d77 spark/firefly (fluorescent \u6d41\u6c34\u4e0d\u5f52\u6863).
    \u5e42\u7b49: \u5df2\u5b58\u5728\u8be5 (org+program+year+month+member) \u2192 update total_amount.
    """
    Session = get_session_factory()
    with Session() as db:
        try:
            now = datetime.now(timezone.utc)
            # \u6708\u521d 02:00 \u8d70\u4e0a\u4e2a\u6708 \u00d7 \u6bcf\u65e5\u8d77\u90fd\u4f1a\u91cd\u5efa\u5f53\u6708 (\u6539\u52a8\u5907\u68c0)
            year, month = now.year, now.month
            built_total = 0
            for program, model in [("spark", SparkIncome), ("firefly", FireflyIncome)]:
                # \u805a\u5408 (org+member) \u2192 total
                from sqlalchemy import func as _f
                stmt = (
                    select(
                        model.organization_id.label("org"),
                        model.member_id.label("mid"),
                        model.account_id.label("aid"),
                        _f.coalesce(_f.sum(model.income_amount), 0.0).label("total"),
                        _f.avg(model.commission_rate).label("rate"),
                        _f.coalesce(_f.sum(model.commission_amount), 0.0).label("commission"),
                    )
                    .where(model.archived_year_month == f"{year:04d}-{month:02d}")
                    .group_by(model.organization_id, model.member_id, model.account_id)
                )
                rows = db.execute(stmt).all()
                for r in rows:
                    a = db.execute(
                        select(IncomeArchive)
                        .where(IncomeArchive.organization_id == r.org)
                        .where(IncomeArchive.program_type == program)
                        .where(IncomeArchive.year == year)
                        .where(IncomeArchive.month == month)
                        .where(IncomeArchive.member_id == r.mid)
                    ).scalar_one_or_none()
                    if a:
                        a.total_amount = float(r.total or 0)
                        a.commission_rate = float(r.rate) if r.rate is not None else None
                        a.commission_amount = float(r.commission or 0)
                    else:
                        db.add(IncomeArchive(
                            organization_id=r.org,
                            program_type=program,
                            year=year, month=month,
                            member_id=r.mid, account_id=r.aid,
                            total_amount=float(r.total or 0),
                            commission_rate=float(r.rate) if r.rate is not None else None,
                            commission_amount=float(r.commission or 0),
                            settlement_status="pending",
                        ))
                    built_total += 1
            db.commit()
            logger.info(
                f"[worker.income_archive_builder] built {built_total} archives "
                f"({year}-{month:02d})"
            )
        except Exception as ex:
            db.rollback()
            logger.error(f"[worker.income_archive_builder] failed: {ex}", exc_info=True)


# ============================================================
# Scheduler 控制
# ============================================================

# \u53ef\u8bbf\u95ee\u72b6\u6001 (healthz \u7528)
worker_status: dict[str, dict] = {
    "aggregate_drama_stats": {"last_run": None, "next_run": None, "interval": "10m"},
    "cookie_status_refresher": {"last_run": None, "next_run": None, "interval": "30m"},
    "sync_mcn_authorization": {"last_run": None, "next_run": None, "interval": "1h"},
    "income_archive_builder": {"last_run": None, "next_run": None, "schedule": "daily 02:00"},
}


def _wrap(name: str, fn):
    def runner():
        worker_status[name]["last_run"] = datetime.now(timezone.utc).isoformat()
        fn()
    return runner


def start_scheduler() -> BackgroundScheduler | None:
    """启动后台 scheduler. \u91cd\u590d\u8c03\u5b89\u5168."""
    global _scheduler
    with _lock:
        if _scheduler is not None and _scheduler.running:
            return _scheduler

        if settings.APP_ENV == "test":
            # \u6d4b\u8bd5\u6a21\u5f0f\u4e0d\u542f
            logger.info("[scheduler] APP_ENV=test, \u4e0d\u542f\u52a8")
            return None

        sched = BackgroundScheduler(timezone=settings.TIMEZONE or "Asia/Shanghai")

        sched.add_job(
            _wrap("aggregate_drama_stats", job_aggregate_drama_stats),
            IntervalTrigger(minutes=10),
            id="aggregate_drama_stats",
            replace_existing=True,
            next_run_time=datetime.now() + timedelta(seconds=30),
        )
        sched.add_job(
            _wrap("cookie_status_refresher", job_cookie_status_refresher),
            IntervalTrigger(minutes=30),
            id="cookie_status_refresher",
            replace_existing=True,
            next_run_time=datetime.now() + timedelta(minutes=2),
        )
        sched.add_job(
            _wrap("sync_mcn_authorization", job_sync_mcn_authorization),
            IntervalTrigger(hours=1),
            id="sync_mcn_authorization",
            replace_existing=True,
            next_run_time=datetime.now() + timedelta(minutes=5),
        )
        sched.add_job(
            _wrap("income_archive_builder", job_income_archive_builder),
            CronTrigger(hour=2, minute=0),
            id="income_archive_builder",
            replace_existing=True,
        )

        sched.start()
        _scheduler = sched

        # 把 next_run 写入 worker_status
        for j in sched.get_jobs():
            if j.id in worker_status and j.next_run_time:
                worker_status[j.id]["next_run"] = j.next_run_time.isoformat()

        logger.info(f"[scheduler] \u542f\u52a8 4 \u4e2a worker: {[j.id for j in sched.get_jobs()]}")
        return sched


def shutdown_scheduler() -> None:
    global _scheduler
    with _lock:
        if _scheduler and _scheduler.running:
            _scheduler.shutdown(wait=False)
            logger.info("[scheduler] \u5173\u95ed")
        _scheduler = None


def trigger_now(job_id: str) -> bool:
    """\u624b\u52a8\u89e6\u53d1 (admin endpoint \u8c03)."""
    if not _scheduler:
        return False
    job = _scheduler.get_job(job_id)
    if not job:
        return False
    job.modify(next_run_time=datetime.now())
    return True


def get_worker_status() -> dict:
    if _scheduler:
        for j in _scheduler.get_jobs():
            if j.id in worker_status and j.next_run_time:
                worker_status[j.id]["next_run"] = j.next_run_time.isoformat()
    return {
        "running": bool(_scheduler and _scheduler.running),
        "jobs": dict(worker_status),
    }
