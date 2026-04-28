"""统一异常处理 — 把所有异常转换为 Envelope 格式.

捕获顺序 (FastAPI 自动按 type 匹配):
  1. BizError                     -> envelope error, http_status=spec.http_status
  2. RequestValidationError       -> envelope error, VALIDATION_422
  3. StarletteHTTPException       -> envelope error, 按 status 映射
  4. Exception (未捕获)            -> envelope error, INTERNAL_500 (DEBUG 时带 details)
"""
from __future__ import annotations

import traceback

from fastapi import FastAPI, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.core import errors as e
from app.core.envelope import err
from app.core.logging import logger


def _trace_id(request: Request) -> str:
    return getattr(request.state, "trace_id", "-")


def install(app: FastAPI) -> None:
    """注册所有异常处理器."""

    @app.exception_handler(e.BizError)
    async def _handle_biz(request: Request, exc: e.BizError):
        tid = _trace_id(request)
        logger.warning(
            f"BizError {exc.code} [{exc.http_status}] {exc.message}",
            code=exc.code,
            details=exc.details,
        )
        body = err(
            exc.code,
            exc.message,
            trace_id=tid,
            hint=exc.hint,
            details=exc.details or None,
        )
        headers = {}
        if isinstance(exc, e.RateLimitError):
            headers["Retry-After"] = str(exc.retry_after)
        return JSONResponse(status_code=exc.http_status, content=body, headers=headers)

    @app.exception_handler(RequestValidationError)
    async def _handle_validation(request: Request, exc: RequestValidationError):
        tid = _trace_id(request)
        # 把 pydantic errors 整理成简洁中文提示
        errors_brief = []
        for er in exc.errors()[:5]:
            loc = ".".join(str(x) for x in er.get("loc", []))
            errors_brief.append(f"{loc}: {er.get('msg', '校验失败')}")
        msg = e.VALIDATION_422.message
        details = {"errors": errors_brief} if errors_brief else None
        logger.warning(f"ValidationError on {request.url.path}: {errors_brief}")
        return JSONResponse(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            content=err(e.VALIDATION_422.code, msg, trace_id=tid, details=details),
        )

    @app.exception_handler(StarletteHTTPException)
    async def _handle_http(request: Request, exc: StarletteHTTPException):
        tid = _trace_id(request)
        # 按 HTTP code 反查 ErrorSpec, 否则归到 INTERNAL_500
        spec_map = {
            401: e.AUTH_401,
            402: e.AUTH_402,
            403: e.AUTH_403,
            404: e.RESOURCE_404,
            409: e.CONFLICT_409,
            422: e.VALIDATION_422,
            429: e.RATE_LIMIT_429,
            500: e.INTERNAL_500,
            502: e.UPSTREAM_502,
            503: e.MAINTENANCE_503,
            504: e.GATEWAY_TIMEOUT_504,
        }
        spec = spec_map.get(exc.status_code, e.INTERNAL_500)
        msg = exc.detail if isinstance(exc.detail, str) else spec.message
        logger.info(f"HTTPException {exc.status_code}: {msg}")
        return JSONResponse(
            status_code=exc.status_code,
            content=err(spec.code, msg, trace_id=tid),
        )

    @app.exception_handler(Exception)
    async def _handle_any(request: Request, exc: Exception):
        tid = _trace_id(request)
        # 完整堆栈打到日志, 客户端只看脱敏 message
        logger.error(
            f"Unhandled exception on {request.url.path}: {type(exc).__name__}: {exc}",
            exc_info=True,
        )
        details = None
        from app.core.config import settings
        if settings.DEBUG:
            details = {
                "internal_error": f"{type(exc).__name__}: {exc}",
                "trace": traceback.format_exc().splitlines()[-10:],
            }
        return JSONResponse(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            content=err(
                e.INTERNAL_500.code,
                e.INTERNAL_500.message,
                trace_id=tid,
                details=details,
            ),
        )
