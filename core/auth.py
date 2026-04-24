# -*- coding: utf-8 -*-
"""认证 / 授权 / 审计核心模块.

- bcrypt 密码哈希校验
- JWT 发放 / 校验 (HS256, jti, 24h 过期)
- jti 黑名单 (user_sessions.revoked_at)
- 角色 (admin / operator / viewer) + 装饰器强校验
- 审计日志 append-only
"""
from __future__ import annotations

import logging
import secrets
import sqlite3
import time
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

import bcrypt
import jwt
from fastapi import HTTPException, Request, status

from core.config import DB_PATH

log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

JWT_ALGO = "HS256"
JWT_TTL_SECONDS = 24 * 3600   # 24h

ROLE_ADMIN = "admin"
ROLE_OPERATOR = "operator"
ROLE_VIEWER = "viewer"
_ROLE_RANK = {ROLE_VIEWER: 1, ROLE_OPERATOR: 2, ROLE_ADMIN: 3}


def _db() -> sqlite3.Connection:
    c = sqlite3.connect(DB_PATH, check_same_thread=False, timeout=30.0,
                        isolation_level=None)
    c.execute("PRAGMA busy_timeout=30000")
    c.row_factory = sqlite3.Row
    return c


def _jwt_secret() -> str:
    """从 security_config 读 JWT_SECRET. 没有就新建."""
    conn = _db()
    try:
        row = conn.execute(
            "SELECT value FROM security_config WHERE key='jwt_secret'"
        ).fetchone()
        if row:
            return row["value"]
        # 首次启动 (理论上 migrate_v17 已经生成)
        secret = secrets.token_hex(64)
        conn.execute(
            "INSERT OR IGNORE INTO security_config (key, value) VALUES (?, ?)",
            ("jwt_secret", secret),
        )
        return secret
    finally:
        conn.close()


_SECRET_CACHE: str | None = None


def get_secret() -> str:
    global _SECRET_CACHE
    if _SECRET_CACHE is None:
        _SECRET_CACHE = _jwt_secret()
    return _SECRET_CACHE


# ---------------------------------------------------------------------------
# 密码
# ---------------------------------------------------------------------------

def hash_password(pw: str) -> str:
    return bcrypt.hashpw(pw.encode("utf-8"), bcrypt.gensalt()).decode("ascii")


def verify_password(pw: str, hashed: str) -> bool:
    try:
        return bcrypt.checkpw(pw.encode("utf-8"), hashed.encode("ascii"))
    except Exception:
        return False


# ---------------------------------------------------------------------------
# JWT
# ---------------------------------------------------------------------------

