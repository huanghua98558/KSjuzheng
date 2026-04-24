# -*- coding: utf-8 -*-
"""封面完整服务 — 对齐 KS184 `_download_and_process_cover` (37 vars).

KS184 bytecode co_varnames 暴露的链路:
  cover_url → original_cover_path (requests 下)
    → ffprobe 读 video_width/video_height → is_portrait
    → target_width/target_height 计算
    → ffmpeg scale+crop + (可选 drawtext) → processed_cover_path
    → file_size check → compress_cmd → compressed_cover_path

我们的实现层次:
  1. prepare_cover(source="url"|"extract", ...) → 产出 working PNG
  2. ensure_size_and_ratio → 适配视频宽高比 + 尺寸
  3. compress_if_needed → 超阈值压缩
  4. (上层) burn_cover(...) → 烧水印

缓存机制 (对齐 KS184 `cover_names + search_dirs + potential_cover`):
  - cache_key = md5(video_path or drama_url) → cached PNG 复用
  - 避开重复 ffmpeg 抽帧

使用:
    from core.cover_service import prepare_cover
    r = prepare_cover(
        video_path="/path/processed.mp4",
        drama_url="https://...hls.m3u8",      # 用作 cache key
        cover_url="https://p5.a.yximgs.com/upic/.../cover.jpg",  # 快手原 cover, 优先
        output_dir="/path/cover_work",
    )
    # → {"ok": True, "cover_path": "...", "source": "downloaded|extracted|cached",
    #    "width": 720, "height": 1280, "is_portrait": True, "size_kb": 120}
"""
from __future__ import annotations

import hashlib
import logging
import os
import re
import secrets
import shutil
import subprocess
import time
from pathlib import Path
from typing import Any

import requests

from core.app_config import get as cfg_get

log = logging.getLogger(__name__)

CACHE_ROOT = Path(r"D:\ks_automation\short_drama_videos\.cover_cache")


def _ffmpeg() -> str:
    for p in [
        r"C:\Program Files\kuaishou2\KS184.7z\KS184\tools\ffmpeg\bin-xin\ffmpeg.exe",
        r"C:\Program Files\kuaishou2\KS184.7z\KS184\tools\ffmpeg\bin\ffmpeg.exe",
        r"D:\ks_automation\tools\m3u8dl\ffmpeg.exe",
    ]:
        if os.path.isfile(p):
            return p
    return "ffmpeg"


def _cache_key(video_path: str, drama_url: str | None) -> str:
    """按 drama_url (优先, 跨账号复用) 或 video_path 算 key."""
    key_src = drama_url or video_path
    return hashlib.md5(key_src.encode("utf-8")).hexdigest()[:16]


def _probe_video_dims(video_path: str) -> tuple[int, int] | None:
    """ffprobe 读视频宽高.

    对齐 KS184: ffprobe_path + probe_cmd + dimensions + video_width + video_height
    """
    cmd = [_ffmpeg(), "-i", video_path, "-t", "0.1", "-f", "null", "-"]
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=10,
                           encoding="utf-8", errors="replace")
        m = re.search(r"Stream.+Video.+ (\d+)x(\d+)", r.stderr or "")
        if m:
            return int(m.group(1)), int(m.group(2))
    except Exception:
        pass
    return None


def _extract_first_frame(video_path: str, out_png: str, at_sec: float = 1.5) -> bool:
    """从视频抽 1 帧 (fallback, 当 cover_url 下不到时)."""
    cmd = [_ffmpeg(), "-y", "-loglevel", "error",
           "-ss", f"{at_sec}", "-i", video_path,
           "-vframes", "1", "-q:v", "2", out_png]
    r = subprocess.run(cmd, capture_output=True, timeout=20)
    return r.returncode == 0 and os.path.isfile(out_png)


def _download_cover(url: str, out_path: str, timeout: int = 20) -> bool:
    """下载快手原 cover (yximgs.com / kuaishoupay cdn)."""
    try:
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                          "AppleWebKit/537.36 Chrome/120.0.0.0 Safari/537.36",
            "Referer": "https://www.kuaishou.com/",
        }
        r = requests.get(url, headers=headers, timeout=timeout, stream=True)
        r.raise_for_status()
        total = 0
        with open(out_path, "wb") as f:
            for chunk in r.iter_content(chunk_size=64 * 1024):
                if chunk:
                    f.write(chunk)
                    total += len(chunk)
        return total > 1024   # >1KB 算成功
    except Exception as e:
        log.debug("[cover] download %s failed: %s", url[:60], e)
        return False


