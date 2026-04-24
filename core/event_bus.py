# -*- coding: utf-8 -*-
"""system_events 统一写入入口.

  emit_event("publish.success",
             entity_type="account", entity_id="948",
             payload={"photo_id": "3x...", "drama": "..."},
             level="info",
             source_module="publisher")

所有模块用这一个入口, 避免格式分裂. 写库失败不抛, 不污染业务流程.

event_type 命名约定 (模块.动作):
  publish.success / publish.failed / publish.verified
  mcn.bind_ok / mcn.bind_fail / mcn.invite_sent / mcn.token_refresh
  heal.diagnosed / heal.applied / heal.playbook_promoted
  rule.triggered / rule.rejected / rule.proposed
  task.canceled / task.dead_letter / task.waiting_manual / task.override
  account.login / account.logout / account.relogin_needed
  config.changed / switch.changed
  agent.run_started / agent.run_completed / agent.escalated
"""
from __future__ import annotations

import json
import logging
import sqlite3
import threading
from typing import Any

from core.config import DB_PATH

log = logging.getLogger(__name__)

_LOCK = threading.Lock()
# 单例写连接 (WAL, autocommit), 多线程共用
_CONN: sqlite3.Connection | None = None

# In-process event fan-out. SSE subscribers register a queue here.
# Thread-safe. 每次 emit_event 时推到所有订阅者.
_SUBS_LOCK = threading.Lock()
_SUBSCRIBERS: list = []   # list[queue.Queue]


def subscribe() -> "queue.Queue":   # type: ignore
    """订阅事件流. 返回一个 Queue, 每次 emit 会 put(event_dict)."""
    import queue as _q
    q: _q.Queue = _q.Queue(maxsize=1000)
    with _SUBS_LOCK:
        _SUBSCRIBERS.append(q)
    return q


def unsubscribe(q) -> None:
    with _SUBS_LOCK:
        try:
            _SUBSCRIBERS.remove(q)
        except ValueError:
            pass


def _fanout(event: dict) -> None:
    """Non-blocking push 到所有订阅者. 队列满直接丢 (保护慢 consumer)."""
    with _SUBS_LOCK:
        subs = list(_SUBSCRIBERS)
    for q in subs:
        try:
            q.put_nowait(event)
        except Exception:
            pass


def _conn() -> sqlite3.Connection:
    global _CONN
    if _CONN is not None:
        return _CONN
    with _LOCK:
        if _CONN is not None:
            return _CONN
        c = sqlite3.connect(DB_PATH, check_same_thread=False,
                            timeout=60.0, isolation_level=None)
        c.execute("PRAGMA journal_mode=WAL")
        c.execute("PRAGMA busy_timeout=60000")
        _CONN = c
        return c


def emit_event(
    event_type: str,
    *,
    entity_type: str = "",
    entity_id: str = "",
    payload: dict | None = None,
    level: str = "info",
    source_module: str = "",
) -> int | None:
    """Non-fatal: 写库失败只 log, 不抛. 写成功后 fan-out 给 SSE 订阅者."""
    event_id = None
    try:
        c = _conn()
        cur = c.execute(
            """INSERT INTO system_events
                 (event_type, event_level, source_module,
                  entity_type, entity_id, payload, created_at)
               VALUES (?, ?, ?, ?, ?, ?, datetime('now','localtime'))""",
            (event_type[:80], level[:16], source_module[:64],
             entity_type[:32], str(entity_id)[:80],
             json.dumps(payload or {}, ensure_ascii=False, default=str)[:8000]),
        )
        event_id = cur.lastrowid
    except Exception as e:
        log.warning("[event_bus] emit failed: %s (%s)", event_type, e)

    # 无论 DB 是否成功, 都 push 给 SSE (让 UI 实时看到)
    try:
        _fanout({
            "id": event_id or 0,
            "event_type": event_type,
            "event_level": level,
            "source_module": source_module,
            "entity_type": entity_type,
            "entity_id": str(entity_id),
            "payload": payload or {},
            "ts": __import__("time").time(),
        })
    except Exception:
        pass
    return event_id


def emit_info(et: str, **kw): return emit_event(et, level="info", **kw)
def emit_warn(et: str, **kw): return emit_event(et, level="warn", **kw)
def emit_error(et: str, **kw): return emit_event(et, level="error", **kw)
def emit_critical(et: str, **kw): return emit_event(et, level="critical", **kw)
