# -*- coding: utf-8 -*-
"""抖音视频真下载 — 从 mirror_cxt_videos 拿 video_url + 直接 GET.

Douyin CDN URL 已嵌 sign, 不用 douyin_sign 服务就能下 (前提: URL TTL 内):
  https://www.douyin.com/aweme/v1/play/?video_id=X&line=0&file_id=Y&sign=Z
  → 302 → https://v13.douyinvod.com/.../.../video.mp4

用法:
    from core.parsers.douyin_downloader import download_by_aweme_id

    r = download_by_aweme_id("7342424845398904076",
                              out_dir="D:/ks_automation/short_drama_videos/douyin/")
    # → {ok, file_path, size, aweme_id, title, author, duration}
"""
from __future__ import annotations
import hashlib
import logging
import sqlite3
import time
import secrets
from pathlib import Path
from typing import Any

log = logging.getLogger(__name__)


DOUYIN_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                  "AppleWebKit/537.36 (KHTML, like Gecko) "
                  "Chrome/120.0.0.0 Safari/537.36",
    "Accept": "video/mp4,video/*,*/*;q=0.8",
    "Accept-Language": "zh-CN,zh;q=0.9",
    "Referer": "https://www.douyin.com/",
}


def _connect():
    from core.config import DB_PATH
    c = sqlite3.connect(DB_PATH, timeout=10)
    c.execute("PRAGMA busy_timeout=5000")
    c.row_factory = sqlite3.Row
    return c


