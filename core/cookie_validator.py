# -*- coding: utf-8 -*-
"""Cookie 有效性验证 + 自动提取用户信息.

验证策略:
  - POST 到 cp.kuaishou.com 的 banner/list 接口 (不需要 sig3)
  - 返回 result=1 = 有效
  - 顺便解析用户基础信息 (if any)

提取用户信息:
  - 调 cp.kuaishou.com/rest/cp/account/basic (简单无签名接口)
  - 拿到 userName, userHead
"""
from __future__ import annotations

from typing import Any

import httpx


_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept": "application/json, text/plain, */*",
    "Origin": "https://cp.kuaishou.com",
    "Referer": "https://cp.kuaishou.com/",
    "Content-Type": "application/json",
}


def validate_cookie_string(cookie_str: str, timeout: float = 8.0) -> dict[str, Any]:
    """调快手 cp API 看 cookie 是否 live.

    返回: {
      ok: True/False,
      user_id: str,
      user_name: str,
      user_avatar: str,
      reason: str,  # 失败原因
      endpoint: str,
    }
    """
    if not cookie_str or "=" not in cookie_str:
        return {"ok": False, "reason": "cookie 为空或格式不对"}

    headers = {**_HEADERS, "Cookie": cookie_str}

    # 1. 验证 cookie (banner/list)
    try:
        with httpx.Client(headers=headers, timeout=timeout) as client:
            r = client.post(
                "https://cp.kuaishou.com/rest/cp/works/v2/video/pc/relation/banner/list",
                json={"pcursor": "", "count": 1},
            )
            data = r.json()
    except Exception as e:
        return {"ok": False, "reason": f"请求失败: {type(e).__name__}: {e}"}

    result_code = data.get("result")
    if result_code != 1:
        return {
            "ok": False,
            "reason": f"API result={result_code}, "
                      f"error={data.get('error_msg', data.get('errorMsg', 'unknown'))}",
            "endpoint": "banner/list",
        }

    info: dict[str, Any] = {
        "ok": True,
        "user_id": "",
        "user_name": "",
        "user_avatar": "",
        "endpoint": "banner/list",
    }

    # 2. 尝试拿 user info
    try:
        with httpx.Client(headers=headers, timeout=timeout) as client:
            r2 = client.post(
                "https://cp.kuaishou.com/rest/cp/user/basic",
                json={},
            )
            d2 = r2.json()
            if d2.get("result") == 1:
                u = d2.get("data") or d2.get("userInfo") or {}
                info["user_id"] = str(u.get("userId") or u.get("user_id") or "")
                info["user_name"] = u.get("userName") or u.get("user_name") or ""
                info["user_avatar"] = u.get("userHead") or u.get("headUrl") or ""
    except Exception:
        pass

    # 3. 退而求其次: 从 cookie 里取 userId
    if not info["user_id"]:
        for pair in cookie_str.split(";"):
            k, _, v = pair.strip().partition("=")
            if k.strip().lower() == "userid":
                info["user_id"] = v.strip()
                break

    return info


def validate_cookies_dict(cookies_dict: dict, timeout: float = 8.0) -> dict[str, Any]:
    """接受规范化的 cookies dict (device_accounts.cookies JSON), 用 creator_cookie 验证."""
    cookie_str = cookies_dict.get("creator_cookie", "")
    if not cookie_str and isinstance(cookies_dict.get("cookies"), list):
        # 从 list 重建
        cookie_str = "; ".join(
            f"{c['name']}={c['value']}"
            for c in cookies_dict["cookies"]
            if c.get("name") and c.get("value")
        )
    return validate_cookie_string(cookie_str, timeout=timeout)
