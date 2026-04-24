# -*- coding: utf-8 -*-
"""通知抽象层 — 失败/告警推到 Telegram/企业微信/dashboard.

设计:
  1. 多 channel 并行 (console 总是开, 其他按 app_config 开关)
  2. 每条通知走一条记录到 system_events 表 (可审计)
  3. 级别: info / warning / error / critical
  4. rate-limit: 同一 title 同级别 5 分钟内只推 1 次 (避免刷屏)

使用:
    from core.notifier import notify
    notify("下载失败", "剧《XX》所有 URL 失效, 请补链接",
           level="error", extra={"drama_name": "XX", "urls_tried": 3})

配置项 (app_config):
    notifier.console.enabled          = true
    notifier.telegram.enabled         = false
    notifier.telegram.bot_token       = (empty, 用户填)
    notifier.telegram.chat_id         = (empty)
    notifier.wecom.enabled            = false
    notifier.wecom.webhook_url        = (empty)
    notifier.dashboard.enabled        = true   (写 system_events 表)
    notifier.rate_limit_sec           = 300    (5 分钟去重)
"""
from __future__ import annotations

import json
import logging
import sqlite3
import threading
import time
from typing import Any

import requests

from core.app_config import get as cfg_get

log = logging.getLogger(__name__)

LEVELS = ("info", "warning", "error", "critical")
_ANSI = {
    "info":     "\x1b[36m",   # cyan
    "warning":  "\x1b[33m",   # yellow
    "error":    "\x1b[31m",   # red
    "critical": "\x1b[35m",   # magenta
}
_RESET = "\x1b[0m"

# rate-limit state: (title, level) -> last_ts
_rate_state: dict[tuple, float] = {}
_rate_lock = threading.Lock()


def _ensure_events_table() -> None:
    """首次使用时确认 system_events 表存在. 适配现有 schema:
      event_type / event_level / source_module / entity_type / entity_id
      / payload / created_at / acknowledged / acknowledged_at / acknowledged_by
    """
    from core.config import DB_PATH
    c = sqlite3.connect(DB_PATH, timeout=10)
    # 如果表不存在就按现有 schema 建
    c.execute("""
        CREATE TABLE IF NOT EXISTS system_events (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          event_type TEXT NOT NULL,
          event_level TEXT,
          source_module TEXT,
          entity_type TEXT,
          entity_id TEXT,
          payload TEXT,
          created_at TEXT DEFAULT (datetime('now','localtime')),
          acknowledged INTEGER DEFAULT 0,
          acknowledged_at TEXT,
          acknowledged_by TEXT
        )
    """)
    c.execute("CREATE INDEX IF NOT EXISTS idx_events_created ON system_events(created_at)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_events_level ON system_events(event_level)")
    c.commit()
    c.close()


_table_ready = False


def _rate_limit_check(title: str, level: str) -> bool:
    """True = 允许发, False = 被限流."""
    limit_sec = cfg_get("notifier.rate_limit_sec", 300)
    key = (title, level)
    now = time.time()
    with _rate_lock:
        last = _rate_state.get(key, 0)
        if now - last < limit_sec:
            return False
        _rate_state[key] = now
    return True


def _send_console(title: str, body: str, level: str) -> bool:
    if not cfg_get("notifier.console.enabled", True):
        return False
    color = _ANSI.get(level, "")
    print(f"\n{color}[{level.upper()}] {title}{_RESET}")
    if body:
        for line in body.split("\n"):
            print(f"  {line}")
    return True


def _send_telegram(title: str, body: str, level: str) -> bool:
    if not cfg_get("notifier.telegram.enabled", False):
        return False
    token = cfg_get("notifier.telegram.bot_token", "")
    chat_id = cfg_get("notifier.telegram.chat_id", "")
    if not token or not chat_id:
        log.warning("[notifier] telegram 开启但未配置 bot_token/chat_id")
        return False

    emoji = {"info": "ℹ️", "warning": "⚠️", "error": "❌", "critical": "🚨"}
    text = f"{emoji.get(level, '')} *{title}*\n\n{body}"
    try:
        r = requests.post(
            f"https://api.telegram.org/bot{token}/sendMessage",
            json={"chat_id": chat_id, "text": text, "parse_mode": "Markdown"},
            timeout=10,
        )
        return r.status_code == 200
    except Exception as e:
        log.warning("[notifier] telegram send failed: %s", e)
        return False


def _send_wecom(title: str, body: str, level: str) -> bool:
    """企业微信群机器人 webhook."""
    if not cfg_get("notifier.wecom.enabled", False):
        return False
    url = cfg_get("notifier.wecom.webhook_url", "")
    if not url:
        return False

    emoji = {"info": "ℹ️", "warning": "⚠️", "error": "❌", "critical": "🚨"}
    content = f"{emoji.get(level, '')} {title}\n\n{body}"
    try:
        r = requests.post(url, json={"msgtype": "text", "text": {"content": content}},
                         timeout=10)
        return r.status_code == 200
    except Exception as e:
        log.warning("[notifier] wecom send failed: %s", e)
        return False


def _record_dashboard(title: str, body: str, level: str, source: str,
                      extra: dict | None, delivered: list[str]) -> bool:
    """写 system_events 表 (让 dashboard SSE 推给前端).

    Payload 打包: {body, extra, delivered_to}
    """
    if not cfg_get("notifier.dashboard.enabled", True):
        return False
    try:
        from core.config import DB_PATH
        payload = {
            "body": body,
            "extra": extra or {},
            "delivered_to": delivered,
        }
        c = sqlite3.connect(DB_PATH, timeout=10)
        c.execute(
            """INSERT INTO system_events
                 (event_type, event_level, source_module, entity_type, entity_id, payload)
               VALUES (?, ?, ?, ?, ?, ?)""",
            ("notify", level, source or "notifier", "notification", title,
             json.dumps(payload, ensure_ascii=False)),
        )
        c.commit()
        c.close()
        return True
    except Exception as e:
        log.warning("[notifier] dashboard record failed: %s", e)
        return False


def notify(
    title: str,
    body: str = "",
    level: str = "info",
    source: str = "",
    extra: dict[str, Any] | None = None,
    bypass_rate_limit: bool = False,
) -> dict:
    """发送通知到所有开启的 channel.

    Returns:
        dict: {"delivered": [...], "rate_limited": bool, "event_id": int|None}
    """
    global _table_ready
    if not _table_ready:
        _ensure_events_table()
        _table_ready = True

    if level not in LEVELS:
        level = "info"

    # rate-limit (critical 级不限流)
    if not bypass_rate_limit and level != "critical":
        if not _rate_limit_check(title, level):
            return {"delivered": [], "rate_limited": True, "event_id": None}

    delivered: list[str] = []
    if _send_console(title, body, level):
        delivered.append("console")
    if _send_telegram(title, body, level):
        delivered.append("telegram")
    if _send_wecom(title, body, level):
        delivered.append("wecom")
    _record_dashboard(title, body, level, source, extra, delivered)

    return {"delivered": delivered, "rate_limited": False, "event_id": None}
