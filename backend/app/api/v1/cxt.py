"""Chengxing/CXT APIs."""
from __future__ import annotations

from fastapi import APIRouter, Depends, Request
from sqlalchemy import text

from app.core.audit import audit_request
from app.core.deps import DbSession
from app.core.envelope import ok
from app.core.permissions import require_perm
from app.models import User
from app.schemas.common import make_pagination
from app.schemas.cxt import (
    CxtUserImportRequest,
    CxtUserPublic,
    CxtVideoImportRequest,
    CxtVideoPublic,
)
from app.services import cxt_service
from app.services import source_mysql_service


router = APIRouter()


def _trace(r: Request) -> str:
    return getattr(r.state, "trace_id", "-")


@router.get("/users")
async def list_cxt_users(
    request: Request,
    db: DbSession,
    user: User = Depends(require_perm("cxt-user:view")),
    page: int = 1,
    size: int = 50,
    keyword: str | None = None,
    status: str | None = None,
):
    items, total = cxt_service.list_users(
        db, user, page=page, size=size, keyword=keyword, status=status
    )
    return ok(
        {
            "items": [CxtUserPublic.model_validate(x).model_dump(mode="json") for x in items],
            "pagination": make_pagination(total, page, size).model_dump(),
        },
        trace_id=_trace(request),
    )


@router.post("/users/import")
async def import_cxt_users(
    data: CxtUserImportRequest,
    request: Request,
    db: DbSession,
    user: User = Depends(require_perm("cxt-user:import")),
):
    result = cxt_service.import_users(db, user, data)
    audit_request(
        request,
        db,
        user=user,
        action="import",
        module="cxt-user",
        detail={"requested": len(data.items), **result},
    )
    db.commit()
    return ok(result, trace_id=_trace(request))


@router.get("/videos")
async def list_cxt_videos(
    request: Request,
    db: DbSession,
    user: User = Depends(require_perm("cxt-video:view")),
    page: int = 1,
    size: int = 50,
    keyword: str | None = None,
    platform: str | None = None,
):
    if source_mysql_service.is_source_mysql(db):
        where = []
        params = {}
        if keyword:
            where.append("(title LIKE :kw OR author LIKE :kw OR aweme_id LIKE :kw)")
            params["kw"] = f"%{keyword}%"
        if platform:
            where.append("platform = :platform")
            params["platform"] = platform
        sql_where = " AND ".join(where) if where else "1=1"
        total = int(db.execute(text(f"SELECT COUNT(*) FROM cxt_videos WHERE {sql_where}"), params).scalar_one())
        rows = db.execute(
            text(f"SELECT * FROM cxt_videos WHERE {sql_where} ORDER BY id DESC LIMIT :limit OFFSET :offset"),
            {**params, "limit": size, "offset": max(page - 1, 0) * size},
        ).mappings().all()
        items = [
            {
                "id": row["id"],
                "organization_id": None,
                "cxt_user_id": None,
                "title": row["title"],
                "author": row["author"],
                "sec_user_id": row["sec_user_id"],
                "aweme_id": row["aweme_id"],
                "description": row["description"],
                "video_url": row["video_url"],
                "cover_url": row["cover_url"],
                "duration": row["duration"],
                "comment_count": row["comment_count"] or 0,
                "collect_count": row["collect_count"] or 0,
                "recommend_count": row["recommend_count"] or 0,
                "share_count": row["share_count"] or 0,
                "play_count": row["play_count"] or 0,
                "digg_count": row["digg_count"] or 0,
                "platform": row["platform"],
                "status": "active",
                "created_at": row["created_at"],
                "updated_at": row["created_at"],
            }
            for row in rows
        ]
        return ok({"items": items, "pagination": make_pagination(total, page, size).model_dump()}, trace_id=_trace(request))
    items, total = cxt_service.list_videos(
        db, user, page=page, size=size, keyword=keyword, platform=platform
    )
    return ok(
        {
            "items": [CxtVideoPublic.model_validate(x).model_dump(mode="json") for x in items],
            "pagination": make_pagination(total, page, size).model_dump(),
        },
        trace_id=_trace(request),
    )


@router.post("/videos/batch-import")
async def import_cxt_videos(
    data: CxtVideoImportRequest,
    request: Request,
    db: DbSession,
    user: User = Depends(require_perm("cxt-video:batch-import")),
):
    result = cxt_service.import_videos(db, user, data)
    audit_request(
        request,
        db,
        user=user,
        action="batch_import",
        module="cxt-video",
        detail={"requested": len(data.items), **result},
    )
    db.commit()
    return ok(result, trace_id=_trace(request))


@router.get("/videos/{video_id}")
async def get_cxt_video(
    video_id: int,
    request: Request,
    db: DbSession,
    user: User = Depends(require_perm("cxt-video:view")),
):
    item = cxt_service.get_video(db, user, video_id)
    return ok(CxtVideoPublic.model_validate(item).model_dump(mode="json"), trace_id=_trace(request))
