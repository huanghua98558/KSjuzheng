"""日志配置 — loguru 单例, 文件 rotating + stdout.

每行带 trace_id (从 contextvar 取). 用法:

    from app.core.logging import logger, bind_trace
    bind_trace("a8f2c7d4")
    logger.info("user logged in", user_id=42)
"""
from __future__ import annotations

import sys
from contextvars import ContextVar

from loguru import logger as _logger

from app.core.config import settings


_trace_var: ContextVar[str] = ContextVar("trace_id", default="-")


def bind_trace(trace_id: str) -> None:
    """ASGI 中间件每请求开头调用一次."""
    _trace_var.set(trace_id)


def _trace_filter(record):
    record["extra"].setdefault("trace_id", _trace_var.get())
    return True


def setup_logging() -> None:
    """主入口启动时调用一次."""
    _logger.remove()

    fmt = (
        "<green>{time:YYYY-MM-DD HH:mm:ss.SSS}</green> "
        "<level>{level: <8}</level> "
        "<cyan>[{extra[trace_id]}]</cyan> "
        "<cyan>{name}:{function}:{line}</cyan> - "
        "<level>{message}</level>"
    )

    # stdout
    _logger.add(
        sys.stdout,
        level=settings.LOG_LEVEL,
        format=fmt,
        filter=_trace_filter,
        enqueue=False,
        backtrace=settings.DEBUG,
        diagnose=settings.DEBUG,
    )

    # rotating file
    log_path = settings.log_dir / "ksjuzheng.log"
    _logger.add(
        str(log_path),
        level=settings.LOG_LEVEL,
        format=(
            "{time:YYYY-MM-DD HH:mm:ss.SSS} {level: <8} "
            "[{extra[trace_id]}] {name}:{function}:{line} - {message}"
        ),
        filter=_trace_filter,
        rotation="50 MB",
        retention=f"{settings.LOG_RETENTION_DAYS} days",
        compression="zip",
        enqueue=True,
        encoding="utf-8",
    )


# 模块级别名
logger = _logger
