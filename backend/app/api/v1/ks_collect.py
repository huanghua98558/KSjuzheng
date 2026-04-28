"""快手数据采集 API — 通过 ks 模块对外暴露能力.

端点:
  POST /api/client/ks/resolve            短链 → photoId + 作品详情
  GET  /api/client/ks/profile/{uid}      visionProfile
  GET  /api/client/ks/pool/stats         cookie 池状态
  POST /api/client/ks/pool/refresh       手动刷新 cookie 池
  POST /api/client/ks/search             关键词搜剧 (谨慎用,易触风控)
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.core.deps import get_current_user
from app.core.envelope import ok
from app.core.errors import (
    BizError,
    ErrorSpec,
    BUSINESS_INVALID_COOKIE,
    RATE_LIMIT_429,
    UPSTREAM_502,
    INTERNAL_500,
    VALIDATION_422,
)
from app.integrations.ks import (
    KSClient,
    cookie_pool,
)
from app.integrations.ks.errors import (
    KSCookieExpired,
    KSDataError,
    KSNetworkError,
    KSRateLimited,
    KSSchemaError,
)
from app.integrations.ks.mappers import map_photo_feed, map_profile, map_video_detail
from app.models import User


router = APIRouter()


# ============================================================
# 请求 / 响应 schemas
# ============================================================

class ResolveRequest(BaseModel):
    url: str = Field(..., min_length=8, max_length=2000, description="v.kuaishou.com/xxx 或完整作品 URL")
    fetch_detail: bool = Field(default=True, description="是否同时拉作品详情")


class SearchRequest(BaseModel):
    keyword: str = Field(..., min_length=1, max_length=80)
    pcursor: str = Field(default="", max_length=200)
    search_session_id: str = Field(default="", max_length=200)


# ============================================================
# 异常 → BizError 映射
# ============================================================

# KS 模块专用 ErrorSpec
_KS_COOKIE_EXPIRED = ErrorSpec("KS_COOKIE_EXPIRED", 503, "快手 Cookie 池暂无可用, 请稍后重试", "联系运营补充 Cookie")
_KS_RATE_LIMITED = ErrorSpec("KS_RATE_LIMITED", 429, "被快手风控限流, 请稍后重试", "降低请求频率")
_KS_NETWORK_ERROR = ErrorSpec("KS_NETWORK_ERROR", 502, "上游网络异常, 请稍后重试", None)
_KS_SCHEMA_ERROR = ErrorSpec("KS_SCHEMA_ERROR", 500, "GraphQL schema 不匹配", "联系开发同步快手 schema")
_KS_DATA_ERROR = ErrorSpec("KS_DATA_ERROR", 400, "快手返回业务错误", None)


def _to_biz(ex: Exception) -> BizError:
    if isinstance(ex, KSCookieExpired):
        return BizError(_KS_COOKIE_EXPIRED, message=str(ex) or _KS_COOKIE_EXPIRED.message)
    if isinstance(ex, KSRateLimited):
        return BizError(_KS_RATE_LIMITED, message=str(ex) or _KS_RATE_LIMITED.message)
    if isinstance(ex, KSNetworkError):
        return BizError(_KS_NETWORK_ERROR, message=f"{_KS_NETWORK_ERROR.message}: {ex}")
    if isinstance(ex, KSSchemaError):
        return BizError(_KS_SCHEMA_ERROR, message=f"{_KS_SCHEMA_ERROR.message}: {ex}")
    if isinstance(ex, KSDataError):
        return BizError(
            _KS_DATA_ERROR,
            message=f"快手返回业务错误: {ex}",
            hint=f"code={ex.code}" if ex.code is not None else None,
        )
    return BizError(INTERNAL_500, message=f"未知错误: {ex}")


# ============================================================
# 1. 短链解析 + 作品详情
# ============================================================

@router.post("/resolve", summary="快手短链解析 + 作品详情")
def post_resolve(
    body: ResolveRequest,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    try:
        with KSClient(db=db) as kc:
            # Step 1: 短链 → photoId
            r = kc.resolve_short_url(body.url)
            photo_id = r["photo_id"]
            author_uid = r.get("author_uid_short")
            data = {
                "photo_id": photo_id,
                "author_uid_short": author_uid,
                "raw_location": r.get("raw_location"),
            }
            # Step 2: 作品详情(可选)
            if body.fetch_detail and photo_id:
                try:
                    detail = kc.get_video_detail(photo_id)
                    data["video"] = map_video_detail(detail)
                except KSDataError as ex:
                    data["video"] = None
                    data["video_error"] = {"code": ex.code, "message": str(ex)}
        return ok(data)
    except Exception as ex:
        raise _to_biz(ex)


# ============================================================
# 2. 用户档案
# ============================================================

@router.get("/profile/{uid_short}", summary="快手用户档案")
def get_profile(
    uid_short: str,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    try:
        with KSClient(db=db) as kc:
            node = kc.get_profile(uid_short)
        return ok(map_profile(node))
    except Exception as ex:
        raise _to_biz(ex)


# ============================================================
# 3. 关键词搜剧
# ============================================================

@router.post("/search", summary="关键词搜剧(谨慎用,易触风控)")
def post_search(
    body: SearchRequest,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    try:
        with KSClient(db=db) as kc:
            res = kc.search_photo(
                body.keyword,
                pcursor=body.pcursor,
                search_session_id=body.search_session_id,
            )
        feeds_mapped = [map_photo_feed(f) for f in res["feeds"] if f.get("photo")]
        return ok({
            "feeds": feeds_mapped,
            "pcursor": res["pcursor"],
            "search_session_id": res["search_session_id"],
            "llsid": res["llsid"],
            "count": len(feeds_mapped),
        })
    except Exception as ex:
        raise _to_biz(ex)


# ============================================================
# 4. Cookie 池状态
# ============================================================

@router.get("/pool/stats", summary="快手 Cookie 池状态")
def get_pool_stats(
    user: User = Depends(get_current_user),
):
    return ok(cookie_pool.stats())


@router.post("/pool/refresh", summary="手动刷新 Cookie 池")
def post_pool_refresh(
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    n = cookie_pool.refresh(db)
    return ok({"pool_size": n, "stats": cookie_pool.stats()})
