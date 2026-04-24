# -*- coding: utf-8 -*-
"""橙星推 (chengxingtui / CXT) 平台解析器.

对齐 KS184 `parse_chengxing_video_url @ 0x21c0e460940` (Nuitka 反编译 docstring):

    星推视频播放链接，获取真实视频下载地址
    橙星推数据库中的 video_url 是播放页面链接, 格式如:
        https://mplayer.ddliveshow.com/play.html?code=2603301325104553748877
    需要通过 API 解析获取真实下载地址:
        https://mplayer.ddliveshow.com/jupiter/mplayer/video.info/{code}

    Returns:
      - 是否成功: "真" / "假"
      - 返回下载地址: 真实视频下载URL
      - 错误信息: 失败时的错误描述

════════════════════════════════════════════════════════════════════════
  三路解析策略 (按优先级 1 → 2 → 3):
════════════════════════════════════════════════════════════════════════

  ┌───────────────────────────────────────────────────────────────┐
  │  1. LOCAL MIRROR  —  查 mirror_cxt_videos 已同步数据         │
  │     MCN 的 cxt_videos.video_url 已经是 **直链**:              │
  │       platform=0 (Douyin)   → douyin.com/aweme/v1/play/...    │
  │       platform=1 (Kuaishou) → djvod.ndcimgs.com/upic/...mp4   │
  │     命中率 ~98% (1457 videos 已同步)                          │
  ├───────────────────────────────────────────────────────────────┤
  │  2. JUPITER API  —  mplayer.ddliveshow.com 真解析              │
  │     仅当 URL 是 play.html?code=XXX 形式才走                    │
  │       GET /jupiter/mplayer/video.info/{code}                   │
  │     (罕见, 本地 mirror 已全部预解析)                           │
  ├───────────────────────────────────────────────────────────────┤
  │  3. PASSTHROUGH  —  已是直链/CDN URL 直接返回                  │
  └───────────────────────────────────────────────────────────────┘

════════════════════════════════════════════════════════════════════════
  KS184 证据链:
════════════════════════════════════════════════════════════════════════

  memscan  nuitka_functions_v3.txt:12909-12911
    地址: 0x21c0e460940
    完整 docstring (含 URL 模板)

  memscan  urls.txt:2924-2926
    https://mplayer.ddliveshow.com/jupiter/mplayer/video.info/
    https://mplayer.ddliveshow.com/play.html?code=2603301325104553748877
    https://mplayer.ddliveshow.com/play.html?code=xxx

  memscan  account_drama_mode_tab.md:96-107
    _check_chengxing_permission (前置) + _publish_chengxing (独立发布分支)

  MCN shortju DB 实证 (2026-04-21):
    mirror_cxt_videos: 1457 条 (284 Douyin + 1173 Kuaishou)
    platform=0: douyin aweme URLs (已直链)
    platform=1: djvod.ndcimgs.com URLs (已直链)
    ddliveshow URL 数: 0 (MCN 侧已全量预解析)
"""
from __future__ import annotations

import logging
import re
import sqlite3
from typing import Any
from urllib.parse import urlparse, parse_qs

log = logging.getLogger(__name__)

# ────────────────────────────────────────────────────────────────
# 常量
# ────────────────────────────────────────────────────────────────

MPLAYER_HOST = "mplayer.ddliveshow.com"
JUPITER_BASE = f"https://{MPLAYER_HOST}/jupiter/mplayer/video.info"
PLAY_PAGE_BASE = f"https://{MPLAYER_HOST}/play.html"

# play.html?code= 里的 code 格式 (22 位纯数字, 样本: 2603301325104553748877)
CODE_RE = re.compile(r"[?&]code=([0-9A-Za-z_\-]{8,64})")

DEFAULT_TIMEOUT = 15
DEFAULT_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "zh-CN,zh;q=0.9",
    "Referer": PLAY_PAGE_BASE,
}


