"""快手创作者中心代理 API - /api/client/ks-creator/*

通过加密 cookie 调用快手 cp.kuaishou.com / jigou.kuaishou.com / www.kuaishou.com
"""
from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException, Request

from app.core.deps import CurrentUser, DbSession
from app.core.envelope import ok
from app.integrations.kuaishou.errors import KuaishouAPIError
from app.services import ks_creator_service


log = logging.getLogger(__name__)
router = APIRouter()


def _trace(r: Request) -> str:
    return getattr(r.state, "trace_id", "-")


def _safe_call(fn, *args, **kwargs):
    """统一把 KuaishouAPIError 翻成 HTTP 友好提示."""
    try:
        return fn(*args, **kwargs)
    except KuaishouAPIError as e:
        log.warning(f"[ks_creator] {fn.__name__} -> {e.user_facing_message} (rc={e.result_code} http={e.http_status})")
        # cookie 失效 → 401；权限不足 → 403；其他 → 502
        if e.result_code == 109:
            raise HTTPException(status_code=401, detail=e.user_facing_message)
        if e.result_code == 530 or e.result_code == 560:
            raise HTTPException(status_code=403, detail=e.user_facing_message)
        if e.result_code == 500002 or e.http_status == 429:
            raise HTTPException(status_code=429, detail=e.user_facing_message)
        raise HTTPException(status_code=502, detail=e.user_facing_message)


@router.get("/{cookie_id}/verify")
async def verify(cookie_id: int, request: Request, db: DbSession, user: CurrentUser):
    """验证 cookie 有效性 + 自动更新 login_status。"""
    data = _safe_call(ks_creator_service.verify, db, user, cookie_id)
    return ok(data, trace_id=_trace(request))


@router.get("/{cookie_id}/info")
async def info(cookie_id: int, request: Request, db: DbSession, user: CurrentUser):
    """快手账号基础信息 + 主页统计 (一次返回 user + stats)"""
    data = _safe_call(ks_creator_service.creator_info, db, user, cookie_id)
    return ok(data, trace_id=_trace(request))


@router.get("/{cookie_id}/overview")
async def overview(
    cookie_id: int,
    request: Request,
    db: DbSession,
    user: CurrentUser,
    time_type: int = 1,
):
    """数据总览（播放量/点赞/粉丝/完播率/评论/分享）"""
    data = _safe_call(ks_creator_service.overview, db, user, cookie_id, time_type=time_type)
    return ok(data, trace_id=_trace(request))


@router.get("/{cookie_id}/photos")
async def photos(cookie_id: int, request: Request, db: DbSession, user: CurrentUser):
    """已发布视频列表"""
    data = _safe_call(ks_creator_service.photo_list, db, user, cookie_id)
    return ok(data, trace_id=_trace(request))


@router.get("/{cookie_id}/analysis/photos")
async def analysis_photos(
    cookie_id: int,
    request: Request,
    db: DbSession,
    user: CurrentUser,
    page: int = 0,
    count: int = 15,
):
    """作品分析数据（每条作品的播放/点赞/留存）"""
    data = _safe_call(ks_creator_service.analysis_photo_list, db, user, cookie_id, page=page, count=count)
    return ok(data, trace_id=_trace(request))


@router.get("/{cookie_id}/income")
async def income(cookie_id: int, request: Request, db: DbSession, user: CurrentUser):
    """账号余额/总收益"""
    data = _safe_call(ks_creator_service.income, db, user, cookie_id)
    return ok(data, trace_id=_trace(request))


@router.get("/{cookie_id}/comments")
async def comments(cookie_id: int, request: Request, db: DbSession, user: CurrentUser):
    """我作品下的评论列表"""
    data = _safe_call(ks_creator_service.comment_list, db, user, cookie_id)
    return ok(data, trace_id=_trace(request))


@router.get("/{cookie_id}/notif/unread")
async def notif_unread(cookie_id: int, request: Request, db: DbSession, user: CurrentUser):
    """未读消息数"""
    data = _safe_call(ks_creator_service.notif_unread, db, user, cookie_id)
    return ok(data, trace_id=_trace(request))


@router.get("/{cookie_id}/jigou/account")
async def jigou_account(cookie_id: int, request: Request, db: DbSession, user: CurrentUser):
    """jigou.kuaishou.com 平台身份信息"""
    data = _safe_call(ks_creator_service.jigou_account, db, user, cookie_id)
    return ok(data, trace_id=_trace(request))


@router.get("/{cookie_id}/www/profile/{target_uid}")
async def www_profile(
    cookie_id: int,
    target_uid: str,
    request: Request,
    db: DbSession,
    user: CurrentUser,
):
    """通过 www.kuaishou.com GraphQL 拉任意 uid 的公开资料"""
    data = _safe_call(ks_creator_service.www_profile, db, user, cookie_id, target_uid=target_uid)
    return ok(data, trace_id=_trace(request))
