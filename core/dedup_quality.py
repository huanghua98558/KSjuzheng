# -*- coding: utf-8 -*-
"""去重质量回测 — 对比 processed 视频 vs 原视频的 pHash distance.

★ 2026-04-23 P2-1: 让系统**量化每次去重效果**, 不再盲跑.

核心指标:
  - frame_phash_hamming: 抽帧 pHash 海明距离, **>15 = pHash 过**, <8 = 大概率判重
  - byte_md5_match:      MD5 必须不同
  - encoder_changed:     元数据 encoder 字段必须改
  - duration_preserved:  原视频时长保留 (≥99%)

结果写入 dedup_quality_reports 表, Dashboard 可展示日均过率.

用法:
    from core.dedup_quality import report
    r = report(original_path, processed_path)
    # r = {score: 85, phash_avg: 18.3, ok: True, details: {...}}
"""
from __future__ import annotations

import hashlib
import json
import logging
import random
import sqlite3
import subprocess
from pathlib import Path
from typing import Any

log = logging.getLogger(__name__)


def _connect():
    from core.config import DB_PATH
    c = sqlite3.connect(DB_PATH, timeout=15)
    c.execute("PRAGMA busy_timeout=30000")
    c.row_factory = sqlite3.Row
    return c


def _ensure_table():
    with _connect() as c:
        c.execute("""CREATE TABLE IF NOT EXISTS dedup_quality_reports (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            original_path   TEXT NOT NULL,
            processed_path  TEXT NOT NULL,
            task_id         TEXT,
            recipe          TEXT,
            image_mode      TEXT,
            drama_name      TEXT,
            score           INTEGER,              -- 0-100 综合分
            phash_min       INTEGER,              -- 最小 hamming (最危险的那帧)
            phash_avg       REAL,                 -- 平均 hamming
            phash_max       INTEGER,
            frames_sampled  INTEGER,
            md5_original    TEXT,
            md5_processed   TEXT,
            duration_orig   REAL,
            duration_proc   REAL,
            encoder_orig    TEXT,
            encoder_proc    TEXT,
            passed          INTEGER,              -- 1=过 / 0=不过 (> 阈值为过)
            threshold_used  INTEGER,              -- 判定阈值 (默认 12)
            notes_json      TEXT,
            created_at      TEXT DEFAULT (datetime('now','localtime'))
        )""")
        c.commit()


def _file_md5(path: str) -> str:
    h = hashlib.md5()
    try:
        with open(path, "rb") as f:
            while True:
                chunk = f.read(1024 * 1024)
                if not chunk: break
                h.update(chunk)
        return h.hexdigest()
    except Exception:
        return ""


def _ffprobe(path: str) -> dict:
    """拿 duration + encoder 标签."""
    try:
        from core.processor import _get_ffmpeg_exe
        ffp = _get_ffmpeg_exe().replace("ffmpeg.exe", "ffprobe.exe")
    except Exception:
        ffp = r"C:\Program Files\kuaishou2\KS184.7z\KS184\tools\ffmpeg\bin\ffprobe.exe"
    try:
        r = subprocess.run(
            [ffp, "-v", "error", "-show_format", "-show_streams", "-of", "json", path],
            capture_output=True, text=True, encoding="utf-8", timeout=15,
        )
        data = json.loads(r.stdout)
        fmt = data.get("format", {}) or {}
        tags = fmt.get("tags", {}) or {}
        dur = float(fmt.get("duration") or 0)
        encoder = tags.get("encoder", "")
        return {"duration": dur, "encoder": encoder}
    except Exception as e:
        log.warning("[dedup_quality] ffprobe fail %s: %s", path, e)
        return {"duration": 0, "encoder": ""}


def _extract_frames(video_path: str, n: int = 5,
                      out_dir: str | None = None) -> list[str]:
    """从视频均匀抽 n 帧 (跳过前 2s + 后 2s 黑边).

    Returns: 帧 PNG 路径 list.
    """
    import tempfile
    from core.processor import _get_ffmpeg_exe

    vi = _ffprobe(video_path)
    dur = vi.get("duration") or 0
    if dur <= 4:
        return []
    start = 2.0
    end = dur - 2.0
    step = (end - start) / max(1, n)

    out_dir = out_dir or tempfile.mkdtemp(prefix="dedup_frames_")
    ffmpeg = _get_ffmpeg_exe()
    frames = []
    for i in range(n):
        t = start + step * i
        out = Path(out_dir) / f"f_{i:02d}.png"
        r = subprocess.run(
            [ffmpeg, "-y", "-loglevel", "error", "-ss", f"{t:.2f}",
             "-i", video_path, "-vframes", "1", "-q:v", "2", str(out)],
            capture_output=True, timeout=20,
        )
        if r.returncode == 0 and out.exists():
            frames.append(str(out))
    return frames


def _compute_phash_hamming(orig_frames: list[str], proc_frames: list[str]) -> dict:
    """比较两组帧的 pHash. 取最小 distance (最危险的帧)."""
    try:
        import imagehash
        from PIL import Image
    except ImportError:
        return {"ok": False, "error": "imagehash/PIL not installed"}

    if not orig_frames or not proc_frames:
        return {"ok": False, "error": "no frames"}

    n = min(len(orig_frames), len(proc_frames))
    distances = []
    for i in range(n):
        try:
            h1 = imagehash.phash(Image.open(orig_frames[i]))
            h2 = imagehash.phash(Image.open(proc_frames[i]))
            distances.append(h1 - h2)  # hamming distance
        except Exception as e:
            log.warning("[dedup_quality] phash frame %d fail: %s", i, e)
            continue

    if not distances:
        return {"ok": False, "error": "all frames failed"}

    return {
        "ok": True,
        "distances": distances,
        "min": min(distances),
        "max": max(distances),
        "avg": sum(distances) / len(distances),
        "n_frames": len(distances),
    }