# ────────────────────────────────────────────────────────────────
# URL 识别 + code 抽取
# ────────────────────────────────────────────────────────────────

def is_chengxing_url(url: str) -> bool:
    """对齐 KS184 `is_chengxing_url @ 0x21c0e460a40`.

    True 表示是橙星推播放链接 (mplayer.ddliveshow.com 下的 URL).
    """
    if not url or not isinstance(url, str):
        return False
    try:
        return MPLAYER_HOST in urlparse(url).netloc.lower()
    except Exception:
        return MPLAYER_HOST in url.lower()


def extract_code(url: str) -> str | None:
    """从 play.html?code=XXXX 形式的 URL 抽 code. 找不到返回 None."""
    if not url:
        return None
    m = CODE_RE.search(url)
    if m:
        return m.group(1)
    # 尝试标准 parse_qs
    try:
        q = parse_qs(urlparse(url).query)
        codes = q.get("code") or []
        if codes:
            return codes[0]
    except Exception:
        pass
    # 尝试 path 末尾 /jupiter/mplayer/video.info/{code}
    try:
        parts = [p for p in urlparse(url).path.split("/") if p]
        if parts and parts[-1] and parts[-1] not in ("play.html", "video.info"):
            return parts[-1]
    except Exception:
        pass
    return None


def is_direct_video_url(url: str) -> bool:
    """已是直链 (mp4 / m3u8 / djvod / aweme/v1/play) → 不需要解析."""
    if not url:
        return False
    u = url.lower()
    return any(s in u for s in (
        ".mp4", ".m3u8",
        "djvod.ndcimgs.com/upic",       # 快手 CDN 直链
        "aweme/v1/play",                 # 抖音直链
    ))


# ────────────────────────────────────────────────────────────────
# 分路 1: LOCAL MIRROR 查本地镜像
# ────────────────────────────────────────────────────────────────

def _lookup_mirror(url: str) -> dict[str, Any] | None:
    """在 mirror_cxt_videos 里查 video_url 或 aweme_id 命中.

    查询策略 (按顺序):
      a. 直接按 video_url 完全匹配
      b. 从 url 里抽 code, 按 aweme_id LIKE 匹配
      c. 如果 url 就是 djvod / aweme 直链 → 反查 video_url 精确匹配

    命中返回 dict (含 direct_url / title / author / platform).
    无命中返回 None.
    """
    try:
        from core.config import DB_PATH
    except Exception:
        return None

    try:
        c = sqlite3.connect(DB_PATH, timeout=10)
        c.execute("PRAGMA busy_timeout=10000")
        cur = c.cursor()

        # a. 完整 URL 匹配 (play.html 或直链都试)
        row = cur.execute(
            """SELECT id, title, author, aweme_id, video_url, cover_url,
                      duration, platform, description
                 FROM mirror_cxt_videos
                 WHERE video_url = ? LIMIT 1""",
            (url,),
        ).fetchone()

        # b. 从 play.html?code=XXX 抽 code, 按 aweme_id 匹配
        if not row:
            code = extract_code(url)
            if code:
                row = cur.execute(
                    """SELECT id, title, author, aweme_id, video_url, cover_url,
                              duration, platform, description
                         FROM mirror_cxt_videos
                         WHERE aweme_id = ? LIMIT 1""",
                    (code,),
                ).fetchone()

        c.close()
        if not row:
            return None

        (vid, title, author, aweme_id, video_url, cover_url,
         duration, platform, description) = row
        platform_name = {0: "douyin", 1: "kuaishou"}.get(platform, "unknown")
        return {
            "cxt_id": vid,
            "title": title or "",
            "author": author or "",
            "aweme_id": aweme_id or "",
            "direct_url": video_url or "",
            "cover_url": cover_url or "",
            "duration": int(duration or 0),
            "platform_real": platform_name,
            "description": description or "",
        }
    except Exception as e:
        log.warning("[chengxing] mirror lookup failed: %s", e)
        return None


