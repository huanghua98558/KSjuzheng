# -*- coding: utf-8 -*-
"""统一视频 URL 解析层 — 对齐 KS184 `parse_video_link @ 0x21c0e460d40`.

设计原则:
  - 一个 entry: parse_video_link(url) → {platform, video_id, direct_url, metadata}
  - 3 分支: kuaishou / douyin / chengxing (auto-detect by URL)
  - 返回统一 dict 格式, caller (downloader) 可以平等对待

用法:
    from core.parsers import parse_video_link, detect_source

    info = parse_video_link("https://www.douyin.com/video/7342424845398904076")
    # → {"ok": True, "platform": "douyin", "video_id": "7342424845398904076",
    #    "direct_url": "...", "title": "...", "author": "...", "duration": 39,
    #    "source": "mirror_cxt"  # 或 "sign_service" / "share_page_scrape"}

    # 不识别 / 不支持时
    info = parse_video_link("http://example.com/foo")
    # → {"ok": False, "error": "unknown_source", "platform": "unknown"}
"""
from __future__ import annotations

import logging
import re
from typing import Any
from urllib.parse import urlparse

log = logging.getLogger(__name__)


# ────────────────────────────────────────────────────────────────
# URL 识别
# ────────────────────────────────────────────────────────────────

# Kuaishou 各域名模式
_KS_DOMAINS = (
    "kuaishou.com", "ksapisrv.com", "v.kuaishou.com",
    "kwaicdn.com", "djvod.ndcimgs.com", "yximgs.com",
    "oskwai.com", "wsukwai.com", "kwaiadcdn.com",
)

# Douyin 各域名模式
_DOUYIN_DOMAINS = (
    "douyin.com", "iesdouyin.com", "v.douyin.com",
    "amemv.com", "aweme.snssdk.com", "douyincdn.com",
    "byteimg.com", "toutiaovod.com",
)

# 橙星推 — 2026-04-21 从 KS184 memscan 确认的主域名 (parse_chengxing_video_url @ 0x21c0e460940)
_CHENGXING_DOMAINS = (
    "mplayer.ddliveshow.com",   # ★ 真正的 play.html + jupiter API 域名
    "ddliveshow.com",
    "chengxingtui.com", "chengxing.kuaishou.com", "im.zhongxiangbao.com",
)

# Douyin short link 模式
_DOUYIN_SHORT_RE = re.compile(r"v\.douyin\.com/([A-Za-z0-9]+)/?")
# Douyin 长链 video id
_DOUYIN_VIDEO_RE = re.compile(r"douyin\.com/(?:video|share/video|aweme/v1/play)/[?]?.*?(\d{10,})")
_DOUYIN_AWEME_RE = re.compile(r"(?:aweme_id|video_id|id)=(\d{10,})", re.I)

# Kuaishou 短链
_KS_SHORT_RE = re.compile(r"kuaishou\.com/f/([A-Za-z0-9_\-]+)")


def detect_source(url: str) -> str:
    """返回 'kuaishou' / 'douyin' / 'chengxing' / 'direct_mp4' / 'unknown'."""
    if not url or not isinstance(url, str):
        return "unknown"
    u = url.lower().strip()

    # 快速域名匹配
    try:
        host = urlparse(u).netloc.lower()
    except Exception:
        host = ""

    for d in _KS_DOMAINS:
        if d in host or d in u:
            return "kuaishou"
    for d in _DOUYIN_DOMAINS:
        if d in host or d in u:
            return "douyin"
    for d in _CHENGXING_DOMAINS:
        if d in host or d in u:
            return "chengxing"

    # 直链 mp4
    if u.endswith(".mp4") or ".mp4?" in u or ".m3u8" in u:
        return "direct_mp4"

    # v.douyin.com 短链
    if "v.douyin.com" in u:
        return "douyin"

    return "unknown"


# ────────────────────────────────────────────────────────────────
# 统一返回结构
# ────────────────────────────────────────────────────────────────

def _ok(platform: str, video_id: str, direct_url: str = "",
        title: str = "", author: str = "", cover_url: str = "",
        duration: int = 0, source: str = "",
        **extra: Any) -> dict[str, Any]:
    return {
        "ok": True,
        "platform": platform,
        "video_id": video_id,
        "direct_url": direct_url,
        "title": title,
        "author": author,
        "cover_url": cover_url,
        "duration": duration,
        "source": source,
        **extra,
    }


def _err(platform: str, code: str, msg: str = "",
          **extra: Any) -> dict[str, Any]:
    return {
        "ok": False,
        "platform": platform,
        "error": code,
        "message": msg,
        **extra,
    }


# ────────────────────────────────────────────────────────────────
# 主分派入口
# ────────────────────────────────────────────────────────────────

def parse_video_link(url: str, **opts: Any) -> dict[str, Any]:
    """统一分派.

    opts 可包含:
        prefer_cache: bool = True    (先查本地 mirror, 不命中再走 resolver)
        allow_network: bool = True   (允许真发 HTTP, False 只查本地)
    """
    if not url:
        return _err("unknown", "empty_url")

    src = detect_source(url)

    if src == "kuaishou":
        # 已有逻辑 → 让 caller (downloader) 处理
        # 这里只返回识别结果, 不再重新实现
        return _ok("kuaishou", video_id="",
                   direct_url=url,   # downloader 自己 resolve
                   source="dispatch_to_existing_downloader")

    if src == "douyin":
        from core.parsers.douyin import resolve_douyin
        return resolve_douyin(url, **opts)

    if src == "chengxing":
        from core.parsers.chengxing import resolve_chengxing
        return resolve_chengxing(url, **opts)

    if src == "direct_mp4":
        return _ok("direct_mp4", video_id="", direct_url=url,
                    source="already_direct")

    return _err("unknown", "unknown_source",
                 f"URL 格式不认识: {url[:80]}")


# ────────────────────────────────────────────────────────────────
# CLI 测试
# ────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import sys, json
    sys.stdout.reconfigure(encoding="utf-8")
    test_urls = [
        "https://www.kuaishou.com/f/X-4974CYHN8hT1sW",
        "https://v.kuaishou.com/abc123",
        "https://www.douyin.com/video/7342424845398904076",
        "https://v.douyin.com/iABCDE/",
        "https://www.douyin.com/aweme/v1/play/?video_id=v0d00fg10000d5h5u7vog65j2ucia6pg",
        "https://k0u2ayeay7dy1czw2408x8722xb800x7xx1cz.djvod.ndcimgs.com/upic/xxx.mp4",
        "http://unknown.com/video/foo",
    ]
    for u in test_urls:
        src = detect_source(u)
        r = parse_video_link(u, allow_network=False)
        print(f"src={src:<12}  ok={r.get('ok')}  platform={r.get('platform'):<10}  url={u[:70]}")
        if not r.get("ok"):
            print(f"                 → err={r.get('error')}: {r.get('message','')[:60]}")
