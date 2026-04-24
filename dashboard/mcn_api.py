# -*- coding: utf-8 -*-
"""MCN 通讯中心路由 — 挂在 /api/mcn/*."""
from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from core.auth import current_user, write_audit, _db
from core.config import DB_PATH

router = APIRouter()

# 与 core/mcn_client.py 的 TOKEN_FILE 保持一致 (相对 cwd "."), 同时兜底几个常见位置
_PROJECT_ROOT = Path(__file__).resolve().parent.parent
_TOKEN_FILE_CANDIDATES = [
    _PROJECT_ROOT / ".mcn_token.json",
    Path(".mcn_token.json"),
    Path.home() / ".mcn_token.json",
]


def _find_token_file() -> Optional[Path]:
    for p in _TOKEN_FILE_CANDIDATES:
        try:
            if p.exists():
                return p
        except Exception:
            continue
    return None


# ---------------------------------------------------------------------------

@router.get("/session")
def mcn_session(request: Request):
    """Captain MCN 登录态 + token 过期时间."""
    current_user(request)
    out = {
        "token_cached": False,
        "expires_at": None,
        "seconds_to_expire": None,
        "captain": None,
        "last_refresh": None,
        "token_file": None,
    }
    tf = _find_token_file()
    if tf:
        try:
            d = json.loads(tf.read_text(encoding="utf-8"))
            exp_str = d.get("expires_at", "")
            exp = datetime.fromisoformat(exp_str.replace("Z", "")) if exp_str else None
            out["token_cached"] = True
            out["expires_at"] = exp_str
            if exp:
                out["seconds_to_expire"] = int((exp - datetime.now()).total_seconds())
            out["captain"] = d.get("user", {})
            out["token_file"] = str(tf)
            out["last_refresh"] = datetime.fromtimestamp(
                tf.stat().st_mtime,
            ).isoformat(sep=" ", timespec="seconds")
        except Exception as e:
            out["error"] = str(e)
    return out


@router.post("/session/refresh")
def mcn_session_refresh(request: Request):
    """强制刷新 captain MCN token."""
    u = current_user(request)
    if u["role"] not in ("admin", "operator"):
        raise HTTPException(status_code=403, detail="admin/operator only")
    try:
        from core.mcn_client import MCNClient
        mc = MCNClient()
        token = mc.login(force=True)
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"MCN refresh failed: {e}")

    ip = request.client.host if request.client else ""
    write_audit(u, action="mcn.session_refresh",
                target_type="mcn", target_id="captain", ip=ip)
    try:
        from core.event_bus import emit_event
        emit_event("mcn.token_refresh", source_module="mcn_api",
                   payload={"token_prefix": token[:16]})
    except Exception:
        pass
    return {"ok": True, "token_prefix": token[:16]}


@router.get("/bindings")
def mcn_bindings(request: Request, limit: int = 200):
    current_user(request)
    conn = _db()
    try:
        rows = conn.execute(
            """SELECT kuaishou_uid, account_name, member_id, owner_code,
                      commission_rate, plan_type, bound_at, last_verified_at
               FROM mcn_account_bindings
               ORDER BY COALESCE(last_verified_at, bound_at) DESC LIMIT ?""",
            (limit,),
        ).fetchall()
    finally:
        conn.close()
    return {"bindings": [dict(r) for r in rows],
            "total": len(rows)}


@router.get("/invitations")
def mcn_invitations(request: Request, limit: int = 100, status: str = ""):
    current_user(request)
    conn = _db()
    try:
        sql = """SELECT * FROM mcn_invitations WHERE 1=1"""
        params: list = []
        if status:
            sql += " AND invitation_status=?"
            params.append(status)
        sql += " ORDER BY id DESC LIMIT ?"
        params.append(limit)
        rows = conn.execute(sql, params).fetchall()
    finally:
        conn.close()
    return {"invitations": [dict(r) for r in rows]}


@router.get("/income")
def mcn_income(request: Request, days: int = 30):
    """近 N 天收益快照 (按 snapshot_date 分组聚合)."""
    current_user(request)
    conn = _db()
    try:
        rows = conn.execute(
            """SELECT snapshot_date,
                      SUM(COALESCE(commission_amount, 0)) AS today,
                      SUM(COALESCE(total_amount, 0))      AS total,
                      COUNT(*)                            AS accounts,
                      AVG(COALESCE(commission_rate, 0))   AS avg_rate
               FROM mcn_income_snapshots
               WHERE snapshot_date >= date('now', ?)
               GROUP BY snapshot_date
               ORDER BY snapshot_date DESC""",
            (f"-{int(days)} days",),
        ).fetchall()
    finally:
        conn.close()
    return {"income": [dict(r) for r in rows]}


class InviteBody(BaseModel):
    user_id: str
    phone_number: str
    note: str = ""
    contract_month: int = 36


