# -*- coding: utf-8 -*-
"""认证路由 — MCN-as-IdP 模式.

登录来源: http://mcn.zhongxiangbao.com/api/auth/login
- Captain (黄老板): REPLACE_WITH_YOUR_PHONE / REPLACE_WITH_YOUR_PASSWORD  → 我们发 role=admin 的 JWT
- 子账号 (团队成员): 如 18474358043 / xxxxxx → 我们发 role=operator 的 JWT
- 未知角色: 默认 viewer (只读)

本地 users 表是 MCN 用户的影子表:
- 首次 MCN 登录成功 → 自动 upsert 一条
- password_hash 恒为 '' (密码不存本地, 下次登录照样走 MCN)
- role 根据 MCN.role 映射
- 保留 users 表目的: 让 audit_logs.actor_id 指向有效行 + 本地权限缓存

本地 admin/bcrypt 兜底: 仅在 env KS_ALLOW_LOCAL_LOGIN=1 时启用, 应急用.
"""
from __future__ import annotations

import os

from fastapi import APIRouter, HTTPException, Request, Response
from pydantic import BaseModel

from core.auth import (
    issue_token, current_user, change_password, revoke_token,
    write_audit, _db,
)
from core.mcn_client import MCNClient

router = APIRouter()


# ---------------------------------------------------------------------------

class LoginBody(BaseModel):
    username: str            # MCN 手机号 (也支持 user_id)
    password: str


class ChangePwBody(BaseModel):
    old_password: str
    new_password: str


# ---------------------------------------------------------------------------
# 角色映射: MCN role → 我们的 role
# ---------------------------------------------------------------------------

def _map_mcn_role(mcn_role: str) -> str:
    role = (mcn_role or "").lower().strip()
    # MCN 里的 captain / 队长 / owner → admin
    if role in ("captain", "队长", "owner", "admin", "super"):
        return "admin"
    # operator / 子账号 / team / member → operator
    if role in ("operator", "member", "sub", "子账号", "team",
                "sub_account", "subcaptain"):
        return "operator"
    # 只读 / viewer
    if role in ("viewer", "readonly", "read_only", "观察员"):
        return "viewer"
    # 未知默认 operator (能入队发布, 不能改全局开关)
    return "operator"


# ---------------------------------------------------------------------------
# 本地 users 表 upsert (MCN 影子)
# ---------------------------------------------------------------------------

def _upsert_mcn_user(mcn_user: dict, our_role: str) -> int:
    """MCN 登录成功后, 同步到本地 users 表. 返回本地 user_id."""
    conn = _db()
    try:
        username = str(mcn_user.get("username")
                       or mcn_user.get("phone")
                       or mcn_user.get("id"))
        nickname = mcn_user.get("nickname") or username
        mcn_id = str(mcn_user.get("id", ""))
        # email 字段借用存 MCN user_id, 方便反查
        row = conn.execute(
            "SELECT id, role FROM users WHERE username=?", (username,),
        ).fetchone()
        if row:
            # 同步 role + display_name (以 MCN 为准)
            conn.execute(
                """UPDATE users SET role=?, display_name=?,
                     email=?, is_active=1,
                     updated_at=datetime('now','localtime')
                   WHERE id=?""",
                (our_role, nickname, f"mcn:{mcn_id}", row["id"]),
            )
            return row["id"]
        # 新建 (password_hash 空字符串, 下次登录仍走 MCN)
        cur = conn.execute(
            """INSERT INTO users
                 (username, password_hash, role, display_name, email,
                  is_active, must_change_pw)
               VALUES (?, '', ?, ?, ?, 1, 0)""",
            (username, our_role, nickname, f"mcn:{mcn_id}"),
        )
        return cur.lastrowid
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# /login
# ---------------------------------------------------------------------------

