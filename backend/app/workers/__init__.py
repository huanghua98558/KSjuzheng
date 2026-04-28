"""后台 worker — APScheduler 单进程内任务.

启动: app.main lifespan 调 start_scheduler()
停止: lifespan shutdown 调 shutdown_scheduler()

对应 PHASE2_PLAN Sprint 2D §1 4 \u4e2a worker:
  - aggregate_drama_stats     \u6bcf 10min \u91cd\u7b97 drama_link_statistics
  - cookie_status_refresher   \u6bcf 30min \u68c0\u67e5\u8d85\u8fc7 6h \u672a\u5237\u65b0\u7684 cookie
  - sync_mcn_authorization    \u6bcf 1h \u62c9 MCN \u6388\u6743\u72b6\u6001 (Phase 2 stub)
  - income_archive_builder    \u6bcf\u65e5 02:00 \u8d77 \u5168\u673a\u6784\u5168 program \u805a\u5408\u4e0a\u6708 income \u2192 income_archives
"""
from __future__ import annotations

from app.workers.scheduler import start_scheduler, shutdown_scheduler  # noqa: F401