@router.post("/invite")
def mcn_invite(body: InviteBody, request: Request):
    """发起 MCN 直邀. 走 MCNClient.direct_invite → 自动写 system_events."""
    u = current_user(request)
    if u["role"] not in ("admin", "operator"):
        raise HTTPException(status_code=403, detail="admin/operator only")

    from core.mcn_client import MCNClient
    try:
        r = MCNClient().direct_invite(
            body.user_id, body.phone_number, body.note or "dashboard",
            body.contract_month,
        )
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"MCN invite failed: {e}")

    ip = request.client.host if request.client else ""
    write_audit(u, action="mcn.invite",
                target_type="mcn_user", target_id=body.user_id,
                after={"phone_3": body.phone_number[:3] + "***",
                       "contract_month": body.contract_month},
                ip=ip)
    return {"ok": bool(r.get("success")), "response": r}


# ★ 2026-04-20: 账号 MCN 状态查询 + 一键邀请 (用户要求)
@router.get("/check/{account_id}")
def mcn_check_account(account_id: int):
    """查单账号 MCN 真实绑定状态 (for 账号详情页 按钮分支).

    Returns:
        status: 'real_bound' (有收益) | 'listed' (在册无收益) | 'not_bound' (未绑)
        + 详细快照 + 邀请历史
    """
    from core.db_manager import DBManager
    db = DBManager()
    try:
        r = db.conn.execute(
            "SELECT id, account_name, kuaishou_uid, numeric_uid FROM device_accounts WHERE id=?",
            (account_id,)
        ).fetchone()
        if not r:
            raise HTTPException(404, "账号不存在")
        account_name = r[1]
        ksuid = r[2]
        numeric_uid = r[3]

        # 1. 最新收益快照
        snap = db.conn.execute(
            """SELECT total_amount, org_task_num, snapshot_date
               FROM mcn_member_snapshots
               WHERE member_id=? ORDER BY snapshot_date DESC LIMIT 1""",
            (numeric_uid,) if numeric_uid else (None,)
        ).fetchone() if numeric_uid else None

        total = float(snap[0] or 0) if snap else 0
        tasks = int(snap[1] or 0) if snap else 0
        last_date = snap[2] if snap else None

        # 2. 邀请记录 (from mcn_invitations 本地表)
        invitations = []
        try:
            rs = db.conn.execute(
                """SELECT invited_at, signed_status, invite_response_json
                   FROM mcn_invitations WHERE kuaishou_uid=?
                   ORDER BY invited_at DESC LIMIT 5""",
                (ksuid,)
            ).fetchall()
            for row in rs:
                resp_j = {}
                try:
                    import json as _j
                    resp_j = _j.loads(row[2] or "{}")
                except Exception:
                    pass
                invitations.append({
                    "invited_at": row[0],
                    "signed_status": row[1],
                    "response_success": resp_j.get("success"),
                })
        except Exception:
            pass

        # 3. 绑定记录
        bind = db.conn.execute(
            """SELECT member_id, plan_type, bound_at, last_verified_at, commission_rate
               FROM mcn_account_bindings WHERE kuaishou_uid=? LIMIT 1""",
            (ksuid,)
        ).fetchone() if ksuid else None

        # 4. 判定状态 (★ 2026-04-20 用户要求: 只分 已绑/未绑 2 态)
        # 已绑 = MCN 里能查到 member_id (无论有无收益, 说明签约完成)
        # 未绑 = MCN 查不到此账号
        if snap or bind:
            status = "bound"
            status_zh = "🟢 已绑"
            if total > 0:
                status_zh = f"🟢 已绑 (¥{total:.2f})"
        else:
            status = "not_bound"
            status_zh = "🔴 未绑"

        return {
            "account_id": account_id,
            "account_name": account_name,
            "kuaishou_uid": ksuid,
            "numeric_uid": numeric_uid,
            "status": status,
            "status_zh": status_zh,
            "total_amount": total,
            "tasks": tasks,
            "last_snapshot_date": last_date,
            "binding": {
                "member_id": bind[0] if bind else None,
                "plan_type": bind[1] if bind else None,
                "bound_at": bind[2] if bind else None,
                "last_verified_at": bind[3] if bind else None,
                "commission_rate": bind[4] if bind else None,
            } if bind else None,
            "invitations": invitations,
            "actions_available": {
                "invite": status == "not_bound",     # 未绑才可邀请
                "query": True,                         # 永远可查
                "resync": status != "not_bound",       # 已在册才可重新同步
            },
        }
    finally:
        db.close()


class InviteByAccountBody(BaseModel):
    """MCN 直邀 — 必须提供账号真实主人 phone + real_name.

    首次邀请要填, 填过的 device_accounts.owner_phone 会保存, 下次自动读.
    """
    phone_number: str | None = None       # 11 位手机 (必填, 除非 device_accounts 已存)
    real_name: str | None = None          # 实名 (必填, 除非 device_accounts 已存)
    note: str = ""                         # 邀请备注
    contract_month: int = 36
    save_to_account: bool = True           # 默认把 phone/name 存回 device_accounts