@router.post("/login")
def login(body: LoginBody, request: Request, response: Response):
    ip = request.client.host if request.client else ""
    ua = request.headers.get("user-agent", "")

    # --- 1. 先走 MCN 校验 ---
    try:
        mcn_user = MCNClient.verify_credentials(body.username, body.password)
    except Exception as mcn_err:
        # 兜底: 允许 KS_ALLOW_LOCAL_LOGIN=1 时尝试本地 bcrypt
        if os.environ.get("KS_ALLOW_LOCAL_LOGIN", "0") == "1":
            try:
                from core.auth import authenticate as _local_auth
                token, user = _local_auth(body.username, body.password,
                                          ip=ip, ua=ua)
                response.set_cookie(
                    "ks_token", token, max_age=24 * 3600,
                    httponly=True, samesite="strict",
                )
                write_audit(
                    {"id": user["id"], "username": user["username"]},
                    action="user.login_local_fallback",
                    target_type="user", target_id=str(user["id"]),
                    note=f"MCN failed: {mcn_err}", ip=ip,
                )
                return {"ok": True, "token": token, "user": user,
                        "source": "local_fallback"}
            except HTTPException:
                pass
        raise HTTPException(status_code=401,
                            detail=f"MCN 登录失败: {mcn_err}")

    # --- 2. MCN OK → 映射 role + upsert 影子行 ---
    our_role = _map_mcn_role(mcn_user.get("role", ""))
    local_user_id = _upsert_mcn_user(mcn_user, our_role)

    username = str(mcn_user.get("username")
                   or mcn_user.get("phone")
                   or mcn_user.get("id"))
    nickname = mcn_user.get("nickname") or username

    # --- 3. 发我们自己的 JWT ---
    token, jti = issue_token(local_user_id, username, our_role,
                             ip=ip, user_agent=ua)
    response.set_cookie(
        "ks_token", token, max_age=24 * 3600,
        httponly=True, samesite="strict",
    )

    # 更新本地 users.last_login_at
    conn = _db()
    try:
        conn.execute(
            """UPDATE users SET last_login_at=datetime('now','localtime'),
                 last_login_ip=?
               WHERE id=?""",
            (ip[:64], local_user_id),
        )
    finally:
        conn.close()

    # 审计
    write_audit(
        {"id": local_user_id, "username": username},
        action="user.login_mcn",
        target_type="user", target_id=str(local_user_id),
        note=(f"mcn_role={mcn_user.get('role','')} "
              f"nickname={nickname} "
              f"commission={mcn_user.get('commission_rate','?')}%"),
        ip=ip,
    )

    return {
        "ok": True,
        "token": token,
        "user": {
            "id": local_user_id,
            "username": username,
            "role": our_role,
            "display_name": nickname,
            "mcn_role": mcn_user.get("role", ""),
            "mcn_id": mcn_user.get("id"),
            "commission_rate": mcn_user.get("commission_rate"),
            "must_change_pw": False,    # MCN 登录走 MCN 改密, 不管本地
        },
        "source": "mcn",
    }


# ---------------------------------------------------------------------------
# 其余路由保持一致
# ---------------------------------------------------------------------------

@router.post("/logout")
def logout(request: Request, response: Response):
    u = current_user(request)
    revoke_token(u["jti"])
    response.delete_cookie("ks_token")
    ip = request.client.host if request.client else ""
    write_audit(u, action="user.logout",
                target_type="user", target_id=str(u["id"]),
                ip=ip)
    return {"ok": True}


@router.get("/me")
def me(request: Request):
    u = current_user(request)
    # 带上本地 users 表里的 display_name / email
    conn = _db()
    try:
        row = conn.execute(
            """SELECT username, role, display_name, email, last_login_at
               FROM users WHERE id=?""",
            (u["id"],),
        ).fetchone()
    finally:
        conn.close()
    if row:
        u.update({
            "display_name": row["display_name"],
            "mcn_id": (row["email"] or "").replace("mcn:", "") or None,
            "last_login_at": row["last_login_at"],
        })
    return {"user": u}


@router.post("/change-password")
def change_my_password(body: ChangePwBody, request: Request):
    """MCN 登录用户的密码在 MCN 后台改, 我们不存本地密码. 本接口仅对
    KS_ALLOW_LOCAL_LOGIN 模式下的本地 admin 账号有效."""
    u = current_user(request)
    conn = _db()
    try:
        row = conn.execute(
            "SELECT password_hash FROM users WHERE id=?", (u["id"],),
        ).fetchone()
    finally:
        conn.close()
    if not row or not row["password_hash"]:
        raise HTTPException(
            status_code=400,
            detail="此账号通过 MCN 后台登录, 请到 mcn.zhongxiangbao.com 改密码",
        )
    change_password(u["id"], body.old_password, body.new_password)
    ip = request.client.host if request.client else ""
    write_audit(u, action="user.change_password_local",
                target_type="user", target_id=str(u["id"]),
                ip=ip)
    return {"ok": True}


@router.get("/audit-logs")
def audit_logs(request: Request, limit: int = 50,
               actor: str = "", action: str = "",
               target_type: str = ""):
    u = current_user(request)
    if u["role"] != "admin":
        raise HTTPException(status_code=403, detail="admin only")

    conn = _db()
    try:
        sql = """SELECT id, actor_id, actor_name, action, target_type,
                        target_id, note, ip, created_at
                 FROM audit_logs WHERE 1=1"""
        params: list = []
        if actor:
            sql += " AND actor_name=?"
            params.append(actor)
        if action:
            sql += " AND action LIKE ?"
            params.append(f"%{action}%")
        if target_type:
            sql += " AND target_type=?"
            params.append(target_type)
        sql += " ORDER BY id DESC LIMIT ?"
        params.append(limit)
        rows = conn.execute(sql, params).fetchall()
    finally:
        conn.close()

    return {"logs": [dict(r) for r in rows]}


@router.get("/users")
def list_users(request: Request):
    """列所有曾登录过的 MCN 用户 + 角色. 仅 admin 可见."""
    u = current_user(request)
    if u["role"] != "admin":
        raise HTTPException(status_code=403, detail="admin only")

    conn = _db()
    try:
        rows = conn.execute(
            """SELECT id, username, role, display_name, email, is_active,
                      last_login_at, last_login_ip, created_at
               FROM users ORDER BY id"""
        ).fetchall()
    finally:
        conn.close()

    out = []
    for r in rows:
        d = dict(r)
        d["mcn_id"] = (d.get("email") or "").replace("mcn:", "") or None
        out.append(d)
    return {"users": out}
