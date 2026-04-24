# -*- coding: utf-8 -*-
"""抖音 URL 解析 — 对齐 KS184 `parse_douyin_link @ 0x21c0e460b40`.

三层策略 (按成本从低到高):
  1. 本地 mirror_cxt_videos 查 aweme_id → 拿 metadata + video_url
  2. share page 抓取 (无需 sign, 短 TTL, 只对部分 URL 有效)
  3. local douyin_sign 服务 (KS184 原方案, 未实现)

返回统一 dict (见 core.parsers.__init__._ok)
"""
from __future__ import annotations
import logging
import re
import sqlite3
from typing import Any

log = logging.getLogger(__name__)


# ────────────────────────────────────────────────────────────────
# URL → aweme_id 提取
# ────────────────────────────────────────────────────────────────

_AWEME_PATTERNS = [
    re.compile(r"douyin\.com/video/(\d+)"),
    re.compile(r"douyin\.com/share/video/(\d+)"),
    re.compile(r"(?:video_id|aweme_id|id)=([a-z0-9]+)", re.I),   # play URL 里的 video_id (含字母)
    re.compile(r"/note/(\d+)"),
    re.compile(r"(\d{15,20})"),   # 裸 aweme_id 最宽松回退 (15-20 位纯数字)
]

_SHORT_URL_PATTERNS = [
    re.compile(r"v\.douyin\.com/([A-Za-z0-9_\-]+)"),
    re.compile(r"iesdouyin\.com/share/video/([A-Za-z0-9_\-]+)"),
]


def extract_aweme_id(url: str) -> str | None:
    """从 Douyin URL 里抠 aweme_id. 短链自动不展开 (需网络)."""
    if not url:
        return None
    for pat in _AWEME_PATTERNS:
        m = pat.search(url)
        if m:
            return m.group(1)
    return None


def extract_short_token(url: str) -> str | None:
    for pat in _SHORT_URL_PATTERNS:
        m = pat.search(url)
        if m:
            return m.group(1)
    return None


# ────────────────────────────────────────────────────────────────
# 本地 mirror 查询
# ────────────────────────────────────────────────────────────────

def _connect():
    from core.config import DB_PATH
    c = sqlite3.connect(DB_PATH, timeout=10)
    c.execute("PRAGMA busy_timeout=5000")
    c.row_factory = sqlite3.Row
    return c


def _query_mirror_by_aweme(aweme_id: str) -> dict[str, Any] | None:
    """在 mirror_cxt_videos 查这个 aweme_id (platform=0)."""
    with _connect() as c:
        row = c.execute(
            """SELECT aweme_id, title, author, video_url, cover_url, duration,
                      play_count, digg_count, sec_user_id
               FROM mirror_cxt_videos
               WHERE platform=0 AND aweme_id = ?
               LIMIT 1""",
            (aweme_id,),
        ).fetchone()
    if not row:
        return None
    return {
        "aweme_id": row["aweme_id"],
        "title": row["title"] or "",
        "author": row["author"] or "",
        "video_url": row["video_url"] or "",
        "cover_url": row["cover_url"] or "",
        "duration": row["duration"] or 0,
        "play_count": row["play_count"] or 0,
        "digg_count": row["digg_count"] or 0,
        "sec_user_id": row["sec_user_id"] or "",
    }


# ────────────────────────────────────────────────────────────────
# 主入口
# ────────────────────────────────────────────────────────────────

