"""Trace ID 中间件 — 每请求生成 8-byte hex, 注入 request.state + response header.

对应蓝图: §2.5 Trace ID 链路追踪.
"""
from __future__ import annotations

import uuid

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

from app.core.logging import bind_trace


class TraceIDMiddleware(BaseHTTPMiddleware):
    """生成 trace_id, 写到 request.state 与 response header."""

    async def dispatch(self, request: Request, call_next) -> Response:
        # 客户端可以通过 Header 传 X-Trace-ID, 否则服务器生成
        trace_id = request.headers.get("X-Trace-ID") or uuid.uuid4().hex[:8]
        request.state.trace_id = trace_id
        bind_trace(trace_id)

        response = await call_next(request)
        response.headers["X-Trace-ID"] = trace_id
        return response