def ensure_size_and_ratio(
    cover_path: str,
    target_width: int = 720,
    target_height: int = 1280,
    is_portrait: bool = True,
) -> dict:
    """把封面缩放+裁剪到目标比例.

    对齐 KS184: is_portrait + target_width + target_height + filter_chain + ffmpeg_cmd
    """
    from PIL import Image
    try:
        img = Image.open(cover_path)
    except Exception as e:
        return {"ok": False, "error": f"open_failed: {e}"}

    src_w, src_h = img.size
    src_ratio = src_w / src_h
    target_ratio = target_width / target_height

    # 如果比例已接近 → 只 resize
    if abs(src_ratio - target_ratio) < 0.03:
        resized = img.resize((target_width, target_height), Image.LANCZOS)
        resized.save(cover_path, "PNG")
        return {"ok": True, "mode": "resized_only",
                "from": (src_w, src_h), "to": (target_width, target_height)}

    # 否则 scale+crop (保证填满, 多余裁掉)
    if src_ratio > target_ratio:
        # 源更宽 → 按高缩放, 裁左右
        new_w = int(src_h * target_ratio)
        left = (src_w - new_w) // 2
        cropped = img.crop((left, 0, left + new_w, src_h))
    else:
        # 源更高 → 按宽缩放, 裁上下
        new_h = int(src_w / target_ratio)
        top = (src_h - new_h) // 2
        cropped = img.crop((0, top, src_w, top + new_h))
    resized = cropped.resize((target_width, target_height), Image.LANCZOS)
    resized.save(cover_path, "PNG")
    return {"ok": True, "mode": "scale_crop",
            "from": (src_w, src_h), "to": (target_width, target_height)}


