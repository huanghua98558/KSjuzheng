"""Envelope 响应工具.

对应蓝图: 后端开发技术文档与接口规范v1.md §2.2.

格式:
    成功: {ok: true,  data: <载荷>, meta: {trace_id, ts, server_version, ...}}
    失败: {ok: false, error: {code, message, hint, details?}, meta: {...}}
"""
from __future__ import annotations

from datetime import datetime, timezone, timedelta
from typing import Any

from app.core.config import settings


# Asia/Shanghai = UTC+8
_TZ_SH = timezone(timedelta(hours=8))


def _now_iso() -> str:
    """ISO 8601 with timezone, e.g. '2026-04-25T14:30:00+08:00'."""
    return datetime.now(_TZ_SH).replace(microsecond=0).isoformat()


def make_meta(trace_id: str, **extra) -> dict:
    """构造 meta 块."""
    meta = {
        "trace_id": trace_id,
        "ts": _now_iso(),
        "server_version": settings.APP_VERSION,
    }
    meta.update({k: v for k, v in extra.items() if v is not None})
    return meta


def ok(data: Any = None, *, trace_id: str = "-", **meta_extra) -> dict:
    """成功响应."""
    return {
        "ok": True,
        "data": data,
        "meta": make_meta(trace_id, **meta_extra),
    }


def err(
    code: str,
    message: str,
    *,
    trace_id: str = "-",
    hint: str | None = None,
    details: dict | None = None,
    **meta_extra,
) -> dict:
    """失败响应."""
    error_obj = {
        "code": code,
        "message": message,
    }
    if hint:
        error_obj["hint"] = hint
    if details and settings.DEBUG:
        error_obj["details"] = details
    return {
        "ok": False,
        "error": error_obj,
        "meta": make_meta(trace_id, **meta_extra),
    }