def resolve_douyin(url: str,
                    prefer_cache: bool = True,
                    allow_network: bool = True,
                    **_: Any) -> dict[str, Any]:
    """解析 Douyin URL → 统一 dict 格式.

    Args:
        url: 任何 Douyin URL 变体
        prefer_cache: 先查本地 mirror_cxt_videos (推荐)
        allow_network: 允许 share page 抓取 (本地没命中时)
    """
    from core.parsers import _ok, _err
    from core.app_config import get as cfg_get

    if not cfg_get("parser.douyin.enabled", True):
        return _err("douyin", "parser_disabled",
                     "parser.douyin.enabled = false")

    aweme_id = extract_aweme_id(url)
    short_token = extract_short_token(url)

    # 1. 本地 mirror 查
    if prefer_cache and aweme_id:
        hit = _query_mirror_by_aweme(aweme_id)
        if hit:
            log.info("[parser.douyin] mirror HIT aweme=%s title='%s'",
                     aweme_id, hit["title"][:30])
            return _ok(
                "douyin",
                video_id=aweme_id,
                direct_url=hit["video_url"],
                title=hit["title"],
                author=hit["author"],
                cover_url=hit["cover_url"],
                duration=hit["duration"],
                source="mirror_cxt",
                # 额外 metadata 给 caller 用
                play_count=hit["play_count"],
                digg_count=hit["digg_count"],
                sec_user_id=hit["sec_user_id"],
            )

    # 2. 短链需要展开 (未命中本地)
    if short_token and not aweme_id and allow_network:
        # 展开需要一次 HEAD/GET 跟 redirect
        resolved = _follow_short_link(url)
        if resolved and resolved != url:
            new_aweme = extract_aweme_id(resolved)
            if new_aweme and prefer_cache:
                hit = _query_mirror_by_aweme(new_aweme)
                if hit:
                    return _ok(
                        "douyin", video_id=new_aweme,
                        direct_url=hit["video_url"],
                        title=hit["title"], author=hit["author"],
                        cover_url=hit["cover_url"], duration=hit["duration"],
                        source="mirror_cxt_after_short_unfold",
                        resolved_from=url,
                    )
            aweme_id = new_aweme

    # 3. fallback: needs sign service (KS184 原方案)
    #    注意: 这里不做 best-effort share-page scraping, 因为抖音 share
    #    page 的 playAddr 被 __DYAVAILABLE 加密, 不搞 douyin_sign 就拿不到.
    source = cfg_get("parser.douyin.source", "mirror")
    if source == "mirror":
        return _err(
            "douyin", "need_mirror_entry",
            msg=(f"aweme_id={aweme_id!r} 不在本地 mirror_cxt_videos 里. "
                 "要么让 KS184 先抓一次 (用它的 douyin_sign), "
                 "要么 parser.douyin.source=sign 启用直接解析 (未实现)."),
            aweme_id=aweme_id,
            url=url,
        )

    # source == "sign" — KS184 方案, 我们没做
    return _err(
        "douyin", "sign_service_not_implemented",
        msg=("Douyin 实时 URL 解析需要 douyin_sign 服务. "
             "KS184 的 parse_douyin_link @ 0x21c0e460b40 调本地 sign. "
             "我们 Week 5 Top 2 预留此路径, 现用 mirror fallback."),
        aweme_id=aweme_id,
        url=url,
    )


def _follow_short_link(url: str, timeout: int = 8) -> str | None:
    """v.douyin.com 短链 → 长链 (GET, 只读 302 location)."""
    try:
        import requests
    except ImportError:
        return None
    try:
        r = requests.get(url, allow_redirects=True, timeout=timeout,
                          headers={"User-Agent": "Mozilla/5.0"})
        return r.url
    except Exception as e:
        log.debug("[parser.douyin] short link expand failed: %s", e)
        return None


# ────────────────────────────────────────────────────────────────
# CLI test
# ────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import sys, json
    sys.stdout.reconfigure(encoding="utf-8")
    # 用本地 mirror 实测 1 条
    with _connect() as c:
        row = c.execute(
            "SELECT aweme_id, title FROM mirror_cxt_videos WHERE platform=0 LIMIT 1"
        ).fetchone()
    if row:
        aweme = row["aweme_id"]
        test_url = f"https://www.douyin.com/video/{aweme}"
        print(f"test url: {test_url}")
        r = resolve_douyin(test_url, allow_network=False)
        print(json.dumps(r, ensure_ascii=False, indent=2))
    else:
        print("no mirror data")
