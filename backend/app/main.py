"""FastAPI 主入口.

启动:
    python -m uvicorn app.main:app --reload --host 0.0.0.0 --port 8800
"""
from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.core.config import settings
from app.core.envelope import ok
from app.core.logging import logger, setup_logging
from app.middleware.exception_handler import install as install_exception_handlers
from app.middleware.trace import TraceIDMiddleware


# 启动 / 关闭 lifecycle ---------------------------------------------------

@asynccontextmanager
async def lifespan(app: FastAPI):
    setup_logging()
    logger.info(f"=== {settings.APP_NAME} v{settings.APP_VERSION} 启动 ===")
    logger.info(f"  ENV={settings.APP_ENV}  DEBUG={settings.DEBUG}")
    logger.info(f"  DB={settings.DATABASE_URL}")
    logger.info(f"  CORS={settings.cors_origins_list}")

    # 初始化 DB 引擎 (建表延后到 alembic / init_db 脚本)
    from app.core.db import init_engine
    init_engine()

    # 启动 worker (test 环境跳过)
    from app.workers import start_scheduler
    start_scheduler()

    yield

    from app.workers import shutdown_scheduler
    shutdown_scheduler()
    logger.info("=== 服务关闭 ===")


# App 实例 ---------------------------------------------------------------

app = FastAPI(
    title=settings.APP_NAME,
    version=settings.APP_VERSION,
    description="KS矩阵后端 API — KS184 业务中台 + AI 自动化",
    docs_url="/docs",
    redoc_url="/redoc",
    openapi_url="/openapi.json",
    lifespan=lifespan,
)


# 中间件 (注册顺序: 后注册的最先执行 outbound) -----------------------------

app.add_middleware(TraceIDMiddleware)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["X-Trace-ID", "X-RateLimit-Limit", "X-RateLimit-Remaining"],
)

install_exception_handlers(app)


# 健康检查端点 (不走 envelope, 给 LB 用) ------------------------------------

@app.get("/healthz", include_in_schema=False)
async def healthz():
    """简单 liveness probe — LB 用. 200 即健康."""
    return {"status": "ok", "service": settings.APP_NAME, "version": settings.APP_VERSION}


@app.get("/readyz", include_in_schema=False)
async def readyz():
    """Readiness probe — 检查 DB 连通性."""
    from app.core.db import check_db
    db_ok, db_msg = check_db()
    if not db_ok:
        return {"status": "degraded", "db": db_msg}
    return {"status": "ok", "db": "connected"}


# 根 (envelope 格式, 给客户端 ping 用) -------------------------------------

@app.get("/")
async def root(request):
    return ok(
        {"name": settings.APP_NAME, "version": settings.APP_VERSION, "docs": "/docs"},
        trace_id=getattr(request.state, "trace_id", "-"),
    )


# API 路由聚合 ------------------------------------------------------------

from app.api.v1 import router as api_v1_router  # noqa: E402
from app.api.demo_compat import router as demo_compat_router  # noqa: E402

app.include_router(demo_compat_router, prefix="/api")
app.include_router(api_v1_router, prefix="/api/client")
