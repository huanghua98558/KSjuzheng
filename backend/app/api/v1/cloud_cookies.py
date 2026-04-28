"""云端 Cookie API — 默认脱敏, 高敏 reveal 单独审计."""
from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Request
from sqlalchemy import text

from app.core.audit import audit_request
from app.core.deps import CurrentUser, DbSession
from app.models import User
from app.core.envelope import ok
from app.core.permissions import require_perm
from app.schemas.account import (
    CloudCookieBatchUpdateOwner,
    CloudCookieCreate,
    CloudCookiePublic,
    CloudCookieReveal,
    CloudCookieUpdate,
)
from app.schemas.common import IdListRequest, make_pagination
from app.services import cookie_service
from app.services import source_mysql_service


router = APIRouter()


def _trace(r: Request) -> str:
    return getattr(r.state, "trace_id", "-")


@router.get("")
async def list_cookies(
    request: Request,
    db: DbSession,
    user: User = Depends(require_perm("cloud-cookie:view")),
    page: int = 1,
    size: int = 50,
    keyword: str | None = None,
    owner_code: str | None = None,
    status: str | None = None,
):
    if source_mysql_service.is_source_mysql(db):
        where = []
        params = {}
        if keyword:
            where.append("(account_name LIKE :kw OR kuaishou_name LIKE :kw OR owner_code LIKE :kw OR device_serial LIKE :kw)")
            params["kw"] = f"%{keyword}%"
        if owner_code:
            where.append("owner_code = :owner_code")
            params["owner_code"] = owner_code
        if status:
            where.append("login_status = :status")
            params["status"] = status
        sql_where = " AND ".join(where) if where else "1=1"
        total = int(db.execute(text(f"SELECT COUNT(*) FROM cloud_cookie_accounts WHERE {sql_where}"), params).scalar_one())
        rows = db.execute(
            text(f"SELECT * FROM cloud_cookie_accounts WHERE {sql_where} ORDER BY id DESC LIMIT :limit OFFSET :offset"),
            {**params, "limit": size, "offset": max(page - 1, 0) * size},
        ).mappings().all()
        items = [
            {
                "id": row["id"],
                "organization_id": None,
                "assigned_user_id": None,
                "account_id": row["account_id"],
                "uid": row["kuaishou_uid"],
                "nickname": row["kuaishou_name"] or row["account_name"],
                "owner_code": row["owner_code"],
                "cookie_preview": (row["cookies"][:77] + "...") if row["cookies"] and len(row["cookies"]) > 80 else row["cookies"],
                "login_status": row["login_status"],
                "last_success_at": row["login_time"],
                "imported_by_user_id": None,
                "created_at": row["created_at"],
                "updated_at": row["updated_at"],
            }
            for row in rows
        ]
        return ok({"items": items, "pagination": make_pagination(total, page, size).model_dump()}, trace_id=_trace(request))
    items, total = cookie_service.list_cookies(
        db, user, page=page, size=size, keyword=keyword,
        owner_code=owner_code, status=status,
    )
    return ok(
        {
            "items": [CloudCookiePublic.model_validate(c).model_dump(mode="json") for c in items],
            "pagination": make_pagination(total, page, size).model_dump(),
        },
        trace_id=_trace(request),
    )


@router.post("")
async def post_cookie(
    data: CloudCookieCreate,
    request: Request,
    db: DbSession,
    user: User = Depends(require_perm("cloud-cookie:create")),
):
    c = cookie_service.create_cookie(db, user, data)
    audit_request(request, db, user=user, action="create", module="cloud-cookie",
                  target_type="cookie", target_id=c.id,
                  detail={"uid": c.uid, "owner_code": c.owner_code})
    db.commit()
    db.refresh(c)
    return ok(CloudCookiePublic.model_validate(c).model_dump(mode="json"),
              trace_id=_trace(request))


@router.put("/{cookie_id}")
async def put_cookie(
    cookie_id: int,
    data: CloudCookieUpdate,
    request: Request,
    db: DbSession,
    user: User = Depends(require_perm("cloud-cookie:edit")),
):
    c = cookie_service.update_cookie(db, user, cookie_id, data)
    audit_request(request, db, user=user, action="update", module="cloud-cookie",
                  target_type="cookie", target_id=cookie_id,
                  detail=data.model_dump(exclude_unset=True))
    db.commit()
    db.refresh(c)
    return ok(CloudCookiePublic.model_validate(c).model_dump(mode="json"),
              trace_id=_trace(request))


@router.delete("/{cookie_id}")
async def delete_cookie(
    cookie_id: int,
    request: Request,
    db: DbSession,
    user: User = Depends(require_perm("cloud-cookie:batch-delete")),
):
    cookie_service.delete_cookie(db, user, cookie_id)
    audit_request(request, db, user=user, action="delete", module="cloud-cookie",
                  target_type="cookie", target_id=cookie_id)
    db.commit()
    return ok({"deleted": True}, trace_id=_trace(request))


@router.post("/batch-update-owner")
async def post_batch_update_owner(
    data: CloudCookieBatchUpdateOwner,
    request: Request,
    db: DbSession,
    user: User = Depends(require_perm("cloud-cookie:batch-update-owner")),
):
    result = cookie_service.batch_update_owner(db, user, data.ids, data.owner_code)
    audit_request(request, db, user=user, action="batch_update_owner",
                  module="cloud-cookie",
                  detail={"count": len(data.ids), "owner_code": data.owner_code})
    db.commit()
    return ok(result, trace_id=_trace(request))


@router.post("/batch-delete")
async def post_batch_delete(
    data: IdListRequest,
    request: Request,
    db: DbSession,
    user: User = Depends(require_perm("cloud-cookie:batch-delete")),
):
    result = cookie_service.batch_delete(db, user, data.ids)
    audit_request(request, db, user=user, action="batch_delete", module="cloud-cookie",
                  detail={"count": len(data.ids)})
    db.commit()
    return ok(result, trace_id=_trace(request))


@router.get("/{cookie_id}/reveal")
async def get_cookie_reveal(
    cookie_id: int,
    request: Request,
    db: DbSession,
    user: User = Depends(require_perm("cloud-cookie:reveal-plaintext")),
):
    """★ 高敏: 返明文 Cookie. 单独审计."""
    plain = cookie_service.reveal_cookie_plaintext(db, user, cookie_id)
    # 必须先审计再返回 (确保可追溯, 即使后续传输失败 log 也已写)
    audit_request(
        request, db, user=user, action="reveal", module="cloud-cookie",
        target_type="cookie", target_id=cookie_id,
        detail={"length": len(plain)},
    )
    db.commit()
    return ok(
        CloudCookieReveal(
            cookie_plaintext=plain,
            revealed_at=datetime.now(timezone.utc),
        ).model_dump(mode="json"),
        trace_id=_trace(request),
    )
