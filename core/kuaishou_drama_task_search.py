# -*- coding: utf-8 -*-
"""kuaishou_drama_task_search — 对齐 KS184 `KuaishouCreatorPublisher.search_drama_task`.

Endpoint (Frida-verified 2026-04-19):
    POST https://cp.kuaishou.com/rest/cp/works/v2/video/pc/relation/banner/list
         ?__NS_sig3=<sig3>

Body (JSON, ensure_ascii=False):
    {
        "type": <int>,            # 10=yingguang(萤光), xinghuo code 待 probe
        "title": "<drama_name>",
        "cursor": "",
        "kuaishou.web.cp.api_ph": "<per-account api_ph>"
    }

Response envelope:
    {
        "result": 1,
        "data": {"list": [...], "cursor": "no_more" | "<next>"},
        "message": "成功"
    }

两种 list 元素 shape (对齐 memscan docstring):
    - 萤光 (yingguang, type=10):
        {bannerTaskId, entranceType, bindTaskType, canParticipate,
         startTime, endTime, title}
    - 星火 (xinghuo, type=?):
        {taskId, bindId, entranceType, bindType, taskType, title}

CXT (橙星推) reuses the xinghuo shape (bindId + taskId).

Usage
-----
    from core.kuaishou_drama_task_search import (
        search_drama_task, TASK_TYPE_CODE, guess_shape,
    )
    result = search_drama_task(
        cookie_str, api_ph, drama_title="仙尊下山", type_code=10,
    )
    # result: {"ok": True, "items": [...], "cursor": "...", "raw": {...}}

Probe
-----
    scripts/probe_drama_task_types.py 会枚举 1..15 各 type 值,
    返回 items 非空 + 含 "bindId"/"taskId" 的即为 xinghuo code.

Design note
-----------
- 严格 `ensure_ascii=False` 序列化 body, 和 sig3 输入对齐
- 用 `curl_cffi` Chrome120 TLS 指纹 (cp.kuaishou.com 做 JA3 校验)
- 支持 full pagination (cursor 回灌, 默认抓第一页)
- 不写任何状态到 DB, 纯查询模块
"""
from __future__ import annotations

import json
import logging
import time
from typing import Any, Optional

from curl_cffi import requests as cr_requests

from core.sig_service import SigService

log = logging.getLogger(__name__)

# ---------------------------------------------------------------------
# 常量
# ---------------------------------------------------------------------

CP_BASE = "https://cp.kuaishou.com/rest/cp/works/v2/video/pc"
ENDPOINT = f"{CP_BASE}/relation/banner/list"

# 已知 type_code → task_type 映射
# - 10 → 萤光 (Frida 17 samples + downstream submit.bannerTask.entranceType=10)
# - xinghuo / spark_cxt → 需要 probe (scripts/probe_drama_task_types.py)
#
# 这个表是 RUNTIME 可覆盖的 — 一旦 probe 发现真实值, 脚本把结果更新到
# app_config['publisher.drama_task_search.xinghuo_type_code'] 即可 (get() 会读新值)
TASK_TYPE_CODE: dict[str, int] = {
    "yingguang": 10,
    "firefly":   10,   # alias
    # xinghuo/spark/cxt: 待 probe. 如果已 probe 过, 通过 app_config 覆盖.
    # 候选 (根据 spark-plan-quest-detail/?layoutType=4 URL 提示): 4
    "xinghuo":   4,   # tentative, 等 probe 验证
    "spark":     4,   # alias
    "cxt":       4,   # 橙星推 reuse xinghuo shape
}


# ---------------------------------------------------------------------
# HTTP 默认 headers (对齐 publisher._post_signed)
# ---------------------------------------------------------------------

_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "zh-CN,zh;q=0.9",
    "Origin": "https://cp.kuaishou.com",
    "Referer": "https://cp.kuaishou.com/",
    "Content-Type": "application/json;charset=UTF-8",
}


# ---------------------------------------------------------------------
# Session (module-level, 复用 curl-cffi TLS)
# ---------------------------------------------------------------------

_SESSION: Optional[cr_requests.Session] = None
_SIG_SVC: Optional[SigService] = None


def _session() -> cr_requests.Session:
    global _SESSION
    if _SESSION is None:
        _SESSION = cr_requests.Session(impersonate="chrome120")
    return _SESSION


def _sig_service() -> SigService:
    global _SIG_SVC
    if _SIG_SVC is None:
        _SIG_SVC = SigService()
    return _SIG_SVC


# ---------------------------------------------------------------------
# Core: single-page search
# ---------------------------------------------------------------------

