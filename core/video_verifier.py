# -*- coding: utf-8 -*-
"""视频完整性校验 — 对齐 KS184 `_check_device_file_hash @ 0x21c0e01dd40`.

三层验证 (cost 递增):
  Layer 1. file_exists + size (毫秒)
  Layer 2. ffprobe JSON (100-300ms) — 拿 duration/codec/w×h/has_audio/bitrate
  Layer 3. sha1 hash (大文件 1-5s) — 内容 fingerprint, 用于 cross-account 去重
           可选 (cfg: video_verifier.compute_hash, 默认 false)

设计 API:
  verify_video(path) -> {
    ok: bool,
    size: int, hash_sha1: str|None,
    duration: float, codec: str, width: int, height: int,
    bitrate: int, has_audio: bool, probe_json: dict,
    errors: list[str]
  }

  compute_sha1(path) -> str    (独立调用, 复用已有 verify 结果避免重算)
"""
from __future__ import annotations
import hashlib
import json
import logging
import os
import subprocess
from pathlib import Path
from typing import Any

log = logging.getLogger(__name__)


# ────────────────────────────────────────────────────────────────
# ffprobe 二进制定位
# ────────────────────────────────────────────────────────────────

_FFPROBE_PATHS = [
    r"D:\ks_automation\tools\ffmpeg\bin\ffprobe.exe",
    r"C:\Program Files\kuaishou2\KS184.7z\KS184\tools\ffmpeg\bin\ffprobe.exe",
    r"C:\Program Files\kuaishou2\KS182.7z\KS182\tools\ffmpeg\bin\ffprobe.exe",
]


def _find_ffprobe() -> str | None:
    """KS184 _find_ffprobe @ 0x21c0e4b2e40 的对齐实现."""
    for p in _FFPROBE_PATHS:
        if os.path.isfile(p):
            return p
    # PATH fallback
    import shutil
    p = shutil.which("ffprobe")
    return p


# ────────────────────────────────────────────────────────────────
# 各层校验
# ────────────────────────────────────────────────────────────────

def _check_size(path: str | Path, min_bytes: int = 102400) -> tuple[bool, str, int]:
    """Layer 1: 文件存在 + 大小合理 (默认 ≥100KB 才算有效视频)."""
    p = Path(path)
    if not p.exists():
        return False, "file_not_exists", 0
    try:
        size = p.stat().st_size
    except Exception as e:
        return False, f"stat_error:{e}", 0
    if size < min_bytes:
        return False, f"too_small_{size}B", size
    return True, "ok", size


def _ffprobe_json(path: str | Path, timeout: float = 10.0) -> tuple[bool, dict, str]:
    """Layer 2: ffprobe JSON 结构化输出. 返 (ok, data, reason)."""
    ffprobe = _find_ffprobe()
    if not ffprobe:
        return False, {}, "ffprobe_not_found"
    try:
        r = subprocess.run(
            [ffprobe, "-v", "error",
             "-show_format", "-show_streams",
             "-of", "json",
             "-timeout", "5000000",   # 5s usec
             str(path)],
            capture_output=True, text=True, timeout=timeout,
            encoding="utf-8", errors="replace",
        )
        if r.returncode != 0:
            err = (r.stderr or "").strip().split("\n")[0][:150]
            return False, {}, f"ffprobe_rc={r.returncode}: {err}"
        try:
            data = json.loads(r.stdout)
        except json.JSONDecodeError as e:
            return False, {}, f"json_decode: {e}"
        return True, data, "ok"
    except subprocess.TimeoutExpired:
        return False, {}, f"ffprobe_timeout_{timeout}s"
    except Exception as e:
        return False, {}, f"ffprobe_exc: {type(e).__name__}:{e}"


def compute_sha1(path: str | Path, chunk_size: int = 1024 * 1024) -> str | None:
    """★ Layer 3: SHA-1 file hash (对齐 KS184 _check_device_file_hash).

    读 1MB chunk, 600MB 文件 ~3s. 对齐 KS184 行为.
    """
    p = Path(path)
    if not p.exists():
        return None
    try:
        h = hashlib.sha1()
        with open(p, "rb") as f:
            while True:
                chunk = f.read(chunk_size)
                if not chunk:
                    break
                h.update(chunk)
        return h.hexdigest()
    except Exception as e:
        log.warning("[video_verifier] compute_sha1 failed %s: %s", p, e)
        return None


# ────────────────────────────────────────────────────────────────
# 主入口
# ────────────────────────────────────────────────────────────────