def report(original_path: str, processed_path: str,
            task_id: str = "", recipe: str = "",
            image_mode: str = "", drama_name: str = "",
            n_frames: int = 5,
            threshold: int = 12) -> dict[str, Any]:
    """回测去重质量. 写 dedup_quality_reports 表 + 返结果.

    Args:
        original_path: 原视频 (下载后)
        processed_path: 处理后视频
        task_id / recipe / image_mode / drama_name: 元数据
        n_frames: 抽帧数
        threshold: pHash min 距离 ≥ threshold 视为"过 L3"

    Returns:
        {
            ok: bool, score: 0-100,
            phash_min, phash_avg, phash_max, frames_sampled,
            md5_changed, encoder_changed, duration_preserved,
            passed: bool, reasons: [...]
        }
    """
    _ensure_table()
    import tempfile

    orig_info = _ffprobe(original_path)
    proc_info = _ffprobe(processed_path)

    md5_orig = _file_md5(original_path)
    md5_proc = _file_md5(processed_path)

    # 抽帧 + pHash
    with tempfile.TemporaryDirectory() as tmp:
        orig_dir = Path(tmp) / "orig"
        proc_dir = Path(tmp) / "proc"
        orig_dir.mkdir(); proc_dir.mkdir()
        orig_frames = _extract_frames(original_path, n_frames, str(orig_dir))
        proc_frames = _extract_frames(processed_path, n_frames, str(proc_dir))
        ph = _compute_phash_hamming(orig_frames, proc_frames)

    # 综合分 (0-100)
    score = 0
    reasons = []
    md5_ok = md5_orig and md5_orig != md5_proc
    if md5_ok: score += 20
    else: reasons.append("md5_same")

    encoder_changed = orig_info.get("encoder") != proc_info.get("encoder")
    if encoder_changed: score += 10
    else: reasons.append("encoder_same")

    dur_o = orig_info.get("duration") or 0
    dur_p = proc_info.get("duration") or 0
    dur_ok = dur_o > 0 and abs(dur_p - dur_o) / dur_o < 0.02   # 2% 误差
    if dur_ok: score += 10
    else: reasons.append(f"duration_drift_{dur_p:.1f}_vs_{dur_o:.1f}")

    if ph.get("ok"):
        ph_min = ph["min"]
        ph_avg = ph["avg"]
        # 60 分全给 pHash (核心指标)
        # <8 危险, 8-12 边界, 12-20 安全, >20 完美
        if ph_min >= 20: ph_score = 60
        elif ph_min >= 12: ph_score = 45
        elif ph_min >= 8: ph_score = 25
        else: ph_score = 5
        score += ph_score
        if ph_min < threshold:
            reasons.append(f"phash_min_{ph_min}_below_threshold_{threshold}")
    else:
        ph_min = None
        ph_avg = None
        reasons.append(f"phash_failed_{ph.get('error')}")

    passed = md5_ok and encoder_changed and dur_ok and (
        ph.get("ok", False) and ph["min"] >= threshold
    )

    result = {
        "ok": True,
        "score": score,
        "passed": passed,
        "phash_min": ph_min,
        "phash_avg": round(ph_avg, 2) if ph_avg else None,
        "phash_max": ph.get("max"),
        "frames_sampled": ph.get("n_frames", 0),
        "md5_original": md5_orig,
        "md5_processed": md5_proc,
        "md5_changed": md5_ok,
        "encoder_changed": encoder_changed,
        "duration_original": dur_o,
        "duration_processed": dur_p,
        "duration_preserved": dur_ok,
        "reasons": reasons,
    }

    # 写 DB
    try:
        with _connect() as c:
            c.execute("""INSERT INTO dedup_quality_reports
                         (original_path, processed_path, task_id, recipe,
                          image_mode, drama_name, score,
                          phash_min, phash_avg, phash_max, frames_sampled,
                          md5_original, md5_processed,
                          duration_orig, duration_proc,
                          encoder_orig, encoder_proc,
                          passed, threshold_used, notes_json)
                         VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                      (original_path, processed_path, task_id, recipe,
                       image_mode, drama_name, score,
                       ph_min, ph_avg, ph.get("max"), ph.get("n_frames", 0),
                       md5_orig, md5_proc,
                       dur_o, dur_p,
                       orig_info.get("encoder"), proc_info.get("encoder"),
                       1 if passed else 0, threshold,
                       json.dumps({"reasons": reasons}, ensure_ascii=False)))
            c.commit()
    except Exception as e:
        log.warning("[dedup_quality] write DB fail: %s", e)

    return result


if __name__ == "__main__":
    import sys, argparse
    sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser()
    ap.add_argument("--orig", required=True)
    ap.add_argument("--proc", required=True)
    ap.add_argument("--recipe", default="")
    ap.add_argument("-n", type=int, default=5)
    args = ap.parse_args()
    r = report(args.orig, args.proc, recipe=args.recipe, n_frames=args.n)
    print(json.dumps(r, ensure_ascii=False, indent=2, default=str))