def search_drama_task(
    cookie_str: str,
    api_ph: str,
    drama_title: str,
    *,
    type_code: int = 10,
    cursor: str = "",
    timeout: int = 15,
    sig_service: Optional[SigService] = None,
) -> dict[str, Any]:
    """Single-page drama task search.

    Parameters
    ----------
    cookie_str : str
        Cookie header for cp.kuaishou.com (domain='cp', from CookieManager).
    api_ph : str
        Per-account ``kuaishou.web.cp.api_ph`` token.
    drama_title : str
        Exact drama name to match. KS184 passes 完整剧名; server does fuzzy match.
    type_code : int
        Task category. 10=yingguang. xinghuo/cxt → probe via
        ``scripts/probe_drama_task_types.py``.
    cursor : str
        Pagination cursor. "" for first page. Server returns "no_more" at end.

    Returns
    -------
    dict
        ``{
            "ok": bool,
            "result_code": int,      # 1 = success, others = server error
            "items": list[dict],     # raw list entries from data.list
            "cursor": str,           # next cursor (or "no_more")
            "message": str,          # server message (often "成功")
            "raw": dict,             # full decoded response
            "error": str | None,     # network/parse error
        }``
    """
    sig = (sig_service or _sig_service())
    payload = {
        "type": int(type_code),
        "title": drama_title,
        "cursor": cursor,
        "kuaishou.web.cp.api_ph": api_ph,
    }

    # sig3 签名 — 注意 payload 里 cursor 为空串不能省, 必须完整入签
    sig3 = sig.sign_payload(payload)
    full_url = f"{ENDPOINT}?__NS_sig3={sig3}"

    # body 用 ensure_ascii=False (和 sig 输入字节一致)
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")

    headers = dict(_HEADERS)
    if cookie_str:
        headers["Cookie"] = cookie_str

    try:
        resp = _session().post(full_url, data=body, headers=headers, timeout=timeout)
        resp.raise_for_status()
        raw = resp.json() if resp.content else {}
    except Exception as e:
        log.warning("[DramaTaskSearch] %s type=%s title=%r — network error: %s",
                    ENDPOINT, type_code, drama_title, e)
        return {
            "ok": False, "result_code": None, "items": [], "cursor": "",
            "message": "", "raw": {}, "error": f"network: {e}",
        }

    rc = raw.get("result")
    data = raw.get("data") if isinstance(raw, dict) else None
    items = (data or {}).get("list") or [] if isinstance(data, dict) else []
    next_cursor = (data or {}).get("cursor", "") if isinstance(data, dict) else ""
    msg = raw.get("message", "") if isinstance(raw, dict) else ""

    return {
        "ok": rc == 1,
        "result_code": rc,
        "items": items,
        "cursor": next_cursor,
        "message": msg,
        "raw": raw,
        "error": None if rc == 1 else f"result={rc} message={msg!r}",
    }


# ---------------------------------------------------------------------
# Shape detection
# ---------------------------------------------------------------------

XINGHUO_REQUIRED_FIELDS = {"taskId", "bindId"}
YINGGUANG_REQUIRED_FIELDS = {"bannerTaskId"}


def guess_shape(item: dict[str, Any]) -> str:
    """Classify list entry by shape.

    Returns:  "xinghuo" | "yingguang" | "unknown"
    """
    if not isinstance(item, dict):
        return "unknown"
    keys = set(item.keys())
    if XINGHUO_REQUIRED_FIELDS.issubset(keys):
        return "xinghuo"
    if YINGGUANG_REQUIRED_FIELDS.issubset(keys):
        return "yingguang"
    return "unknown"


# ---------------------------------------------------------------------
# Convenience: search all pages
# ---------------------------------------------------------------------

def search_all(
    cookie_str: str,
    api_ph: str,
    drama_title: str,
    *,
    type_code: int = 10,
    max_pages: int = 5,
    sleep_between: float = 0.2,
    **kwargs,
) -> dict[str, Any]:
    """Iterate all pages until cursor == "no_more" or max_pages reached."""
    all_items: list[dict] = []
    cursor = ""
    last_raw: dict[str, Any] = {}
    for page in range(1, max_pages + 1):
        r = search_drama_task(
            cookie_str, api_ph, drama_title,
            type_code=type_code, cursor=cursor, **kwargs,
        )
        last_raw = r
        if not r["ok"]:
            break
        all_items.extend(r["items"])
        cursor = r["cursor"]
        if not cursor or cursor == "no_more":
            break
        if sleep_between:
            time.sleep(sleep_between)

    return {
        "ok": last_raw.get("ok", False),
        "items": all_items,
        "pages": page,
        "final_cursor": cursor,
        "last": last_raw,
    }


# ---------------------------------------------------------------------
# Helper: convenient wrapper by task_type string + app_config integration
# ---------------------------------------------------------------------

def resolve_type_code(task_type: str) -> int:
    """Resolve task_type string to int type_code.

    Checks app_config first (lets probe update live without code change):
      ``publisher.drama_task_search.<task_type>_type_code``

    Falls back to TASK_TYPE_CODE dict.
    """
    try:
        from core.app_config import get as cfg_get
        key = f"publisher.drama_task_search.{task_type}_type_code"
        v = cfg_get(key, None)
        if v is not None:
            return int(v)
    except Exception:
        pass
    return TASK_TYPE_CODE.get(task_type, 10)


def search_for_task_type(
    cookie_str: str,
    api_ph: str,
    drama_title: str,
    *,
    task_type: str = "yingguang",
    **kwargs,
) -> dict[str, Any]:
    """Convenience wrapper: search_drama_task by task_type string.

    task_type ∈ {"yingguang", "firefly", "xinghuo", "spark", "cxt"}
    """
    tc = resolve_type_code(task_type)
    return search_drama_task(
        cookie_str, api_ph, drama_title, type_code=tc, **kwargs,
    )


__all__ = [
    "CP_BASE", "ENDPOINT", "TASK_TYPE_CODE",
    "search_drama_task", "search_all", "search_for_task_type",
    "guess_shape", "resolve_type_code",
    "XINGHUO_REQUIRED_FIELDS", "YINGGUANG_REQUIRED_FIELDS",
]