@router.post("/invite/{account_id}")
def mcn_invite_by_account(account_id: int, body: InviteByAccountBody,
                            request: Request):
    """从 account_id 直邀. 需要 phone + real_name (首次填, 之后自动).

    ★ 2026-04-20 用户纠正: direct_invite 的 phone_number 必须是
    账号真实主人手机, 不是 captain 手机. 没填过的账号直接报错.
    """
    u = current_user(request)
    if u["role"] not in ("admin", "operator"):
        raise HTTPException(403, "admin/operator only")

    from core.db_manager import DBManager
    from core.mcn_client import MCNClient
    import re
    db = DBManager()
    try:
        r = db.conn.execute(
            "SELECT kuaishou_uid, account_name, owner_phone, owner_real_name "
            "FROM device_accounts WHERE id=?",
            (account_id,)
        ).fetchone()
        if not r:
            raise HTTPException(404, "账号不存在")
        ksuid, aname, stored_phone, stored_name = r

        # 优先用 body, fallback 读 device_accounts 存过的
        phone = (body.phone_number or stored_phone or "").strip()
        real_name = (body.real_name or stored_name or "").strip()

        if not phone or not re.match(r"^1[3-9]\d{9}$", phone):
            raise HTTPException(400,
                f"缺失或格式错误的 phone_number (必须 11 位手机). "
                f"账号={aname} 未登记主人手机, 请填表后再邀")
        if not real_name:
            raise HTTPException(400,
                f"缺失 real_name (真实姓名). 账号={aname} 未登记主人姓名")
        if not ksuid:
            raise HTTPException(400, "账号无 kuaishou_uid, 不能邀请")

        # 调 MCN
        try:
            resp = MCNClient().direct_invite(
                str(ksuid), phone,
                body.note or f"dashboard@{aname} ({real_name})",
                body.contract_month
            )
        except Exception as e:
            raise HTTPException(502, f"MCN invite failed: {e}")

        # 邀请成功 or 失败都记录; 成功且开启 save → 写回 device_accounts
        success = bool(resp.get("success"))
        try:
            from datetime import datetime as _dt
            now_iso = _dt.now().strftime("%Y-%m-%d %H:%M:%S")
            if body.save_to_account and success:
                db.conn.execute(
                    """UPDATE device_accounts SET
                         owner_phone = ?, owner_real_name = ?,
                         owner_filled_at = ?,
                         mcn_last_invite_at = ?,
                         mcn_last_invite_status = ?
                       WHERE id = ?""",
                    (phone, real_name, now_iso, now_iso,
                     'success' if success else 'failed', account_id)
                )
            else:
                db.conn.execute(
                    """UPDATE device_accounts SET
                         mcn_last_invite_at = ?,
                         mcn_last_invite_status = ?
                       WHERE id = ?""",
                    (now_iso, 'success' if success else 'failed', account_id)
                )
            db.conn.commit()
        except Exception as e:
            pass

        ip = request.client.host if request.client else ""
        write_audit(u, action="mcn.invite_account",
                    target_type="account", target_id=str(account_id),
                    after={"ksuid": ksuid, "account_name": aname,
                           "real_name_3": real_name[:1] + "**",
                           "phone_3": phone[:3] + "****",
                           "success": success},
                    ip=ip)
        return {"ok": success, "account_id": account_id,
                "account_name": aname, "response": resp,
                "saved_to_account": body.save_to_account and success}
    finally:
        db.close()


@router.post("/sync")
def mcn_sync(request: Request):
    """手动触发一次全量同步: bindings + members + income snapshot."""
    u = current_user(request)
    if u["role"] not in ("admin", "operator"):
        raise HTTPException(status_code=403, detail="admin/operator only")

    from core.db_manager import DBManager
    from core.mcn_client import MCNClient
    from core.mcn_business import MCNBusiness
    db = DBManager()
    try:
        biz = MCNBusiness(db, MCNClient())
        synced = biz.sync_account_bindings()
        try:
            updated = biz.sync_members()
        except Exception as e:
            updated = f"error: {e}"
        try:
            income = biz.snapshot_daily_income()
        except Exception as e:
            income = f"error: {e}"
    finally:
        db.close()

    ip = request.client.host if request.client else ""
    write_audit(u, action="mcn.sync",
                target_type="mcn", target_id="batch",
                after={"synced": synced, "updated": updated, "income": income},
                ip=ip)
    try:
        from core.event_bus import emit_event
        emit_event("mcn.full_sync", source_module="mcn_api",
                   payload={"synced": synced, "updated": updated,
                            "income_snapshots": income})
    except Exception:
        pass
    return {"ok": True, "synced": synced, "updated": updated, "income": income}


@router.get("/events")
def mcn_events(request: Request, limit: int = 50):
    """近 N 条 MCN 相关的 system_events."""
    current_user(request)
    conn = _db()
    try:
        rows = conn.execute(
            """SELECT id, event_type, event_level, entity_id,
                      payload, created_at
               FROM system_events
               WHERE event_type LIKE 'mcn.%'
               ORDER BY id DESC LIMIT ?""",
            (limit,),
        ).fetchall()
    finally:
        conn.close()
    out = []
    for r in rows:
        try:
            payload = json.loads(r["payload"] or "{}")
        except Exception:
            payload = {}
        out.append({**dict(r), "payload": payload})
    return {"events": out}
