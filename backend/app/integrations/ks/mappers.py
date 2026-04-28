"""快手 GraphQL JSON → 业务对象映射.

约定: 输入是 KSClient 各方法返回的 dict, 输出是字典或 ORM-friendly 形态.
"""
from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Any


# 清洗 caption 中的 # 标签和 @ 提及, 提取主标题
_HASH_RE = re.compile(r"#\S+")
_AT_RE = re.compile(r"@\S+")
_URL_RE = re.compile(r"https?://\S+")
_WS_RE = re.compile(r"\s+")


def clean_caption(caption: str) -> str:
    """从带 #标签 #提及 #链接 的 caption 抽出干净标题."""
    if not caption:
        return ""
    s = caption
    s = _HASH_RE.sub(" ", s)
    s = _AT_RE.sub(" ", s)
    s = _URL_RE.sub(" ", s)
    s = _WS_RE.sub(" ", s).strip()
    return s


def map_profile(node: dict) -> dict:
    """visionProfile.userProfile → 标准化字段."""
    profile = node.get("profile") or {}
    cnt = node.get("ownerCount") or {}
    return {
        "uid_short": profile.get("user_id"),
        "user_name": profile.get("user_name"),
        "head_url": profile.get("headurl"),
        "gender": profile.get("gender"),
        "user_text": profile.get("user_text") or "",
        "fan_count": _to_int(cnt.get("fan")),
        "follow_count": _to_int(cnt.get("follow")),
        "photo_count": _to_int(cnt.get("photo")),
        "photo_public_count": _to_int(cnt.get("photo_public")),
        "is_following": bool(node.get("isFollowing")),
    }


def map_photo_feed(feed: dict) -> dict:
    """search/photoList 的 feed 项 → 作品标准化字段."""
    a = feed.get("author") or {}
    p = feed.get("photo") or {}
    tags = [t.get("name") for t in (feed.get("tags") or []) if t.get("name")]

    raw_caption = p.get("caption") or ""
    return {
        "photo_id": p.get("id"),
        "author_uid_short": a.get("id"),
        "author_name": a.get("name"),
        "author_head_url": a.get("headerUrl"),
        "caption_raw": raw_caption,
        "caption_clean": clean_caption(raw_caption),
        "view_count": _to_int(p.get("viewCount")),
        "like_count": _to_int(p.get("likeCount")),
        "real_like_count": _to_int(p.get("realLikeCount")),
        "duration_ms": _to_int(p.get("duration")),
        "cover_url": p.get("coverUrl"),
        "photo_url": p.get("photoUrl"),
        "timestamp_ms": _to_int(p.get("timestamp")),
        "publish_at": _ts_to_iso(p.get("timestamp")),
        "tags": tags,
        "tags_text": " ".join(tags),
    }


def map_video_detail(node: dict) -> dict:
    """visionVideoDetail → 作品标准化字段 (含 status 和 type)."""
    out = map_photo_feed({"author": node.get("author"), "photo": node.get("photo"), "tags": node.get("tags")})
    out["status"] = _to_int(node.get("status"))
    out["type"] = node.get("type")
    out["llsid"] = node.get("llsid")
    return out


def _to_int(v: Any) -> int | None:
    if v is None:
        return None
    try:
        return int(v)
    except (ValueError, TypeError):
        return None


def _ts_to_iso(ms: Any) -> str | None:
    n = _to_int(ms)
    if not n:
        return None
    try:
        return datetime.fromtimestamp(n / 1000, tz=timezone.utc).isoformat()
    except Exception:
        return None