def verify_video(
    path: str | Path,
    min_size_bytes: int | None = None,
    min_duration_sec: float | None = None,
    require_video_stream: bool = True,
    require_audio_stream: bool = False,
    max_duration_sec: float | None = None,
    compute_hash: bool | None = None,
    timeout: float = 10.0,
) -> dict[str, Any]:
    """综合完整性校验.

    Args:
        path: 视频文件路径
        min_size_bytes: 最小字节数 (默认读 cfg video_verifier.min_size_bytes=102400)
        min_duration_sec: 最短时长 (默认 cfg .min_duration_sec=10)
        max_duration_sec: 最长时长 (默认 cfg .max_duration_sec=3600, 反防空白视频循环)
        require_video_stream: 是否要有视频流 (默认 True)
        require_audio_stream: 是否要有音频流 (默认 False, 有些有效视频可能静音)
        compute_hash: 是否算 sha1 (默认 cfg .compute_hash=false)
        timeout: ffprobe 超时

    Returns:
        {ok, size, duration, codec, width, height, bitrate, has_audio,
         hash_sha1, probe_json, errors, layers_passed}
    """
    try:
        from core.app_config import get as cfg_get
    except Exception:
        cfg_get = lambda k, d=None: d

    if min_size_bytes is None:
        min_size_bytes = int(cfg_get("video_verifier.min_size_bytes", 102400))
    if min_duration_sec is None:
        min_duration_sec = float(cfg_get("video_verifier.min_duration_sec", 10))
    if max_duration_sec is None:
        max_duration_sec = float(cfg_get("video_verifier.max_duration_sec", 3600))
    if compute_hash is None:
        compute_hash = bool(cfg_get("video_verifier.compute_hash", False))

    result: dict[str, Any] = {
        "ok": False, "path": str(path),
        "size": 0, "duration": 0.0,
        "codec": "", "width": 0, "height": 0,
        "bitrate": 0, "has_audio": False,
        "hash_sha1": None, "probe_json": {},
        "errors": [], "layers_passed": 0,
    }

    # Layer 1: size
    ok, reason, size = _check_size(path, min_bytes=min_size_bytes)
    result["size"] = size
    if not ok:
        result["errors"].append(f"L1:{reason}")
        return result
    result["layers_passed"] = 1

    # Layer 2: ffprobe
    ok, probe_data, reason = _ffprobe_json(path, timeout=timeout)
    result["probe_json"] = probe_data
    if not ok:
        result["errors"].append(f"L2:{reason}")
        return result
    result["layers_passed"] = 2

    # 提取 metadata
    fmt = probe_data.get("format") or {}
    streams = probe_data.get("streams") or []
    try:
        result["duration"] = float(fmt.get("duration") or 0)
    except Exception: pass
    try:
        result["bitrate"] = int(fmt.get("bit_rate") or 0)
    except Exception: pass

    v_stream = next((s for s in streams if s.get("codec_type") == "video"), None)
    a_stream = next((s for s in streams if s.get("codec_type") == "audio"), None)
    if v_stream:
        result["codec"] = v_stream.get("codec_name") or ""
        try:
            result["width"] = int(v_stream.get("width") or 0)
            result["height"] = int(v_stream.get("height") or 0)
        except Exception: pass
    result["has_audio"] = a_stream is not None

    # 规则检查
    if require_video_stream and not v_stream:
        result["errors"].append("L2:no_video_stream")
        return result
    if require_audio_stream and not a_stream:
        result["errors"].append("L2:no_audio_stream")
        # 不 return, 只记录
    if result["duration"] < min_duration_sec:
        result["errors"].append(f"L2:duration_too_short_{result['duration']:.1f}s")
        return result
    if result["duration"] > max_duration_sec:
        result["errors"].append(f"L2:duration_too_long_{result['duration']:.0f}s")
        # 不 return (长视频也可能有效, 只警告)

    # Layer 3 (optional): SHA-1
    if compute_hash:
        h = compute_sha1(path)
        result["hash_sha1"] = h
        if h:
            result["layers_passed"] = 3

    # 如有 L2 错但不是 fatal, 仍 ok=True 返 (require_audio_stream 警告)
    fatal_errs = [e for e in result["errors"] if not e.startswith("L2:no_audio_stream")
                   and "duration_too_long" not in e]
    result["ok"] = not fatal_errs
    return result


# ────────────────────────────────────────────────────────────────
# CLI
# ────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import sys
    sys.stdout.reconfigure(encoding="utf-8")
    if len(sys.argv) < 2:
        print("Usage: python -m core.video_verifier <video_path> [--hash]")
        sys.exit(1)
    path = sys.argv[1]
    compute_hash = "--hash" in sys.argv
    r = verify_video(path, compute_hash=compute_hash)
    print(json.dumps(
        {k: v for k, v in r.items() if k != "probe_json"},
        ensure_ascii=False, indent=2, default=str,
    ))
    if compute_hash:
        print(f"sha1: {r['hash_sha1']}")