def compress_if_needed(
    cover_path: str,
    max_size_kb: int = 500,
    min_quality: int = 70,
) -> dict:
    """封面过大自动压缩到 JPEG. PNG 改 JPEG 体积能降 5-10x.

    对齐 KS184: file_size + file_size_mb + compress_cmd + compressed_cover_path
    """
    size = os.path.getsize(cover_path)
    if size <= max_size_kb * 1024:
        return {"ok": True, "skipped": True, "size_kb": size // 1024}

    from PIL import Image
    # 改存 JPEG (原地覆盖 .png 扩展名保持)
    img = Image.open(cover_path).convert("RGB")
    # 按 quality 逐渐降直到 < max_size_kb
    for q in range(95, min_quality - 1, -5):
        img.save(cover_path, "JPEG", quality=q, optimize=True)
        new_size = os.path.getsize(cover_path)
        if new_size <= max_size_kb * 1024:
            return {"ok": True, "compressed": True, "quality": q,
                    "size_before_kb": size // 1024,
                    "size_after_kb": new_size // 1024}
    # 最低 q 也超 → 认了
    return {"ok": True, "compressed": True, "quality": min_quality,
            "size_before_kb": size // 1024,
            "size_after_kb": os.path.getsize(cover_path) // 1024}


def prepare_cover(
    video_path: str,
    drama_url: str | None = None,
    cover_url: str | None = None,
    output_dir: str | None = None,
    force_refresh: bool = False,
) -> dict[str, Any]:
    """主入口: 准备一张对齐快手规格的封面 (还没烧水印).

    优先级:
      1. 缓存命中 → 直接用
      2. 有 cover_url (KS184 偏好) → 下载
      3. fallback → 从视频抽第 1.5 秒帧

    Args:
        video_path: 处理后视频 (用于抽帧 fallback + 读宽高)
        drama_url: 用作缓存 key (跨账号可复用)
        cover_url: 快手原 cover 直链 (存在 drama_links.remark 里)
        output_dir: 输出目录. None = 视频同目录下 .cover_work/
        force_refresh: 忽略缓存

    Returns:
        {ok, cover_path, source, width, height, is_portrait,
         size_kb, elapsed_sec, from_cache, error?}
    """
    t0 = time.time()

    if not os.path.isfile(video_path):
        return {"ok": False, "error": f"video_not_found: {video_path}"}

    output_dir = Path(output_dir) if output_dir else \
                 Path(video_path).parent / ".cover_work"
    output_dir.mkdir(parents=True, exist_ok=True)

    CACHE_ROOT.mkdir(parents=True, exist_ok=True)
    cache_key = _cache_key(video_path, drama_url)
    cached_file = CACHE_ROOT / f"{cache_key}.png"

    # ── ① 缓存命中 ──
    if cached_file.exists() and not force_refresh:
        # 复制到 output_dir
        out = output_dir / f"cover_{secrets.token_hex(4)}.png"
        shutil.copy(cached_file, out)
        dims = _probe_video_dims(video_path) or (720, 1280)
        return {
            "ok": True, "cover_path": str(out),
            "source": "cached", "from_cache": True,
            "width": dims[0], "height": dims[1],
            "is_portrait": dims[1] > dims[0],
            "size_kb": cached_file.stat().st_size // 1024,
            "elapsed_sec": round(time.time() - t0, 2),
        }

    # ── ② 下载快手原 cover ──
    out_cover = output_dir / f"cover_{secrets.token_hex(4)}.png"
    source = None
    if cover_url:
        if _download_cover(cover_url, str(out_cover)):
            source = "downloaded"
            log.info("[cover] 下载快手原封面: %s", cover_url[:60])

    # ── ③ fallback: 抽视频帧 ──
    if source is None:
        if _extract_first_frame(video_path, str(out_cover)):
            source = "extracted"
            log.info("[cover] 从视频抽帧: %s", Path(video_path).name)
        else:
            return {"ok": False, "error": "both_download_and_extract_failed"}

    # ── ④ 读视频宽高 + is_portrait 判断 ──
    dims = _probe_video_dims(video_path)
    if dims:
        video_w, video_h = dims
        is_portrait = video_h > video_w
    else:
        video_w, video_h = 720, 1280
        is_portrait = True

    # ── ⑤ 适配比例 ──
    if is_portrait:
        target_w, target_h = 720, 1280
    else:
        target_w, target_h = 1280, 720

    ratio_result = ensure_size_and_ratio(str(out_cover), target_w, target_h,
                                           is_portrait=is_portrait)

    # ── ⑥ 大小压缩 ──
    max_size_kb = cfg_get("cover.max_size_kb", 500)
    compress_result = compress_if_needed(str(out_cover), max_size_kb=max_size_kb)

    # ── ⑦ 写缓存 ──
    try:
        shutil.copy(out_cover, cached_file)
    except Exception:
        pass

    return {
        "ok": True,
        "cover_path": str(out_cover),
        "source": source,
        "from_cache": False,
        "width": target_w, "height": target_h,
        "is_portrait": is_portrait,
        "source_dims": (video_w, video_h),
        "size_kb": os.path.getsize(out_cover) // 1024,
        "elapsed_sec": round(time.time() - t0, 2),
        "ratio_op": ratio_result,
        "compress": compress_result,
    }


def gc_cover_cache(older_than_days: int = 14) -> int:
    """清理旧封面缓存."""
    if not CACHE_ROOT.exists():
        return 0
    n = 0
    cutoff = time.time() - older_than_days * 86400
    for f in CACHE_ROOT.glob("*.png"):
        try:
            if f.stat().st_mtime < cutoff:
                f.unlink()
                n += 1
        except Exception:
            pass
    return n


if __name__ == "__main__":
    import argparse, json, sys
    sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser()
    ap.add_argument("--video", required=True)
    ap.add_argument("--cover-url", default=None)
    ap.add_argument("--drama-url", default=None)
    ap.add_argument("--output-dir", default=None)
    ap.add_argument("--force", action="store_true")
    ap.add_argument("--gc", action="store_true")
    args = ap.parse_args()

    if args.gc:
        n = gc_cover_cache()
        print(f"cleaned {n} old covers")
    else:
        r = prepare_cover(args.video, drama_url=args.drama_url,
                          cover_url=args.cover_url,
                          output_dir=args.output_dir,
                          force_refresh=args.force)
        print(json.dumps(r, ensure_ascii=False, indent=2, default=str))