def download_by_aweme_id(
    aweme_id: str,
    out_dir: str | None = None,
    attempts: int = 2,
    verify: bool = True,
    cache: bool = True,
) -> dict[str, Any]:
    """下载 aweme_id 对应的 Douyin 视频.

    Args:
        aweme_id: Douyin video id (如 '7342424845398904076')
        out_dir: 输出目录, None = short_drama_videos/douyin/
        attempts: 重试次数
        verify: 下载后是否 ffprobe 校验 (默认开)
        cache: 是否走 download_cache 跨账号复用 (默认开)

    Returns:
        {ok: bool, file_path?, aweme_id, title?, author?, duration?, size?,
         error?, cache_hit?}
    """
    from core.app_config import get as cfg_get

    if not out_dir:
        out_dir = cfg_get("parser.douyin.output_dir",
                          r"D:\ks_automation\short_drama_videos\douyin")
    od = Path(out_dir)
    od.mkdir(parents=True, exist_ok=True)

    # 1. mirror 查 metadata + video_url
    with _connect() as c:
        row = c.execute(
            """SELECT aweme_id, title, author, video_url, cover_url, duration, sec_user_id
               FROM mirror_cxt_videos
               WHERE platform=0 AND aweme_id=? LIMIT 1""",
            (aweme_id,),
        ).fetchone()
    if not row:
        return {
            "ok": False, "aweme_id": aweme_id,
            "error": "not_in_mirror",
            "message": f"aweme={aweme_id} 不在 mirror_cxt_videos 中. "
                       "需先 sync_cxt_from_mcn 或让 KS184 抓一次.",
        }

    video_url = row["video_url"]
    title = row["title"] or ""
    author = row["author"] or ""
    duration = row["duration"] or 0
    cover_url = row["cover_url"] or ""

    # 2. cache hit check (跨账号复用)
    if cache:
        from core.downloader import _try_cache_hit
        hit = _try_cache_hit([video_url], od, drama_name=title)
        if hit:
            log.info("[douyin_dl] ★ cache hit aweme=%s title='%s'",
                     aweme_id, title[:30])
            return {
                "ok": True,
                "file_path": hit["file_path"],
                "aweme_id": aweme_id,
                "title": title, "author": author, "duration": duration,
                "size": hit["size"],
                "cover_url": cover_url,
                "cache_hit": True,
            }

    # 3. 真下载 (直接 GET, 已嵌 sign)
    import requests
    target = od / f"{aweme_id}_{secrets.token_hex(3)}.mp4"
    last_err = ""
    for attempt in range(1, attempts + 1):
        try:
            with requests.get(video_url, headers=DOUYIN_HEADERS,
                              stream=True, timeout=60,
                              allow_redirects=True) as r:
                if r.status_code not in (200, 206):
                    last_err = f"http_{r.status_code}"
                    log.warning("[douyin_dl] attempt %d: %s", attempt, last_err)
                    if attempt < attempts:
                        time.sleep(2 ** attempt)
                    continue
                ct = r.headers.get("Content-Type", "")
                if "video" not in ct.lower() and "octet" not in ct.lower():
                    last_err = f"bad_content_type:{ct[:40]}"
                    if attempt < attempts:
                        time.sleep(2 ** attempt)
                    continue
                total = int(r.headers.get("Content-Length", 0))
                downloaded = 0
                with open(target, "wb") as f:
                    for chunk in r.iter_content(
                        chunk_size=int(cfg_get("download.direct.chunk_size_kb", 256)) * 1024
                    ):
                        if chunk:
                            f.write(chunk)
                            downloaded += len(chunk)
                if downloaded < 102400:   # < 100KB suspicious
                    last_err = f"too_small_{downloaded}B"
                    try: target.unlink()
                    except Exception: pass
                    continue
                # download 成功
                break
        except Exception as e:
            last_err = f"{type(e).__name__}:{e}"
            log.warning("[douyin_dl] attempt %d exception: %s", attempt, last_err)
            if attempt < attempts:
                time.sleep(2 ** attempt)
            continue
    else:
        return {
            "ok": False, "aweme_id": aweme_id,
            "error": "download_failed", "message": last_err,
            "video_url": video_url[:120],
        }

    size = target.stat().st_size

    # 4. verify (ffprobe + 可选 sha1)
    verify_info = "skipped"
    if verify and cfg_get("video_verifier.enabled", True):
        from core.video_verifier import verify_video
        vr = verify_video(target)
        if not vr.get("ok"):
            errs = vr.get("errors", [])
            log.warning("[douyin_dl] verify failed: %s", errs)
            try: target.unlink()
            except Exception: pass
            return {
                "ok": False, "aweme_id": aweme_id,
                "error": "verify_failed", "message": "; ".join(errs)[:150],
                "size": size,
            }
        verify_info = (f"{vr.get('width')}x{vr.get('height')} "
                       f"{vr.get('codec')} dur={vr.get('duration'):.1f}s")

    # 5. 写 cache
    if cache:
        from core.downloader import _cache_download
        with _connect() as c:
            _cache_download(c, video_url, str(target), size)

    log.info("[douyin_dl] ✅ aweme=%s → %s (%dKB, %s)",
             aweme_id, target.name, size // 1024, verify_info)
    return {
        "ok": True,
        "file_path": str(target),
        "aweme_id": aweme_id,
        "title": title, "author": author, "duration": duration,
        "cover_url": cover_url,
        "size": size,
        "verify_info": verify_info,
        "cache_hit": False,
    }


def download_by_url(
    url: str,
    out_dir: str | None = None,
    **opts: Any,
) -> dict[str, Any]:
    """从 Douyin URL (任意格式) 下载 — 先 resolve_douyin 拿 aweme_id 再调 by_aweme_id."""
    from core.parsers.douyin import resolve_douyin
    info = resolve_douyin(url, allow_network=True)
    if not info.get("ok"):
        return info   # 原封不动透传错误
    aweme_id = info.get("video_id")
    if not aweme_id:
        return {"ok": False, "error": "no_aweme_id", "resolve_info": info}
    return download_by_aweme_id(aweme_id, out_dir=out_dir, **opts)


# CLI
if __name__ == "__main__":
    import sys, json
    sys.stdout.reconfigure(encoding="utf-8")
    if len(sys.argv) < 2:
        # Pick random mirror aweme for smoke
        with _connect() as c:
            row = c.execute(
                "SELECT aweme_id FROM mirror_cxt_videos "
                "WHERE platform=0 AND duration BETWEEN 30 AND 120 LIMIT 1"
            ).fetchone()
        if not row:
            print("没样本可测")
            sys.exit(1)
        aweme = row["aweme_id"]
        print(f"测 aweme={aweme}")
    else:
        aweme = sys.argv[1]

    r = download_by_aweme_id(aweme)
    print(json.dumps(r, ensure_ascii=False, indent=2, default=str))