# ────────────────────────────────────────────────────────────────
# 分路 2: JUPITER API  GET /jupiter/mplayer/video.info/{code}
# ────────────────────────────────────────────────────────────────

def _call_jupiter_api(code: str, timeout: int = DEFAULT_TIMEOUT) -> dict[str, Any]:
    """调 mplayer.ddliveshow.com Jupiter 解析 API.

    ════════════════════════════════════════════════════════════════════
      实测结论 (2026-04-21, 真调 7 次):
    ════════════════════════════════════════════════════════════════════
      - ONLY GET 有效. POST 总返 405 Method Not Allowed.
      - 响应字段 (真实): err_code (int), err_msg (str), data (dict?)
      - err_code == 0 成功, 非 0 失败
      - 我们手头所有 code (22-digit share code 样本 + aweme_id) 全部返
        err_code=100 "获取视频链接失败" — 可能需要鉴权 token / Cookie,
        或这些 code 是测试 / 过期样本.
      - 真实成功响应字段 **未抓到**, 字段名基于 KS184 docstring 猜测:
        `短剧标题` / `返回下载地址` / `返回作者名称` / `返回封面下载地址` /
        `时长` / `返回文案` / `同框`
        (也可能是 data.title / data.download_url, 需抓到 1 条才知道)

    输入约束:
      code 必须是 CXT 签发的 **22 位 share code** (play.html?code=XXX 格式).
      **aweme_id 不能直接用** (实测都返 err_code=100).

    Returns:
        {"ok": bool, "direct_url": str, "raw": dict, "error": str|None}
    """
    import requests

    url = f"{JUPITER_BASE}/{code}"

    try:
        log.info("[chengxing] GET %s", url)
        resp = requests.get(
            url,
            headers=DEFAULT_HEADERS,
            timeout=timeout,
            allow_redirects=True,
        )
        resp.raise_for_status()
        data = resp.json()
    except Exception as e:
        return {"ok": False, "direct_url": "", "raw": {},
                "error": f"jupiter_api_http_failed: {e}"}

    # --- 先识别实测确认的错误码 ---
    err_code = data.get("err_code")
    err_msg = data.get("err_msg") or ""
    if err_code is not None and err_code != 0:
        return {"ok": False, "direct_url": "", "raw": data,
                "error": f"jupiter_err_code={err_code}: {err_msg}"}

    # --- 成功响应解析 (字段名 KS184 docstring 推测, 实测到后校准) ---
    payload = data.get("data") if isinstance(data.get("data"), dict) else data

    direct_url = (
        payload.get("返回下载地址")
        or payload.get("download_url")
        or payload.get("video_url")
        or payload.get("url")
        or ""
    )

    if not direct_url:
        return {"ok": False, "direct_url": "", "raw": data,
                "error": err_msg or "jupiter_returned_empty_url"}

    return {
        "ok": True,
        "direct_url": direct_url,
        "raw": data,
        "title":    payload.get("短剧标题")   or payload.get("title") or "",
        "author":   payload.get("返回作者名称") or payload.get("author") or "",
        "cover_url":payload.get("返回封面下载地址") or payload.get("cover_url") or "",
        "caption":  payload.get("返回文案")   or payload.get("caption") or "",
        "duration": int(payload.get("时长")   or payload.get("duration") or 0),
        "allow_coshoot": bool(payload.get("同框") or 0),
        "error": None,
    }


# ────────────────────────────────────────────────────────────────
# 主入口
# ────────────────────────────────────────────────────────────────

