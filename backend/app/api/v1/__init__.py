"""v1 API 路由聚合 — 挂在 /api/client 下."""
from fastapi import APIRouter

from app.api.v1 import (
    accounts,
    ai,
    announcements,
    audit_logs,
    auth,
    cloud_cookies,
    collect_pool,
    cxt,
    high_income_dramas,
    income,
    ks_accounts,
    ks_collect,
    members,
    organizations,
    settings_api,
    statistics,
    system,
    users,
    violations,
    wallet,
    workers,
)

router = APIRouter()
router.include_router(auth.router, prefix="/auth", tags=["auth"])
router.include_router(system.router, prefix="/system", tags=["system"])

# Sprint 2A
router.include_router(accounts.router, prefix="/accounts", tags=["accounts"])
router.include_router(ks_accounts.router, prefix="/ks-accounts", tags=["ks-accounts"])
router.include_router(cloud_cookies.router, prefix="/cloud-cookies", tags=["cloud-cookies"])
router.include_router(users.router, prefix="/users", tags=["users"])
router.include_router(organizations.router, prefix="/organizations", tags=["organizations"])
router.include_router(audit_logs.router, prefix="/audit-logs", tags=["audit-logs"])

# Sprint 2B
router.include_router(collect_pool.router, prefix="/collect-pool", tags=["collect-pool"])
router.include_router(high_income_dramas.router, prefix="/high-income-dramas",
                      tags=["high-income"])
router.include_router(statistics.router, prefix="/statistics", tags=["statistics"])
router.include_router(cxt.router, prefix="/cxt", tags=["cxt"])

# Sprint 2C
router.include_router(members.router, prefix="", tags=["members"])
# 注: members.router 内部子路径已含 /org-members /spark/members /firefly/members
# /fluorescent/members /member-query, prefix 为空避免重复嵌套
router.include_router(income.router, prefix="", tags=["income"])
router.include_router(violations.router, prefix="/violations", tags=["violations"])
router.include_router(wallet.router, prefix="/wallet", tags=["wallet"])

# Sprint 2D
router.include_router(announcements.router, prefix="/announcements", tags=["announcements"])
router.include_router(settings_api.router, prefix="/settings", tags=["settings"])
router.include_router(workers.router, prefix="/workers", tags=["workers"])

# Phase 3: L9-L12 AI 自动化
router.include_router(ai.router, prefix="/ai", tags=["ai"])

# Phase 4: 快手数据采集 (KS GraphQL)
router.include_router(ks_collect.router, prefix="/ks", tags=["ks"])