def issue_token(user_id: int, username: str, role: str,
                ip: str = "", user_agent: str = "") -> tuple[str, str]:
    """发 JWT 并落 user_sessions. 返回 (token, jti)."""
    jti = secrets.token_hex(16)
    now = datetime.now(timezone.utc)
    exp = now + timedelta(seconds=JWT_TTL_SECONDS)
    payload = {
        "sub": str(user_id),
        "username": username,
        "role": role,
        "jti": jti,
        "iat": int(now.timestamp()),
        "exp": int(exp.timestamp()),
    }
    token = jwt.encode(payload, get_secret(), algorithm=JWT_ALGO)

    conn = _db()
    try:
        conn.execute(
            """INSERT INTO user_sessions
                 (jti, user_id, username, expires_at, ip, user_agent)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (jti, user_id, username,
             exp.isoformat(sep=" ", timespec="seconds"),
             ip[:64], user_agent[:256]),
        )
    finally:
        conn.close()

    return token, jti


def verify_token(token: str) -> dict:
    """解析 JWT, 检查过期 + 黑名单. 失败抛 HTTPException(401)."""
    try:
        payload = jwt.decode(token, get_secret(), algorithms=[JWT_ALGO])
    except jwt.ExpiredSignatureError:
        raise HTTPException(status_code=401, detail="token expired")
    except jwt.InvalidTokenError as e:
        raise HTTPException(status_code=401, detail=f"invalid token: {e}")

    jti = payload.get("jti", "")
    if not jti:
        raise HTTPException(status_code=401, detail="token missing jti")

    conn = _db()
    try:
        row = conn.execute(
            """SELECT revoked_at FROM user_sessions WHERE jti=?""",
            (jti,),
        ).fetchone()
    finally:
        conn.close()
    if not row:
        raise HTTPException(status_code=401, detail="session not found")
    if row["revoked_at"]:
        raise HTTPException(status_code=401, detail="session revoked")

    return payload


def revoke_token(jti: str) -> None:
    conn = _db()
    try:
        conn.execute(
            """UPDATE user_sessions SET revoked_at=datetime('now','localtime')
               WHERE jti=? AND revoked_at IS NULL""",
            (jti,),
        )
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# 登录
# ---------------------------------------------------------------------------

def authenticate(username: str, password: str,
                 ip: str = "", ua: str = "") -> tuple[str, dict]:
    """验证用户名/密码, 成功返回 (token, user_info)."""
    conn = _db()
    try:
        row = conn.execute(
            """SELECT id, username, password_hash, role, display_name,
                      is_active, must_change_pw
               FROM users WHERE username=?""",
            (username,),
        ).fetchone()
    finally:
        conn.close()
    if not row:
        raise HTTPException(status_code=401, detail="bad credentials")
    if not row["is_active"]:
        raise HTTPException(status_code=403, detail="account disabled")
    if not verify_password(password, row["password_hash"]):
        raise HTTPException(status_code=401, detail="bad credentials")

    token, jti = issue_token(
        row["id"], row["username"], row["role"],
        ip=ip, user_agent=ua,
    )
    # 更新 last_login
    conn = _db()
    try:
        conn.execute(
            """UPDATE users SET last_login_at=datetime('now','localtime'),
                 last_login_ip=?, updated_at=datetime('now','localtime')
               WHERE id=?""",
            (ip[:64], row["id"]),
        )
    finally:
        conn.close()

    return token, {
        "id": row["id"],
        "username": row["username"],
        "role": row["role"],
        "display_name": row["display_name"] or row["username"],
        "must_change_pw": bool(row["must_change_pw"]),
    }


def change_password(user_id: int, old_pw: str, new_pw: str) -> None:
    if len(new_pw) < 6:
        raise HTTPException(status_code=400,
                            detail="password too short (min 6)")
    conn = _db()
    try:
        row = conn.execute(
            "SELECT password_hash FROM users WHERE id=?", (user_id,),
        ).fetchone()
        if not row or not verify_password(old_pw, row["password_hash"]):
            raise HTTPException(status_code=401,
                                detail="old password incorrect")
        new_hash = hash_password(new_pw)
        conn.execute(
            """UPDATE users SET password_hash=?,
                 must_change_pw=0,
                 updated_at=datetime('now','localtime')
               WHERE id=?""",
            (new_hash, user_id),
        )
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# FastAPI 依赖注入
# ---------------------------------------------------------------------------

def extract_token(request: Request) -> Optional[str]:
    """从 Authorization: Bearer <x> 或 cookie 'ks_token' 拿 token."""
    auth = request.headers.get("Authorization") or request.headers.get("authorization")
    if auth and auth.lower().startswith("bearer "):
        return auth[7:].strip()
    return request.cookies.get("ks_token")


def current_user(request: Request) -> dict:
    """FastAPI Depends: 解析当前请求的用户. 未认证 → 401."""
    token = extract_token(request)
    if not token:
        raise HTTPException(status_code=401, detail="not authenticated")
    payload = verify_token(token)
    return {
        "id": int(payload["sub"]),
        "username": payload["username"],
        "role": payload["role"],
        "jti": payload["jti"],
    }


def require_role(min_role: str):
    """装饰器工厂 — 当前用户至少是 min_role."""
    needed = _ROLE_RANK.get(min_role, 99)

    def dep(request: Request) -> dict:
        u = current_user(request)
        if _ROLE_RANK.get(u["role"], 0) < needed:
            raise HTTPException(
                status_code=403,
                detail=f"need role>={min_role}, you are {u['role']}",
            )
        return u

    return dep


def optional_user(request: Request) -> dict | None:
    """宽松模式: 有 token 就解析, 没就返回 None (供只读 GET 用)."""
    token = extract_token(request)
    if not token:
        return None
    try:
        payload = verify_token(token)
        return {
            "id": int(payload["sub"]),
            "username": payload["username"],
            "role": payload["role"],
            "jti": payload["jti"],
        }
    except HTTPException:
        return None


# ---------------------------------------------------------------------------
# 审计
# ---------------------------------------------------------------------------

def write_audit(actor: dict | None, *, action: str,
                target_type: str = "", target_id: str = "",
                before: Any = None, after: Any = None,
                note: str = "", ip: str = "") -> int | None:
    """落一条 audit_logs. 不抛异常."""
    import json as _json
    try:
        conn = _db()
        cur = conn.execute(
            """INSERT INTO audit_logs
                 (actor_id, actor_name, action, target_type, target_id,
                  before_json, after_json, note, ip)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                (actor or {}).get("id") if actor else None,
                (actor or {}).get("username") if actor else "system",
                action, target_type, str(target_id),
                _json.dumps(before, ensure_ascii=False, default=str)[:8000] if before else "",
                _json.dumps(after, ensure_ascii=False, default=str)[:8000] if after else "",
                note[:500], ip[:64],
            ),
        )
        row_id = cur.lastrowid
        conn.close()
        return row_id
    except Exception as e:
        log.warning("[auth.write_audit] failed: %s", e)
        return None
