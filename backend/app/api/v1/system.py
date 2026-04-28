"""系统层端点 — 服务自检 / 时间同步."""
from __future__ import annotations

from datetime import datetime, timezone, timedelta

from fastapi import APIRouter, Request

from app.core.config import settings
from app.core.envelope import ok


router = APIRouter()


@router.get("/ping")
async def ping(request: Request):
    """简单 ping — 客户端启动时检查服务可达."""
    return ok(
        {"name": settings.APP_NAME, "version": settings.APP_VERSION, "env": settings.APP_ENV},
        trace_id=getattr(request.state, "trace_id", "-"),
    )


@router.get("/time")
async def server_time(request: Request):
    """返服务器时间 (Asia/Shanghai), 客户端可对时间偏差."""
    tz = timezone(timedelta(hours=8))
    return ok(
        {
            "server_time": datetime.now(tz).isoformat(timespec="seconds"),
            "timezone": settings.TIMEZONE,
        },
        trace_id=getattr(request.state, "trace_id", "-"),
    )
