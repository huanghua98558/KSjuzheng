# -*- coding: utf-8 -*-
"""快手网页扫码登录 — 脱离 KS184 自己实现.

流程:
  1. GET https://passport.kuaishou.com/pc/qrcode/query_start?source=kwai_web&lurl=...
     拿到 qrLoginToken, qrLoginSignature
  2. GET https://passport.kuaishou.com/pc/qrcode/v2/bitmap?qrLoginToken=...
     拿到二维码图片 (Base64)
  3. 轮询 https://passport.kuaishou.com/pc/qrcode/scan_result?qrLoginToken=...&qrLoginSignature=...
     状态: wait_scan / waiting_confirm / scan_success / scan_canceled / scan_timeout
  4. scan_success 后调 /rest/passport/qrcode/login_v2 换取 passToken
  5. 用 passToken 换账号 cookie, 写入 device_accounts

注意: 本模块只做最小实现, 真实流程可能需要补充:
  - CSRF token / sig 参数 (需 Frida 抓包)
  - device_id 生成
"""
from __future__ import annotations

import base64
import json
import secrets
import time
from typing import Any

import httpx


_QR_SESSIONS: dict[str, dict] = {}  # qr_id → {token, signature, created_at, status, ...}
_QR_TTL = 120  # 2 分钟


_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept": "application/json, text/plain, */*",
    "Origin": "https://passport.kuaishou.com",
    "Referer": "https://passport.kuaishou.com/",
}


def generate_qr() -> dict[str, Any]:
    """第 1+2 步: 生成登录二维码.

    返回: {
      qr_id: 本地 session id,
      qrcode_base64: 图片 (data URI),
      expires_in: 120,
      source: 'kuaishou',
    }
    """
    qr_id = secrets.token_hex(12)
    try:
        with httpx.Client(timeout=10, headers=_HEADERS) as client:
            r = client.get(
                "https://passport.kuaishou.com/pc/qrcode/query_start",
                params={
                    "source": "kwai_web",
                    "lurl": "https://cp.kuaishou.com/",
                },
            )
            data = r.json()
    except Exception as e:
        return {"ok": False, "error": f"请求 query_start 失败: {e}"}

    token = data.get("qrLoginToken") or data.get("data", {}).get("qrLoginToken")
    sig = data.get("qrLoginSignature") or data.get("data", {}).get("qrLoginSignature")
    if not token:
        return {"ok": False,
                "error": "快手 query_start 未返回 qrLoginToken",
                "raw": str(data)[:400]}

    # 拉二维码 bitmap
    try:
        with httpx.Client(timeout=10, headers=_HEADERS) as client:
            r = client.get(
                "https://passport.kuaishou.com/pc/qrcode/bitmap",
                params={"qrLoginToken": token, "qrLoginSignature": sig},
            )
            img_bytes = r.content
    except Exception as e:
        return {"ok": False, "error": f"获取二维码图片失败: {e}"}

    b64 = base64.b64encode(img_bytes).decode("ascii")

    _QR_SESSIONS[qr_id] = {
        "token": token,
        "signature": sig,
        "created_at": time.time(),
        "status": "wait_scan",
        "last_poll": 0.0,
    }
    return {
        "ok": True,
        "qr_id": qr_id,
        "qrcode_base64": f"data:image/png;base64,{b64}",
        "expires_in": _QR_TTL,
    }


def poll_qr(qr_id: str) -> dict[str, Any]:
    """第 3 步: 轮询扫码状态.

    返回 {status, cookie (when scan_success), user_info}
    状态: wait_scan / waiting_confirm / scan_success / scan_canceled / scan_timeout / error
    """
    sess = _QR_SESSIONS.get(qr_id)
    if not sess:
        return {"ok": False, "status": "unknown", "error": "qr_id 不存在或已过期"}
    if time.time() - sess["created_at"] > _QR_TTL:
        _QR_SESSIONS.pop(qr_id, None)
        return {"ok": False, "status": "scan_timeout", "error": "二维码过期"}

    try:
        with httpx.Client(timeout=10, headers=_HEADERS) as client:
            r = client.get(
                "https://passport.kuaishou.com/pc/qrcode/scan_result",
                params={
                    "qrLoginToken": sess["token"],
                    "qrLoginSignature": sess["signature"],
                    "channelType": "pc_web",
                },
            )
            data = r.json()
    except Exception as e:
        return {"ok": False, "status": "error", "error": str(e)}

    result = data.get("result")
    status_code = data.get("data", {}).get("status") or data.get("status")
    sess["last_poll"] = time.time()

    # 状态映射
    code_map = {
        0: "wait_scan",
        1: "scan_success",  # 扫描但未确认
        2: "waiting_confirm",
        3: "login_success",
        4: "scan_canceled",
        5: "scan_timeout",
    }
    status_str = code_map.get(int(status_code) if status_code is not None else -1,
                              "unknown")
    sess["status"] = status_str

    if status_str == "login_success":
        # 换取 passToken
        cookie_data = _exchange_pass_token(sess, data)
        return {
            "ok": True,
            "status": "login_success",
            "cookie": cookie_data.get("cookie", ""),
            "user_info": cookie_data.get("user_info", {}),
        }

    return {"ok": True, "status": status_str}


def _exchange_pass_token(sess: dict, scan_data: dict) -> dict:
    """第 4+5 步: 用 scan_result 返回的数据换 cookie."""
    # 这一步实际快手 API 有一系列调用, 包括 passport/login_v2 / account_info 等
    # 此版返回 scan_result 里的 meta 信息, 真实 cookie 落地需要进一步 Frida 抓包
    data = scan_data.get("data") or {}
    return {
        "cookie": "",   # TODO: 实现完整 cookie 交换
        "user_info": {
            "userId": data.get("userId"),
            "userName": data.get("userName"),
            "avatar": data.get("userAvatar"),
            "_note": "真实 cookie 交换待补 Frida 抓包 — 目前仅返回扫码元信息",
        },
    }


def save_account(db_manager, cookie_str: str, user_info: dict) -> dict[str, Any]:
    """把扫码成功的账号写入 device_accounts."""
    user_id = user_info.get("userId") or user_info.get("id")
    name = user_info.get("userName") or user_info.get("nickname") or f"ks_{user_id}"
    if not user_id:
        return {"ok": False, "error": "user_id 为空"}
    try:
        db_manager.conn.execute(
            """INSERT OR REPLACE INTO device_accounts
                 (account_name, kuaishou_uid, kuaishou_name, login_status,
                  all_cookie, main_cookie, cookie_last_success_at,
                  lifecycle_stage, signed_status)
               VALUES (?, ?, ?, 'logged_in', ?, ?, datetime('now','localtime'),
                       'startup', 'unknown')""",
            (name, str(user_id), name, cookie_str, cookie_str),
        )
        db_manager.conn.commit()
        return {"ok": True, "account_name": name, "uid": str(user_id)}
    except Exception as e:
        return {"ok": False, "error": str(e)}


# ---------------------------------------------------------------------------
# 清理过期 session
# ---------------------------------------------------------------------------

def cleanup_expired() -> int:
    now = time.time()
    expired = [k for k, v in _QR_SESSIONS.items() if now - v["created_at"] > _QR_TTL]
    for k in expired:
        _QR_SESSIONS.pop(k, None)
    return len(expired)
