# -*- coding: utf-8 -*-
"""浏览器驱动的扫码登录 — 真正可用的扫码流程.

流程:
  1. 启 Chrome 打开 https://www.kuaishou.com/login (或 cp 登录页)
  2. 用户手机扫码确认
  3. 后台轮询 CDP: 当页面 URL 跳转 + `passToken` cookie 出现 = 登录成功
  4. 拉全部 cookie → 用 cookie_parser 规范化 → 用 cookie_validator 验证 → 存 device_accounts

比 httpx 版本稳 10 倍 — 不用研究快手 passport API 的 sign 算法.
"""
from __future__ import annotations

import json
import secrets
import threading
import time
from typing import Any

from core.logger import get_logger
from core.browser_launcher import BrowserLauncher, fetch_cookies_from_chrome
from core.cookie_parser import build_account_cookies_json, extract_user_id
from core.cookie_validator import validate_cookie_string

log = get_logger("browser_qrlogin")


# session_id → state
_LOGIN_SESSIONS: dict[str, dict] = {}


LOGIN_URL_OPTIONS = {
    "cp":    "https://cp.kuaishou.com/login",
    "www":   "https://www.kuaishou.com",
    "pass":  "https://passport.kuaishou.com/pc/passport/login?sid=kwai_cp",
}


def start_login(db_manager, login_url_code: str = "cp",
                headless: bool = False) -> dict[str, Any]:
    """启动浏览器, 返回 session_id + 浏览器信息."""
    url = LOGIN_URL_OPTIONS.get(login_url_code, LOGIN_URL_OPTIONS["cp"])
    session_id = secrets.token_hex(12)

    launcher = BrowserLauncher(db_manager=db_manager)
    # account_id 用 0 当"待分配"
    r = launcher.launch_for_account(
        account_id=0,
        target_url=url,
        inject_cookies=False,   # 登录时不注入已有 cookie
        headless=headless,
    )
    if not r.get("ok"):
        return {"ok": False, "error": r.get("error")}

    _LOGIN_SESSIONS[session_id] = {
        "pid": r["pid"],
        "port": r["port"],
        "login_url": url,
        "started_at": time.time(),
        "status": "waiting",
        "result": None,
    }

    # 异步轮询 (最多 5 分钟)
    t = threading.Thread(
        target=_poll_login_loop,
        args=(db_manager, session_id),
        daemon=True,
    )
    t.start()

    return {
        "ok": True,
        "session_id": session_id,
        "port": r["port"],
        "login_url": url,
        "pid": r["pid"],
    }


def _poll_login_loop(db_manager, session_id: str, max_seconds: int = 300) -> None:
    """后台轮询直到登录成功或超时."""
    sess = _LOGIN_SESSIONS.get(session_id)
    if not sess:
        return
    port = sess["port"]
    t0 = time.time()

    while time.time() - t0 < max_seconds:
        if _LOGIN_SESSIONS.get(session_id) is None:
            return   # 外部取消
        time.sleep(3)

        cookies = fetch_cookies_from_chrome(port)
        if not cookies:
            continue

        # 关键信号: userId 出现 (已登录)
        user_id = None
        has_pass_token = False
        for c in cookies:
            if c.get("name") == "userId" and c.get("value"):
                user_id = str(c["value"])
            if c.get("name") == "passToken" and c.get("value"):
                has_pass_token = True
        if not user_id:
            continue

        # 已登录! 拉 cookie + 规范化 + 验证
        log.info("[qr_login %s] detected userId=%s (passToken=%s)",
                 session_id, user_id, has_pass_token)

        sess["status"] = "validating"
        cookies_json = build_account_cookies_json(
            cookies, login_method="browser_login",
        )
        validation = validate_cookie_string(
            cookies_json.get("creator_cookie", "")
            or cookies_json.get("cookies", [{}])[0].get("value", ""),
            timeout=6,
        )
        if validation.get("ok"):
            cookies_json["user_info"] = {
                "userId": user_id,
                "userName": validation.get("user_name") or "",
                "userHead": validation.get("user_avatar") or "",
            }

        # 保存到 device_accounts
        save_res = _save_account(db_manager, user_id, cookies_json, validation)
        # ★ 2026-04-23 Bug 4: 只有 save 真成功 (created/updated) 才标 login_success.
        # save_failed 时前端显"保存失败", 避免"扫码成功但账号没入库"的误导.
        if save_res.get("action") in ("created", "updated"):
            sess["status"] = "login_success"
        else:
            sess["status"] = "save_failed"
            log.warning("[qr_login %s] save_failed: %s",
                        session_id, save_res.get("error"))
        sess["result"] = {
            "user_id": user_id,
            "validation": validation,
            "save": save_res,
        }

        # 审计
        try:
            db_manager.conn.execute(
                """INSERT INTO account_qr_login_attempts
                     (qr_id, status, user_id, user_name, finished_at)
                   VALUES (?, ?, ?, ?, datetime('now','localtime'))""",
                (session_id, sess["status"], user_id,
                 validation.get("user_name", "")),
            )
            db_manager.conn.commit()
        except Exception:
            pass
        return

    sess["status"] = "timeout"
    log.warning("[qr_login %s] timeout after %ds", session_id, max_seconds)


