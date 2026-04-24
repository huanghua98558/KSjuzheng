# -*- coding: utf-8 -*-
"""SSE 实时事件推送.

前端 EventSource 连 /api/stream/events?levels=warn,error,critical
服务端从 event_bus 订阅, 实时 flush 每一条. keep-alive ping 每 20s.
"""
from __future__ import annotations

import asyncio
import json
import queue as _queue
import time

from fastapi import APIRouter, Query, Request
from fastapi.responses import StreamingResponse

from core.auth import verify_token, extract_token
from core.event_bus import subscribe, unsubscribe

router = APIRouter()


async def _event_generator(request: Request, levels: set[str],
                           event_types: set[str]):
    """SSE 事件流 generator.

    ★ 2026-04-20 PERF FIX: 之前 q.get(timeout=1.0) 是 **blocking** 同步调用,
    在 async generator 里会阻塞整个 uvicorn event loop. 2 个 SSE 连接就
    能让所有 /api/* 请求增加 ~3-6s 延迟.

    修复: 改用 asyncio.to_thread 把 blocking get 扔到线程池,
    event loop 不再被占用.
    """
    import asyncio as _asyncio
    q = subscribe()
    try:
        # 首条: 订阅确认
        yield f"event: ready\ndata: {{\"ts\":{time.time()}}}\n\n"
        last_ping = time.time()
        while True:
            if await request.is_disconnected():
                break
            try:
                # ★ 关键修复: 用 to_thread 不占 event loop
                event = await _asyncio.to_thread(q.get, True, 1.0)
            except _queue.Empty:
                # keep-alive ping 每 20s (防代理断流)
                if time.time() - last_ping > 20:
                    yield f": ping {int(time.time())}\n\n"
                    last_ping = time.time()
                continue

            if levels and event.get("event_level") not in levels:
                continue
            if event_types and event.get("event_type") not in event_types:
                # 支持前缀匹配 "publish.*"
                if not any(
                    t.endswith(".*") and event.get("event_type", "").startswith(t[:-1])
                    for t in event_types
                ):
                    continue

            yield f"id: {event['id']}\nevent: system\ndata: {json.dumps(event, ensure_ascii=False, default=str)}\n\n"
    finally:
        unsubscribe(q)


@router.post("/_test_emit")
def test_emit(request: Request, level: str = "warn",
              event_type: str = "test.sse"):
    """测试用: 从 dashboard 进程内 emit 一条事件, 验证 SSE pipe 打通."""
    from core.auth import current_user
    u = current_user(request)
    from core.event_bus import emit_event
    eid = emit_event(
        event_type,
        entity_type="test", entity_id=u["username"],
        payload={"triggered_by": u["username"],
                 "message": f"test event from {u['username']}"},
        level=level, source_module="stream_test",
    )
    return {"ok": True, "event_id": eid}


@router.get("/events")
async def stream_events(request: Request,
                        levels: str = Query("", description="warn,error,critical 逗号分隔, 空=全部"),
                        types: str = Query("", description="event_type 过滤, 支持 publish.*")):
    """SSE 实时事件流. 通过 query string 传认证 token (EventSource 不支持自定义 header)."""
    # EventSource 不能带 Authorization header → 从 query 或 cookie 拿 token
    token = request.query_params.get("token") or extract_token(request)
    if not token:
        return StreamingResponse(
            iter([f"event: error\ndata: {json.dumps({'error':'not authenticated'})}\n\n"]),
            media_type="text/event-stream",
            status_code=401,
        )
    try:
        verify_token(token)
    except Exception as e:
        return StreamingResponse(
            iter([f"event: error\ndata: {json.dumps({'error':str(e)})}\n\n"]),
            media_type="text/event-stream",
            status_code=401,
        )

    levels_set = {x.strip() for x in levels.split(",") if x.strip()}
    types_set = {x.strip() for x in types.split(",") if x.strip()}

    return StreamingResponse(
        _event_generator(request, levels_set, types_set),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
            "Connection": "keep-alive",
        },
    )