def resolve_chengxing(url: str, **opts: Any) -> dict[str, Any]:
    """橙星推统一解析入口. Signature matches core/parsers/douyin.py.

    输入 3 种可能:
      - https://mplayer.ddliveshow.com/play.html?code=2603301325104553748877
      - https://mplayer.ddliveshow.com/jupiter/mplayer/video.info/2603301325...
      - 纯 code (22 位数字) — 兼容 drama_links.remark 直接存 code 的场景

    返回 `_ok()` dict (统一格式, 兼容 downloader / publisher).
    """
    from core.parsers import _ok, _err
    from core.app_config import get as cfg_get

    if not cfg_get("parser.chengxing.enabled", False):
        return _err("chengxing", "parser_disabled",
                    msg="parser.chengxing.enabled=false",
                    url=url)

    if not url:
        return _err("chengxing", "empty_url")

    prefer_cache = bool(opts.get("prefer_cache", True))
    allow_network = bool(opts.get("allow_network", True))

    # ——————— 分路 3: passthrough ———————
    if is_direct_video_url(url) and not is_chengxing_url(url):
        return _ok("chengxing", video_id="", direct_url=url,
                   source="already_direct")

    # ——————— 分路 1: LOCAL MIRROR ———————
    if prefer_cache:
        hit = _lookup_mirror(url)
        if hit:
            log.info("[chengxing] mirror HIT: cxt_id=%s platform=%s",
                     hit["cxt_id"], hit["platform_real"])
            return _ok(
                "chengxing",
                video_id=str(hit["cxt_id"]),
                direct_url=hit["direct_url"],
                title=hit["title"],
                author=hit["author"],
                cover_url=hit["cover_url"],
                duration=hit["duration"],
                source=f"mirror_cxt_videos:{hit['platform_real']}",
                platform_real=hit["platform_real"],
                description=hit["description"],
                aweme_id=hit["aweme_id"],
            )

    # ——————— 分路 2: JUPITER API ———————
    if not allow_network:
        return _err("chengxing", "mirror_miss_network_disabled",
                    msg=("本地 mirror_cxt_videos 没命中这条 URL, "
                         "且 allow_network=False. 先 `python -m "
                         "scripts.sync_cxt_from_mcn` 同步."),
                    url=url)

    share_code = extract_code(url)
    if not share_code and re.fullmatch(r"[0-9A-Za-z_\-]{8,64}", url.strip()):
        # 允许直接传 code (22-digit 纯数字)
        share_code = url.strip()

    if not share_code:
        return _err("chengxing", "code_not_found_in_url",
                    msg=f"无法从 URL 抽出 code: {url[:80]}", url=url)

    result = _call_jupiter_api(share_code)
    if not result["ok"]:
        # 注意: _err 的 2nd positional 叫 code (error code), 避免冲突用 share_code kwarg
        return _err("chengxing", "jupiter_api_failed",
                    msg=result.get("error", ""), url=url,
                    share_code=share_code,
                    raw=result.get("raw"))

    return _ok(
        "chengxing",
        video_id=share_code,
        direct_url=result["direct_url"],
        title=result.get("title", ""),
        author=result.get("author", ""),
        cover_url=result.get("cover_url", ""),
        duration=result.get("duration", 0),
        source="jupiter_api",
        share_code=share_code,
        caption=result.get("caption", ""),
        allow_coshoot=result.get("allow_coshoot", False),
    )


# ────────────────────────────────────────────────────────────────
# CLI 测试
# ────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import sys, json
    sys.stdout.reconfigure(encoding="utf-8")
    tests = [
        "https://mplayer.ddliveshow.com/play.html?code=2603301325104553748877",
        "https://mplayer.ddliveshow.com/jupiter/mplayer/video.info/2603301325104553748877",
        "2603301325104553748877",
        "https://www.douyin.com/aweme/v1/play/?video_id=v0200fg10000d62tivfog65p",
        "https://k0u70y5yd9yd9zw2409x8c34xe00x100xx19z.djvod.ndcimgs.com/upic/xxx.mp4",
        "http://example.com/foo",
        "",
    ]
    for u in tests:
        is_cx = is_chengxing_url(u)
        code = extract_code(u)
        r = resolve_chengxing(u, allow_network=False)
        print(f"\n---\nurl={u[:80]}")
        print(f"  is_chengxing={is_cx}  code={code}")
        print(f"  result={json.dumps(r, ensure_ascii=False)[:200]}")