def _save_account(db_manager, user_id: str, cookies_json: dict,
                  validation: dict) -> dict:
    """保存登录成功的账号到 device_accounts."""
    try:
        existing = db_manager.conn.execute(
            "SELECT id FROM device_accounts WHERE kuaishou_uid=?", (user_id,)
        ).fetchone()
        name = validation.get("user_name") or f"ks_{user_id}"
        cookies_blob = json.dumps(cookies_json, ensure_ascii=False)

        if existing:
            db_manager.conn.execute(
                """UPDATE device_accounts SET
                     cookies=?,
                     login_status='logged_in',
                     cookie_last_success_at=datetime('now','localtime'),
                     account_name=COALESCE(NULLIF(account_name,''), ?),
                     kuaishou_name=COALESCE(NULLIF(kuaishou_name,''), ?),
                     avatar_url=COALESCE(NULLIF(avatar_url,''), ?)
                   WHERE kuaishou_uid=?""",
                (cookies_blob, name, name,
                 validation.get("user_avatar", ""), user_id),
            )
            db_manager.conn.commit()
            return {"action": "updated", "id": existing[0], "uid": user_id}
        else:
            # ★ 2026-04-23 Bug 4 修复: device_accounts.device_serial + account_id
            # 是 NOT NULL, 老代码漏字段 → INSERT 失败被 except 吞, 导致扫码假成功.
            # 按现有 13 账号的惯例: device_serial='no_device' (API-only 账号无真机),
            # account_id = f'acc_{sha1(uid)[:8]}' (legacy KS184 复合键格式).
            import hashlib
            account_id_legacy = f"acc_{hashlib.sha1(str(user_id).encode()).hexdigest()[:8]}"
            # numeric_uid 从 user_id 推 (如果是纯数字)
            try:
                numeric_uid = int(user_id) if str(user_id).isdigit() else 0
            except (TypeError, ValueError):
                numeric_uid = 0
            cur = db_manager.conn.execute(
                """INSERT INTO device_accounts
                     (device_serial, account_id,
                      account_name, kuaishou_uid, kuaishou_name, numeric_uid,
                      login_status, is_active, cookies,
                      cookie_last_success_at, avatar_url,
                      lifecycle_stage, signed_status)
                   VALUES ('no_device', ?,
                           ?, ?, ?, ?, 'logged_in', 1, ?,
                           datetime('now','localtime'), ?,
                           'startup', 'unknown')""",
                (account_id_legacy,
                 name, user_id, name, numeric_uid, cookies_blob,
                 validation.get("user_avatar", "")),
            )
            db_manager.conn.commit()
            return {"action": "created", "id": cur.lastrowid, "uid": user_id,
                    "name": name, "account_id": account_id_legacy}
    except Exception as e:
        # ★ Bug 4: 老代码异常被吞, 前端 alert 登录成功但 DB 无数据. 现在 log 出来.
        import traceback
        log.error("[qr_login/_save_account] failed user_id=%s err=%s\n%s",
                   user_id, e, traceback.format_exc())
        return {"action": "failed", "error": str(e)}


# ---------------------------------------------------------------------------
# 查询 session 状态
# ---------------------------------------------------------------------------

def get_status(session_id: str) -> dict[str, Any]:
    sess = _LOGIN_SESSIONS.get(session_id)
    if not sess:
        return {"ok": False, "status": "unknown"}
    elapsed = int(time.time() - sess["started_at"])
    return {
        "ok": True,
        "status": sess["status"],          # waiting / validating / login_success / timeout
        "elapsed_seconds": elapsed,
        "port": sess.get("port"),
        "login_url": sess.get("login_url"),
        "result": sess.get("result"),
    }


def cancel(session_id: str) -> dict[str, Any]:
    sess = _LOGIN_SESSIONS.pop(session_id, None)
    if not sess:
        return {"ok": False}
    # 关 Chrome
    try:
        launcher = BrowserLauncher()
        launcher.stop(sess["pid"])
    except Exception:
        pass
    return {"ok": True}


def cleanup_old(max_age: int = 600) -> int:
    """清 10 分钟以上的 session."""
    now = time.time()
    expired = [sid for sid, s in _LOGIN_SESSIONS.items()
               if now - s["started_at"] > max_age]
    for sid in expired:
        cancel(sid)
    return len(expired)
