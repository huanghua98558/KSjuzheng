"""ks_creator_service - 快手创作者中心代理服务

输入：cookie_id (cloud_cookie_accounts.id)
内部：cookie_service.reveal_cookie_plaintext → KuaishouClient → 调快手
输出：脱敏 + 标准化的业务数据

CLAUDE.md 红线：
  - 客户端 cookie 必须 AES-256 加密上传（cookie_service.create_cookie 已做）
  - 服务端只在内存里短暂解密 + 调用，不落明文
  - 错误统一翻译为中文友好（KuaishouClient.errors.user_facing_message）
"""
from __future__ import annotations

import logging

from sqlalchemy.orm import Session

from app.integrations.kuaishou import KuaishouClient
from app.integrations.kuaishou.errors import (
    KuaishouAPIError,
    KuaishouAuthError,
)
from app.models import User
from app.services import cookie_service


log = logging.getLogger(__name__)


def _build_client(db: Session, user: User, cookie_id: int) -> KuaishouClient:
    """从加密 cookie 构造一个 KuaishouClient。"""
    plain = cookie_service.reveal_cookie_plaintext(db, user, cookie_id)
    return KuaishouClient.from_cookie_string(plain)


def verify(db: Session, user: User, cookie_id: int) -> dict:
    """验证 cookie 是否还有效，并返回基础信息"""
    client = _build_client(db, user, cookie_id)
    result = client.verify_cookie()
    # 如果验证通过，回写 login_status='active'，否则 'expired'
    cookie = cookie_service.get_cookie(db, user, cookie_id)
    cookie.login_status = "active" if result["valid"] else "expired"
    db.flush()
    return result


def creator_info(db: Session, user: User, cookie_id: int) -> dict:
    """创作者中心基础信息（昵称/UID/粉丝/头像 + 主页统计）"""
    client = _build_client(db, user, cookie_id)
    try:
        user_info = client.cp_creator_user_info()
        info_v2 = client.cp_creator_info_v2()
        return {
            "user": user_info.get("data", {}).get("coreUserInfo"),
            "stats": info_v2.get("data"),
        }
    except KuaishouAuthError:
        cookie = cookie_service.get_cookie(db, user, cookie_id)
        cookie.login_status = "expired"
        db.flush()
        raise


def overview(db: Session, user: User, cookie_id: int, time_type: int = 1) -> dict:
    """数据总览（time_type 1=近 7 天 / 2=近 30 天）"""
    client = _build_client(db, user, cookie_id)
    r = client.cp_analysis_overview(time_type=time_type)
    bd = r.get("data", {}).get("basicData") or []
    metrics = []
    for m in bd:
        metrics.append({
            "name": m.get("name"),
            "tab": m.get("tab"),
            "sum": m.get("sumCount"),
            "today": m.get("endDayCount"),
            "interpret": m.get("interpretDesc"),
            "trend": m.get("trendData") or [],
        })
    return {"time_type": time_type, "metrics": metrics}


def photo_list(db: Session, user: User, cookie_id: int) -> dict:
    """已发布视频列表"""
    client = _build_client(db, user, cookie_id)
    r = client.cp_photo_list()
    items = (r.get("data") or {}).get("list") or []
    return {
        "total": len(items),
        "items": [
            {
                "work_id": it.get("workId"),
                "publish_id": it.get("publishId"),
                "title": it.get("title"),
                "cover": it.get("publishCoverUrl"),
                "publish_time": it.get("publishTime"),
                "play_count": it.get("playCount"),
                "like_count": it.get("likeCount"),
                "comment_count": it.get("commentCount"),
                "raw": it,
            }
            for it in items
        ],
    }


def analysis_photo_list(db: Session, user: User, cookie_id: int, page: int = 0, count: int = 15) -> dict:
    """作品分析数据"""
    client = _build_client(db, user, cookie_id)
    r = client.cp_analysis_photo_list(page=page, count=count)
    items = ((r.get("data") or {}).get("photoList") or {}).get("photoItems") or []
    return {"page": page, "count": count, "items": items}


def income(db: Session, user: User, cookie_id: int) -> dict:
    """快手账号余额/总收益"""
    client = _build_client(db, user, cookie_id)
    r = client.cp_income()
    d = r.get("data") or {}
    return {"income": d.get("income"), "balance": d.get("banance")}


def comment_list(db: Session, user: User, cookie_id: int) -> dict:
    """我作品的评论"""
    client = _build_client(db, user, cookie_id)
    r = client.cp_home_comment_list()
    items = (r.get("data") or {}).get("list") or []
    return {"total": len(items), "items": items}


def notif_unread(db: Session, user: User, cookie_id: int) -> dict:
    client = _build_client(db, user, cookie_id)
    r = client.cp_notif_unread()
    return {"unread": (r.get("data") or {}).get("unReadCount", 0)}


def jigou_account(db: Session, user: User, cookie_id: int) -> dict:
    """机构平台身份信息"""
    client = _build_client(db, user, cookie_id)
    r = client.jigou_account_current()
    d = r.get("data") or {}
    return {
        "user_info": d.get("userInfo"),
        "settled": d.get("settled"),
        "settle_guide": d.get("settleGuide"),
    }


def www_profile(db: Session, user: User, cookie_id: int, target_uid: str) -> dict:
    """通过 GraphQL 拉任意 uid 的公开资料"""
    client = _build_client(db, user, cookie_id)
    r = client.www_vision_profile(user_id=target_uid)
    vp = ((r.get("data") or {}).get("visionProfile") or {})
    return {"target_uid": target_uid, "profile": vp.get("userProfile"), "is_following": vp.get("isFollowing")}
