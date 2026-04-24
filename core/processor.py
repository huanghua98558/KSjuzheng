# -*- coding: utf-8 -*-
"""视频处理器 MVP — 截取片段 + 抹 metadata + 轻量去重.

当前策略 (until Frida 抓完 10 种 KS184 mode):
  1. 截取 60-180s 之间的一段 (太短吸引不了人, 太长浪费带宽)
  2. 随机起点 (避开片头片尾重复片段)
  3. 抹 metadata (creation_time, title, comment 等 — 降查重嫌疑)
  4. 轻度像素噪点 (CRF 自控)
  5. 输出 ASCII-safe 文件名 (publisher.py 对齐 KS184 要求)

Recipe 概念 (为 Week 2 铺路):
  当前只实现 "mvp_trim_wipe_metadata" 1 个 recipe
  Week 2 Frida 抓到 KS184 argv 后, 新增 10 个 recipe 到 ffmpeg_recipes 表

使用:
    from core.processor import process_video
    r = process_video(
        input_path="D:/downloads/xxx.mp4",
        recipe="mvp_trim_wipe_metadata",
        target_duration_sec=90,
    )
    # → {ok: True, output_path: "...", recipe: "mvp_...", duration: 90.05}
"""
from __future__ import annotations

import logging
import os
import random
import re
import secrets
import subprocess

# ★ 2026-04-24 v6 Day 5-A: subprocess_helper 统一入口
# run_safe: 自动 log stderr (失败时 tail 前 600 字符)
# run_nvenc: 同上 + NVENC session 信号量 (RTX 3060 硬件上限 3)
from core.subprocess_helper import run_safe, run_nvenc, exists_and_nonempty
import time
from pathlib import Path
from typing import Any

from core.app_config import get as cfg_get

log = logging.getLogger(__name__)


def _cfg_bool(key: str, default: bool) -> bool:
    """app_config 里无 value_type 时 raw="false" 会被 bool() 判真. 统一在此 coerce."""
    v = cfg_get(key, None)
    if v is None:
        return default
    if isinstance(v, bool):
        return v
    if isinstance(v, str):
        return v.strip().lower() in ("true", "1", "yes", "on")
    return bool(v)


def _libx264_vbr_args(target_kbps: int | None = None) -> list[str]:
    """★ 2026-04-20 Bug 修复: libx264 用 VBR 模式有码率上限.

    Returns: ffmpeg args list, 直接 extend 到命令行.
    """
    if target_kbps is None:
        target_kbps = int(cfg_get("video.process.target_bitrate_kbps", 2500))
    max_mult = float(cfg_get("video.process.maxrate_multiplier", 2.0))
    buf_mult = float(cfg_get("video.process.bufsize_multiplier", 4.0))
    maxrate = int(target_kbps * max_mult)
    bufsize = int(target_kbps * buf_mult)
    return [
        "-b:v", f"{target_kbps}k",
        "-maxrate", f"{maxrate}k",
        "-bufsize", f"{bufsize}k",
    ]


def _should_use_gpu(recipe: str = "") -> bool:
    """根据 accel 总开关 + recipe 独立 use_gpu 开关决定.

    Priority:
      1. recipe 级 config `video.process.{recipe}.use_gpu` (优先)
      2. 总开关 `video.process.accel` (gpu/cpu)
    """
    if recipe:
        raw = cfg_get(f"video.process.{recipe}.use_gpu", None)
        if raw is not None:
            return str(raw).strip().lower() in ("true", "1", "yes", "on")
    accel = str(cfg_get("video.process.accel", "gpu") or "gpu").lower()
    return accel == "gpu"


def _video_encode_args(recipe: str = "", target_kbps: int | None = None,
                        preset: str | None = None,
                        extra_nvenc: list[str] | None = None) -> list[str]:
    """★ 2026-04-23 P0-1: 按 recipe use_gpu 开关输出 NVENC 或 libx264 VBR args.

    NVENC (GPU):
      - 吃 RTX 3060 VRAM, 不占主存 (300-400 MB vs 1-3 GB CPU)
      - 3-5x 速度
      - RTX 3060 硬件限制: 同时 3 个 NVENC session, 建议 per_task_type_publish ≤ 4

    libx264 (CPU):
      - 兼容好, 画质略优
      - 作为 GPU 故障 fallback

    Args:
        recipe: recipe 代码, 用于查 video.process.{recipe}.use_gpu
        target_kbps: 目标码率, 默认 2500
        preset: NVENC 用 p1-p7 (越小越快), libx264 用 ultrafast-veryslow. None = 默认
        extra_nvenc: 额外 NVENC 参数 (如 -profile:v high), libx264 分支忽略

    Returns:
        ffmpeg args list, 直接 extend 到命令行 (含 -c:v + 码率 + profile).
    """
    if target_kbps is None:
        target_kbps = int(cfg_get("video.process.target_bitrate_kbps", 2500) or 2500)
    max_mult = float(cfg_get("video.process.maxrate_multiplier", 2.0) or 2.0)
    buf_mult = float(cfg_get("video.process.bufsize_multiplier", 4.0) or 4.0)
    maxrate = int(target_kbps * max_mult)
    bufsize = int(target_kbps * buf_mult)

    if _should_use_gpu(recipe):
        args = [
            "-c:v", "h264_nvenc",
            "-preset", preset or "p4",           # p1-p7, p4 平衡
            "-rc", "vbr", "-cq", "25",           # NVENC VBR 质量 25 (对齐 CRF 23-25)
            "-b:v", f"{target_kbps}k",
            "-maxrate", f"{maxrate}k",
            "-bufsize", f"{bufsize}k",
            "-profile:v", "high",
            "-pix_fmt", "yuv420p",
        ]
        if extra_nvenc:
            args.extend(extra_nvenc)
        return args
    # CPU libx264 分支
    return [
        "-c:v", "libx264",
        "-preset", preset or "medium",
        "-b:v", f"{target_kbps}k",
        "-maxrate", f"{maxrate}k",
        "-bufsize", f"{bufsize}k",
        "-pix_fmt", "yuv420p",
    ]


def _get_ffmpeg_exe() -> str:
    # 优先 KS184 bin
    ks184 = r"C:\Program Files\kuaishou2\KS184.7z\KS184\tools\ffmpeg\bin\ffmpeg.exe"
    if os.path.isfile(ks184):
        return ks184
    try:
        from core.config import FFMPEG_EXE
        return FFMPEG_EXE
    except Exception:
        return "ffmpeg"


# ═════════════════════════════════════════════════════════════════
# 2026-04-20 ★ 通用调色链 + 音频 filter helper
# 对齐 Canonical v3 §5 "完整调色链" + 补 L4 音频层短板
# ═════════════════════════════════════════════════════════════════

def _build_color_chain(intensity: str = "medium") -> str:
    """组合调色 filter (对齐 Canonical v3 §5).

    KS184 实际用的调色不是单 eq, 而是组合链:
        hue=s=0 → colorbalance → eq(brightness/contrast/saturation/gamma) → curves=vintage

    本 helper 按强度分 3 档, AI planner 可选:

    Args:
        intensity: "light" / "medium" / "heavy"
            - light:   只 eq (轻度, 保原味)
            - medium:  eq + colorbalance (平衡, 默认)
            - heavy:   完整链 eq+colorbalance+hue+curves (深度洗色, 反 L3 pHash)

    Returns:
        filter 字符串片段, 用法: `f"...noise,{_build_color_chain()},..."`

    Config:
        video.process.color_chain.intensity = medium
    """
    cfg_intensity = cfg_get("video.process.color_chain.intensity", intensity)
    if cfg_intensity in ("light", "medium", "heavy"):
        intensity = cfg_intensity

    if intensity == "light":
        return "eq=brightness=0.02:contrast=1.05:saturation=1.05:gamma=1.02"

    if intensity == "heavy":
        # 全链: hue + colorbalance + eq + curves=vintage (L3 pHash 最大破坏)
        return (
            "hue=s=1,"                                           # saturation 微调
            "colorbalance=rs=0.05:gs=-0.05:bs=0.05,"              # RGB 平衡
            "eq=brightness=0.03:contrast=1.08:saturation=1.10:gamma=1.03,"
            "curves=preset=increase_contrast"                     # 胶片调色
        )

    # medium (默认): eq + colorbalance 平衡
    return (
        "colorbalance=rs=0.03:gs=-0.03:bs=0.03,"
        "eq=brightness=0.02:contrast=1.06:saturation=1.08:gamma=1.02"
    )


def _build_audio_filter(mode: str = "shift") -> str | None:
    """组合音频 filter (对抗 L4 音频指纹层).

    快手 2022 国家优秀奖专利: 音频指纹基于 Chromaprint-like 色度特征.
    破坏方法:
        - asetrate 采样率微移 (改音调, 破指纹)
        - atempo 变速复位 (保持听觉时长)
        - anoise (白噪掩盖, 可选)

    Args:
        mode: "none" / "shift" / "heavy"
            - none:   不处理 (返回 None)
            - shift:  asetrate ×1.005 + atempo /1.005 (微移 + 复位)
            - heavy:  shift + anoise 白噪 (-40dB 不可察)

    Returns:
        audio filter 字符串 (用法: -af "<result>"), 或 None 表示不加

    Config:
        video.process.audio_filter.enabled = true
        video.process.audio_filter.mode    = shift
        video.process.audio_filter.pitch_ratio = 1.005  (0.995-1.015 范围)
    """
    if not _cfg_bool("video.process.audio_filter.enabled", False):
        return None

    cfg_mode = cfg_get("video.process.audio_filter.mode", mode)
    if cfg_mode not in ("none", "shift", "heavy"):
        cfg_mode = mode

    if cfg_mode == "none":
        return None

    # pitch_ratio: 1.005 = 微移 0.5%, 不可察
    # 范围 [0.995, 1.015] (clamp 防止失真)
    pitch = float(cfg_get("video.process.audio_filter.pitch_ratio", 1.005))
    pitch = max(0.995, min(1.015, pitch))

    # asetrate 改采样率 (假设源 44100), atempo 用倒数复位
    shift = (
        f"asetrate=44100*{pitch:.4f},"
        f"aresample=44100,"
        f"atempo={1.0/pitch:.4f}"
    )

    if cfg_mode == "heavy":
        # 再叠弱白噪 (-40dB, 人耳听不出但指纹测到)
        # 注: aevalsrc 需要 lavfi input, 这里用简化方案 — volume 抖动
        return shift + ",volume='1.0+0.001*sin(2*PI*t*7)':eval=frame"

    # shift (默认)
    return shift


def _add_audio_filter_args(base_audio_args: list[str]) -> list[str]:
    """如果 audio filter 启用, 把 -af 插入 audio args 序列.

    典型用法:
        args = ["-c:a", "aac", "-b:a", "128k"]
        args = _add_audio_filter_args(args)   # 可能加 -af
    """
    af = _build_audio_filter()
    if not af:
        return base_audio_args
    return base_audio_args + ["-af", af]


def _get_zhizun_ffmpeg() -> str:
    """KS184 至尊/荣耀/不闪 三种算法专用 ffmpeg.

    按内存反编 docstring (PathFinder._find_ffmpeg_for_algorithm):
        " 查找FFmpeg路径(用于三种算法) … 'tools/ffmpeg/bin4/cfg64.exe' "

    我们把 cfg64.exe 已经从 KS184 目录抢救到 tools/ks184_recovered/.
    它实际上是 ffmpeg 8.0.1-full_build (NVENC/AMF/Vulkan/libplacebo) 的 UPX 包装.
    """
    candidates = [
        r"D:\ks_automation\tools\ks184_recovered\tools\ffmpeg\bin4\cfg64.exe",
        r"C:\Program Files\kuaishou2\KS184.7z\KS184\tools\ffmpeg\bin4\cfg64.exe",
        # 旧路径 (留作 fallback)
        r"C:\Program Files\kuaishou2\KS184.7z\KS184\tools\ffmpeg\zhizun\ffmpeg.exe",
    ]
    for p in candidates:
        if os.path.isfile(p):
            return p
    return _get_ffmpeg_exe()


def _probe_duration(path: str) -> float | None:
    """拿视频总时长 (秒)."""
    ffmpeg = _get_ffmpeg_exe()
    try:
        # ★ Day 5-A: run_safe — 失败时自动 log stderr tail
        rc, _stdout, stderr = run_safe(
            [ffmpeg, "-i", path, "-t", "0.1", "-f", "null", "-"],
            timeout=10, tag="processor/probe_duration",
        )
        m = re.search(r"Duration:\s*(\d+):(\d+):(\d+\.\d+)", stderr or "")
        if not m:
            return None
        h, mm, ss = int(m.group(1)), int(m.group(2)), float(m.group(3))
        return h * 3600 + mm * 60 + ss
    except Exception:
        return None


# ─────────────────────────────────────────────────────────────────
# Recipes (按 name 分发)
# ─────────────────────────────────────────────────────────────────

def _recipe_mvp_trim_wipe_metadata(
    src: str, dst: str, target_dur: float, start_sec: float,
) -> list[str]:
    """Base recipe: 截取 + 抹 metadata. 不重编码 (-c copy), 速度极快."""
    return [
        _get_ffmpeg_exe(), "-y", "-loglevel", "error",
        "-ss", f"{start_sec:.2f}",
        "-i", src,
        "-t", f"{target_dur:.2f}",
        "-c", "copy",
        "-map_metadata", "-1",                # 抹 global metadata
        "-metadata:s:v:0", "rotate=",         # 抹视频流 metadata
        "-metadata", "creation_time=",
        "-metadata", "title=",
        "-metadata", "comment=",
        "-metadata", "description=",
        "-movflags", "+faststart+use_metadata_tags",
        "-fflags", "+genpts",
        dst,
    ]


def _recipe_light_noise_recode(
    src: str, dst: str, target_dur: float, start_sec: float, crf: int = 23,
) -> list[str]:
    """中等强度: 截取 + 重编码 + 轻噪点 (降低查重指纹).

    CRF 23 = 平衡 (小=高质量, 大=更多压缩).
    用 GPU (h264_nvenc) 如果配置允许, 否则 CPU.

    ★ 2026-04-20: 加 light 调色链 + 可选音频 filter
    """
    # 噪点 + 轻调色链 (canonical §5)
    color_chain = _build_color_chain("light")
    vf = f"noise=c0s=5:c0f=t+u:allf=t+u,{color_chain}"

    audio_args = _add_audio_filter_args(["-c:a", "aac", "-b:a", "128k"])

    return [
        _get_ffmpeg_exe(), "-y", "-loglevel", "error",
        "-ss", f"{start_sec:.2f}",
        "-i", src,
        "-t", f"{target_dur:.2f}",
        "-vf", vf,
        *_video_encode_args(recipe="light_noise"),
        *audio_args,
        "-map_metadata", "-1",
        "-metadata", "creation_time=",
        "-metadata", "title=",
        "-movflags", "+faststart",
        dst,
    ]


# ─────────────────────────────────────────────────────────────────
# zhizun (至尊) recipe — 噪点 + 调色 + 九宫格图案
# ─────────────────────────────────────────────────────────────────
# 来源 (memory dump 反编 + 磁盘抢救 + cfg64.exe PoC 复刻成功):
#   docstring: ShortDramaManager.process_video_with_zhizun
#              " 至尊算法视频处理(噪点+调色+图案) "
#   evidence:  KS182\…\mode6_temp\temp_material_*\grid_image.png  (3240×5760)
#                                                  \images\art_001..009.png  (1080×1920×9)
#   PoC:       tools/zhizun_poc.py  → md5(input) ≠ md5(output) 验证成功

_ZHIZUN_GRID_W = 1080
_ZHIZUN_GRID_H = 1920


# ═════════════════════════════════════════════════════════════════
# R1-4 (2026-04-20): 统一 pattern 生成入口 → 调 qitian.py 6 种风格
# 对齐 KS184 UI "图片模式" 6 选 1
# ═════════════════════════════════════════════════════════════════

def _generate_pattern_by_mode(
    out_path: str,
    image_mode: str | None = None,
    width: int = _ZHIZUN_GRID_W,
    height: int = _ZHIZUN_GRID_H,
    opacity: float = 0.30,
    video_path: str | None = None,
    drama_name: str = "",
    account_name: str = "",
) -> dict:
    """统一 pattern 生成入口 — AI 决策选 image_mode, 此函数分发到 qitian.

    Args:
        out_path: PNG 输出路径
        image_mode: 6 选 1 (qitian_art / gradient_random / random_shapes /
                            mosaic_rotate / frame_transform / random_chars)
                    None = 读 app_config `video.process.image_mode`
        width/height: 目标尺寸 (至尊 mode5=716×954, 麒麟 mode6=1080×1920)
        opacity: pattern 透明度 (后续 overlay 时用)
        video_path: mosaic_rotate / frame_transform 需要真视频抽帧
        drama_name/account_name: 纯 pattern 不需要, 但 qitian 可接受

    Returns:
        {ok, path, mode, width, height, size_kb, elapsed_sec, error?}
    """
    from core.qitian import generate, AVAILABLE_STYLES

    # 从 config 读默认 image_mode
    if image_mode is None:
        image_mode = cfg_get("video.process.image_mode", "qitian_art")
    if image_mode not in AVAILABLE_STYLES:
        log.warning("[pattern] unknown image_mode=%s, fallback qitian_art",
                     image_mode)
        image_mode = "qitian_art"

    # 调 qitian.generate (它已处理 6 种风格)
    r = generate(
        style=image_mode,
        drama_name=drama_name or "",
        account_name=account_name or "",
        output_path=out_path,
        video_path=video_path,
        width=width,
        height=height,
    )
    if r.get("ok"):
        log.info("[pattern] ✅ %s → %s (%.1fKB)",
                 image_mode, out_path, r.get("size_kb", 0))
    else:
        log.error("[pattern] ❌ %s failed: %s", image_mode, r.get("error"))
    return r


def _generate_zhizun_grid_image(out_path: str, opacity: float = 0.30) -> str:
    """生成 KS182 风格的九宫格艺术覆盖图 (单图 1080×1920, 含装饰).

    模拟 KS182 art_001..009.png 的视觉特征:
      - 半透明几何形状 (三角/方/圆) 重叠
      - 渐变背景 (深色基调)
      - 散点光斑 (bokeh)
      - alpha = opacity (默认 0.30)

    注: KS182 真实 grid_image 是 3×3 拼接成 3240×5760, 我们这里直接生成 1080×1920
    单图供 ffmpeg overlay (避免 scale 浪费). 风格随机 → 每次 dedup 指纹不同.
    """
    try:
        from PIL import Image, ImageDraw, ImageFilter
    except ImportError:
        raise RuntimeError("Pillow 未安装 -> pip install Pillow")
    import math

    w, h = _ZHIZUN_GRID_W, _ZHIZUN_GRID_H
    a = int(255 * opacity)

    # 1. 渐变背景 (随机两色 → 垂直渐变)
    img = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    pix = img.load()
    c1 = tuple(random.randint(40, 110) for _ in range(3))   # 深色 1
    c2 = tuple(random.randint(40, 110) for _ in range(3))   # 深色 2
    for y in range(h):
        t = y / h
        r = int(c1[0] * (1 - t) + c2[0] * t)
        g = int(c1[1] * (1 - t) + c2[1] * t)
        b = int(c1[2] * (1 - t) + c2[2] * t)
        for x in range(w):
            pix[x, y] = (r, g, b, a // 2)         # 半透明背景

    # 2. 几何形状 (8-15 个随机三角/方/圆)
    draw = ImageDraw.Draw(img, "RGBA")
    for _ in range(random.randint(8, 15)):
        shape = random.choice(["triangle", "rect", "circle"])
        col = (
            random.randint(80, 230),
            random.randint(80, 230),
            random.randint(80, 230),
            random.randint(60, 180),
        )
        if shape == "circle":
            cx, cy = random.randint(0, w), random.randint(0, h)
            r = random.randint(40, 250)
            draw.ellipse((cx - r, cy - r, cx + r, cy + r), fill=col)
        elif shape == "rect":
            x0, y0 = random.randint(0, w), random.randint(0, h)
            x1, y1 = x0 + random.randint(80, 350), y0 + random.randint(80, 350)
            draw.rectangle((x0, y0, x1, y1), fill=col)
        else:  # triangle
            pts = [(random.randint(0, w), random.randint(0, h)) for _ in range(3)]
            draw.polygon(pts, fill=col)

    # 3. 散点光斑 (20-40 个小圆)
    for _ in range(random.randint(20, 40)):
        cx, cy = random.randint(0, w), random.randint(0, h)
        r = random.randint(3, 18)
        col = (
            random.randint(150, 255),
            random.randint(150, 255),
            random.randint(150, 255),
            random.randint(80, 200),
        )
        draw.ellipse((cx - r, cy - r, cx + r, cy + r), fill=col)

    # 4. 整图轻微高斯模糊 → 边缘软化
    img = img.filter(ImageFilter.GaussianBlur(radius=1.5))

    img.save(out_path, "PNG")
    return out_path


def _recipe_zhizun_overlay(
    src: str, dst: str, target_dur: float, start_sec: float,
    opacity: float = 0.30, crf: int = 18,
) -> list[str]:
    """至尊 overlay 变体 (简单版) — 对齐 KS184 #19/#24 Frida 抓.

    这是 KS184 的默认 zhizun 快速变体, 单 pass ffmpeg:
      [0:v] noise + eq 调色 [bg]
      [1:v] format=rgba, scale=720:1280 [overlay]
      [bg][overlay] overlay=0:0:format=auto:shortest=1 [outv]

    对齐 argv:
      -c:v libx264 -preset medium -crf 18
      -pix_fmt yuv420p -profile:v high -level 4.1
      -movflags +faststart
    """
    # R2-3: 走 pattern dispatcher — image_mode 从 config 读
    grid_png = str(Path(dst).with_suffix("").with_name(Path(dst).stem + "_grid.png"))
    image_mode = cfg_get("video.process.image_mode", "qitian_art")
    _generate_pattern_by_mode(
        out_path=grid_png, image_mode=image_mode,
        width=_ZHIZUN_GRID_W, height=_ZHIZUN_GRID_H,
        opacity=opacity, video_path=src,
    )

    # KS184 #19 用的是 1280×720 (横向 overlay), 但我们视频常是 720×1280 竖屏, 保持 720×1280
    # ★ 2026-04-20: 调色链升级 (对齐 canonical §5 hue+colorbalance+eq+curves)
    color_chain = _build_color_chain("medium")
    fc = (
        "[0:v]"
        "noise=alls=14:allf=t+u,"
        f"{color_chain}"
        "[bg];"
        f"[1:v]format=rgba,scale={_ZHIZUN_GRID_W}:{_ZHIZUN_GRID_H},"
        f"colorchannelmixer=aa={opacity}[overlay];"
        "[bg][overlay]overlay=0:0:format=auto:shortest=1[outv]"
    )

    # ★ 2026-04-23 P0-1: 通过 _video_encode_args 统一 GPU/CPU 分支
    # zhizun.use_gpu=true → NVENC, 否则 libx264
    audio_args = _add_audio_filter_args(
        ["-c:a", "aac", "-b:a", "128k", "-ar", "44100"]
    )
    return [
        _get_ffmpeg_exe(), "-y", "-loglevel", "warning",
        "-ss", f"{start_sec:.2f}",
        "-i", src,
        "-loop", "1", "-i", grid_png,
        "-t", f"{target_dur:.2f}",
        "-filter_complex", fc,
        "-map", "[outv]", "-map", "0:a?",
        "-threads", "4",
        *_video_encode_args(recipe="zhizun"),
        *audio_args,
        "-map_metadata", "-1",
        "-metadata", "creation_time=",
        "-metadata", "title=",
        "-metadata", "comment=",
        "-movflags", "+faststart",
        dst,
    ]


# ─────────────────────────────────────────────────────────────────
# wuxianliandui (无限连队) — libx264 + force_key_frames (KS184 #14)
# ─────────────────────────────────────────────────────────────────

def _recipe_wuxianliandui(
    src: str, dst: str, target_dur: float, start_sec: float,
    crf: int | None = None, force_keyframe_n: int = 20,
    preset: str | None = None,
) -> list[str]:
    """无限怼队 (多步防检测) — 对齐 KS184 Canonical v3 §2.2.

    UI 极简 (用户截图确认): 无质量/图片/融图/GPU 参数, 所有内部硬编码.

    2026-04-20 补齐:
      1. ★ 加 `-x264-params keyint=65535:ref=16:bframes=16:b-adapt=2` (canonical 明确)
      2. ★ 加 Step 2 concat (原视频前 30 帧 + pattern zoompan 拼接)
      3. 融合版单命令 (避免临时文件管理)

    路径分支:
      use_concat = True (默认, 对齐 canonical §2.2):
        单 ffmpeg_complex: concat=n=2 (src 前 30 帧 + pattern zoompan) + x264 激进参数
      use_concat = False (fallback, 原单 step 实现):
        只做 Step 1 cach1 = 轻量 GOP 破坏

    Config:
      video.process.wuxianliandui.use_concat   = true   (默认走 canonical §2.2 增强版)
      video.process.wuxianliandui.crf          = 20
      video.process.wuxianliandui.preset       = faster
      video.process.wuxianliandui.image_mode   = random_shapes
        (UI 不暴露 — KS184 内部, 但我们保留 config 让运维可改)
    """
    if crf is None:
        crf = int(cfg_get("video.process.wuxianliandui.crf", 20))
    if preset is None:
        preset = cfg_get("video.process.wuxianliandui.preset", "faster")

    use_concat = _cfg_bool("video.process.wuxianliandui.use_concat", True)

    # 对齐 KS184 canonical §2.2 激进 x264 params
    x264_params = "keyint=65535:ref=16:bframes=16:b-adapt=2"

    # ── 分支 1: fallback 单 step (原实现, 加 x264-params) ──
    if not use_concat:
        return [
            _get_ffmpeg_exe(), "-y", "-loglevel", "warning",
            "-ss", f"{start_sec:.2f}",
            "-i", src,
            "-t", f"{target_dur:.2f}",
            "-c:v", "libx264", "-preset", str(preset),
            "-profile:v", "high", "-level:v", "4",
            "-x264-params", x264_params,             # ★ 补齐
            "-force_key_frames", f"expr:eq(n,{force_keyframe_n})",
            "-pix_fmt", "yuv420p",
            "-vf", "fps=30",
            *_libx264_vbr_args(),
            "-c:a", "aac",
            "-map_metadata", "-1",
            "-metadata", "creation_time=",
            "-metadata", "title=",
            "-movflags", "+faststart",
            dst,
        ]

    # ── 分支 2: 默认走 Step 2 concat (canonical §2.2 对齐) ──
    # KS184 内部用 random_shapes 做 pattern (UI 不让选, 硬编)
    image_mode = cfg_get("video.process.wuxianliandui.image_mode", "random_shapes")
    grid_png = str(Path(dst).with_suffix("").with_name(Path(dst).stem + "_grid.png"))
    _generate_pattern_by_mode(
        out_path=grid_png, image_mode=image_mode,
        width=720, height=1280,
        opacity=0.30, video_path=src,
    )

    # concat filter_complex: 原视频前 30 帧 + pattern zoompan
    # 总时长 = target_dur, src_portion = target_dur - 2s (留 2s 给 pattern)
    pattern_dur = 2.0
    src_portion = max(1.0, target_dur - pattern_dur)
    fc = (
        # [0:v] fps 30 + 前 src_portion 秒 (包含前 30 帧硬切)
        f"[0:v]fps=30,trim=0:{src_portion:.2f},setpts=PTS-STARTPTS,"
        "scale=720:1280:force_original_aspect_ratio=increase,"
        "crop=720:1280,setsar=1[first];"
        # [1:v] pattern 做 zoompan 2s, 缓慢放大
        f"[1:v]scale=720:1280:force_original_aspect_ratio=increase,"
        f"crop=720:1280,"
        f"zoompan=z='min(zoom+0.001,1.3)':d={int(pattern_dur * 30)}:"
        f"x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':s=720x1280,"
        f"fps=30,setsar=1[zoom];"
        # 拼接
        "[first][zoom]concat=n=2:v=1:a=0[v]"
    )

    audio_args = _add_audio_filter_args(["-c:a", "aac", "-b:a", "128k"])

    return [
        _get_ffmpeg_exe(), "-y", "-loglevel", "warning",
        "-ss", f"{start_sec:.2f}",
        "-i", src,
        "-loop", "1", "-i", grid_png,
        "-t", f"{target_dur:.2f}",
        "-filter_complex", fc,
        "-map", "[v]", "-map", "0:a?",
        "-threads", "4",
        "-c:v", "libx264", "-preset", str(preset),
        "-profile:v", "high", "-level:v", "4",
        "-x264-params", x264_params,                 # ★ canonical §2.2
        "-force_key_frames", f"expr:eq(n,{force_keyframe_n})",
        "-pix_fmt", "yuv420p",
        *_libx264_vbr_args(),
        *audio_args,
        "-map_metadata", "-1",
        "-metadata", "creation_time=",
        "-metadata", "title=",
        "-movflags", "+faststart",
        dst,
    ]


# ─────────────────────────────────────────────────────────────────
# yemao (夜猫) — 4×3 马赛克拼帧
# ─────────────────────────────────────────────────────────────────

def _recipe_yemao(
    src: str, dst: str, target_dur: float, start_sec: float,
    crf: int | None = None,
) -> list[str]:
    """夜猫 (yemao) — 12 帧随机 crop + rotate, split+xstack 3×4 + 可选融图.

    对齐 KS184 Canonical v3 §2.7 + UI "夜猫" 项:
      - 核心: KS184 用 split=12 + xstack (非 tile=4x3!)
      - 每格 240×320, 3 列 × 4 行 = 720×1280 总输出
      - UI 支持: 图片模式 6 选 1 + 融图 + 视频帧透明度 50% + GPU/CPU

    数据源: scan2 yemao_full + scan1 crop_filter/rotate_filter

    Config (对齐 DEVELOPMENT_REFERENCE §6.2):
      video.process.yemao.crf             = 22
      video.process.yemao.image_mode      = random_shapes (6 选 1)
      video.process.yemao.blend_enabled   = true  (UI 勾选融图)
      video.process.yemao.blend_opacity   = 0.50  (UI 视频帧透明度)
      video.process.yemao.use_gpu         = true

    两路分支 (2026-04-20 补齐):
      blend_enabled=False → 纯 12 格马赛克 (原实现)
      blend_enabled=True  → 12 格 xstack → 叠 pattern image_mode (新)
    """
    if crf is None:
        crf = int(cfg_get("video.process.yemao.crf", 22))

    # ★ 2026-04-20: 补齐融图 + image_mode 支持 (对齐 canonical UI §0 表格)
    # UI 截图确认: 夜猫默认**融图勾选**, 视频帧透明度 50%, 图片模式**齐天艺术**
    blend_enabled = _cfg_bool("video.process.yemao.blend_enabled",
                                _cfg_bool("video.process.blend_enabled", True))
    blend_opacity = float(cfg_get("video.process.yemao.blend_opacity",
                                    cfg_get("video.process.blend_alpha", 0.50)))
    image_mode = cfg_get("video.process.yemao.image_mode",
                          cfg_get("video.process.image_mode", "qitian_art"))
    image_opacity = float(cfg_get("video.process.image_opacity", 0.30))

    cell_w, cell_h = 240, 320
    out_w, out_h = cell_w * 3, cell_h * 4  # 720×1280

    # 12 格 layout
    layout_parts = []
    for row in range(4):
        for col in range(3):
            layout_parts.append(f"{col * cell_w}_{row * cell_h}")
    layout = "|".join(layout_parts)

    # 每格随机帧号 + 随机 rotate 角度
    frame_picks = [(i + random.uniform(0.1, 0.9)) / 12.0 for i in range(12)]
    angles = [random.uniform(-0.12, 0.12) for _ in range(12)]

    # 构 12 条 split branch
    split_inputs = "".join(f"[s{i}]" for i in range(12))
    branches = []
    for i in range(12):
        t_pick = frame_picks[i] * target_dur
        branches.append(
            f"[s{i}]"
            f"trim=start={t_pick:.3f}:duration=0.5,setpts=PTS-STARTPTS,"
            f"scale=iw*2:ih*2,crop={cell_w}:{cell_h},"
            f"rotate={angles[i]:.4f}:fillcolor=black:ow={cell_w}:oh={cell_h},"
            f"loop=loop=-1:size=1:start=0,trim=duration={target_dur:.2f},setpts=PTS-STARTPTS"
            f"[c{i}];"
        )
    xstack_input = "".join(f"[c{i}]" for i in range(12))
    color_chain = _build_color_chain("light")  # yemao 用浅调色保马赛克原样

    # ── 分支 1: 纯马赛克 (blend_enabled=False, 原实现) ──
    if not blend_enabled:
        fc = (
            f"[0:v]split=12{split_inputs};"
            + "".join(branches)
            + f"{xstack_input}"
            f"xstack=inputs=12:layout={layout}[grid];"
            f"[grid]noise=alls=6:allf=t,{color_chain}"
            "[v]"
        )
        audio_args = _add_audio_filter_args(["-c:a", "aac", "-b:a", "128k"])
        return [
            _get_ffmpeg_exe(), "-y", "-loglevel", "warning",
            "-ss", f"{start_sec:.2f}",
            "-i", src,
            "-t", f"{target_dur:.2f}",
            "-filter_complex", fc,
            "-map", "[v]", "-map", "0:a?",
            "-threads", "4",
            *_video_encode_args(recipe="yemao"),
            *audio_args,
            "-map_metadata", "-1",
            "-movflags", "+faststart",
            dst,
        ]

    # ── 分支 2: 12 格 + image_mode 融图 (2026-04-20 新增, 对齐 yemao UI UI 融图勾选) ──
    # 生成 pattern PNG
    grid_png = str(Path(dst).with_suffix("").with_name(Path(dst).stem + "_grid.png"))
    _generate_pattern_by_mode(
        out_path=grid_png, image_mode=image_mode,
        width=out_w, height=out_h,
        opacity=image_opacity, video_path=src,
    )

    fc = (
        f"[0:v]split=12{split_inputs};"
        + "".join(branches)
        + f"{xstack_input}"
        f"xstack=inputs=12:layout={layout}[grid_raw];"
        # xstack 结果叠 pattern 图 blend
        f"[grid_raw]noise=alls=6:allf=t,{color_chain}[grid];"
        f"[1:v]format=rgba,scale={out_w}:{out_h},"
        f"colorchannelmixer=aa={image_opacity}[pattern];"
        f"[grid][pattern]blend=all_expr='A*(1-{blend_opacity})+B*{blend_opacity}':shortest=1[v]"
    )
    audio_args = _add_audio_filter_args(["-c:a", "aac", "-b:a", "128k"])
    return [
        _get_ffmpeg_exe(), "-y", "-loglevel", "warning",
        "-ss", f"{start_sec:.2f}",
        "-i", src,
        "-loop", "1", "-i", grid_png,
        "-t", f"{target_dur:.2f}",
        "-filter_complex", fc,
        "-map", "[v]", "-map", "0:a?",
        "-threads", "4",
        *_video_encode_args(recipe="yemao"),
        *audio_args,
        "-map_metadata", "-1",
        "-movflags", "+faststart",
        dst,
    ]


# ─────────────────────────────────────────────────────────────────
# bushen (不闪) — cfg64.exe 独占, 噪点+调色 (无 overlay)
# ─────────────────────────────────────────────────────────────────

def _recipe_bushen(
    src: str, dst: str, target_dur: float, start_sec: float,
    crf: int | None = None,
) -> list[str]:
    """不闪 — 噪点+调色 (可选九宫格 overlay, 对齐 KS184 UI).

    对齐 DEVELOPMENT_REFERENCE §6.2:
      video.process.bushen.crf            = 20
      video.process.bushen.image_mode     = random_shapes (默认, UI 6 选 1)
      video.process.bushen.blend_enabled  = true (UI 勾选)
      video.process.bushen.blend_opacity  = 0.50 (UI 视频帧透明度)
      video.process.bushen.use_gpu        = false (cfg64 强制 CPU)
      video.process.bushen.ffmpeg_path    = tools/ffmpeg/bin4/cfg64.exe

    KS184 内部: cfg64.exe = ffmpeg 8.0.1 UPX 包装 (强制 CPU, 不支持 NVENC).
    "比至尊更轻" 是因为默认 blend 关, 但 UI 允许开 → 支持两路.
    """
    if crf is None:
        crf = int(cfg_get("video.process.bushen.crf", 20))
    # UI 截图确认 (2026-04-20): 不闪算法 UI 暴露图片模式 + 融图勾选,
    # 默认图片模式 = 齐天艺术 (qitian_art), 融图勾选, 视频帧透明度 50%
    image_mode = cfg_get("video.process.bushen.image_mode",
                          cfg_get("video.process.image_mode", "qitian_art"))
    blend_enabled = _cfg_bool("video.process.bushen.blend_enabled", True)
    blend_opacity = float(cfg_get("video.process.bushen.blend_opacity", 0.50))
    image_opacity = float(cfg_get("video.process.image_opacity", 0.30))

    # ffmpeg 路径: 优先 bushen 独占 (cfg64.exe), fallback 通用
    ffmpeg = _get_bushen_ffmpeg()

    # 不闪 filter 核心: 噪点 + 调色 (对比至尊: alls=12 vs 14, 轻)
    # ★ 2026-04-20: 调色链升级 (对齐 canonical §5 hue+colorbalance+eq+curves)
    color_chain = _build_color_chain("medium")
    noise_eq = f"noise=alls=12:allf=t+u,{color_chain}"

    # 分支 1: UI 勾选"融图" → 走和至尊类似的 overlay/blend 路径
    # 分支 2: UI 未勾选 → 纯 vf 噪点+调色 (极轻 cpu 模式)
    if blend_enabled:
        # Pattern 生成
        grid_png = str(Path(dst).with_suffix("").with_name(Path(dst).stem + "_grid.png"))
        _generate_pattern_by_mode(
            out_path=grid_png, image_mode=image_mode,
            width=_ZHIZUN_GRID_W, height=_ZHIZUN_GRID_H,
            opacity=image_opacity, video_path=src,
        )

        fc = (
            f"[0:v]{noise_eq}[bg];"
            f"[1:v]format=rgba,scale={_ZHIZUN_GRID_W}:{_ZHIZUN_GRID_H},"
            f"colorchannelmixer=aa={image_opacity}[overlay];"
            f"[bg][overlay]blend=all_expr='A*(1-{blend_opacity})+B*{blend_opacity}':shortest=1[outv]"
        )

        audio_args = _add_audio_filter_args(["-c:a", "aac", "-b:a", "128k"])
        return [
            ffmpeg, "-y", "-loglevel", "warning",
            "-ss", f"{start_sec:.2f}",
            "-i", src,
            "-loop", "1", "-i", grid_png,
            "-t", f"{target_dur:.2f}",
            "-filter_complex", fc,
            "-map", "[outv]", "-map", "0:a?",
            *_video_encode_args(recipe="bushen"),
            *audio_args,
            "-map_metadata", "-1",
            "-metadata", "creation_time=",
            "-metadata", "title=",
            "-movflags", "+faststart",
            dst,
        ]

    # 纯噪点模式 (不闪经典)
    # 注: 纯模式默认 -c:a copy (L4 层零破坏), 若 audio_filter.enabled=true 改 aac + filter
    af = _build_audio_filter()
    if af:
        # 有音频 filter 要求 → 必须重编码 audio
        audio_args = ["-c:a", "aac", "-b:a", "128k", "-af", af]
    else:
        audio_args = ["-c:a", "copy"]
    return [
        ffmpeg, "-y", "-loglevel", "warning",
        "-ss", f"{start_sec:.2f}",
        "-i", src,
        "-t", f"{target_dur:.2f}",
        "-vf", noise_eq,
        *_video_encode_args(recipe="bushen"),
        *audio_args,
        "-map_metadata", "-1",
        "-metadata", "creation_time=",
        "-metadata", "title=",
        "-movflags", "+faststart",
        dst,
    ]


def _get_bushen_ffmpeg() -> str:
    """不闪独占 ffmpeg binary (cfg64.exe).

    Config: video.process.bushen.ffmpeg_path = tools/ffmpeg/bin4/cfg64.exe
    """
    # 先查 config
    cfg_path = cfg_get("video.process.bushen.ffmpeg_path",
                        "tools/ffmpeg/bin4/cfg64.exe")
    if cfg_path and not os.path.isabs(cfg_path):
        # 相对路径转 KS184 安装目录
        ks184_root = r"C:\Program Files\kuaishou2\KS184.7z\KS184"
        abs_in_ks184 = os.path.join(ks184_root, cfg_path.replace("/", "\\"))
        if os.path.isfile(abs_in_ks184):
            return abs_in_ks184

    # 其他候选
    for p in [
        r"D:\ks_automation\tools\ks184_recovered\tools\ffmpeg\bin4\cfg64.exe",
        r"C:\Program Files\kuaishou2\KS184.7z\KS184\tools\ffmpeg\bin4\cfg64.exe",
    ]:
        if os.path.isfile(p):
            return p

    log.warning("[bushen] cfg64.exe not found, using fallback ffmpeg")
    return _get_ffmpeg_exe()


# ─────────────────────────────────────────────────────────────────
# touming_9gong (透明九宫) — 抽 9 帧拼九宫格 → blend opacity=0.3
# ─────────────────────────────────────────────────────────────────

def _recipe_touming_9gong(
    src: str, dst: str, target_dur: float, start_sec: float,
    opacity: float | None = None, crf: int = 22,
    animations: str | list[str] | None = None,
) -> list[str]:
    """透明叠加 (透明九宫 / mode3_overlay) — 抽 9 帧拼九宫格 → 动画 + blend overlay.

    对齐 KS184 UI 截图 "透明叠加" + Canonical v3 §2.1:
      - UI "透明度 30%"  → opacity (blend 权重, 推荐 20-50)
      - UI "动画效果 7 选 N" → animations (多选)
      - 输出容器 matroska 伪装成 .mp4 (encoder=kuaishou_mode3_processor)

    UI 截图确认 (2026-04-20):
      - 默认透明度 30%
      - 动画 7 个 checkbox 全未勾选 (= 用 config 默认 / random 回退)
      - **透明叠加独占**: 不使用 image_mode / 融图 / GPU / 质量参数

    2026-04-20 补齐:
      ★ 多动画支持 — UI 可选 N 个 (≥2 时时段均分): anim[0] 段 + anim[1] 段 ... concat 拼

    流程:
      animations=1: 单动画 (原单 pass)
      animations=N (≥2): 把 target_dur 均分 N 段, 每段用不同动画, concat 拼

    Config:
      video.process.overlay.opacity                          = 0.30
      video.process.mode3.overlay_anim_{zoom_in,...}         = true/false (7 个 bool)
      video.process.animations                                = "*" 或 "zoom_in,pan_right"
    """
    from core.pattern_animator import (
        get_animation_filter, resolve_animations_from_config,
        AVAILABLE_ANIMATIONS,
    )

    if opacity is None:
        opacity = float(cfg_get("video.process.overlay.opacity", 0.30))

    # 读动画: None = 读 config; str = 单动画; list = 多动画
    if animations is None:
        animations = resolve_animations_from_config()
    if isinstance(animations, str):
        animations = [animations]
    if not animations:
        animations = ["zoom_in"]
    # 过滤 valid
    animations = [a for a in animations if a in AVAILABLE_ANIMATIONS or a == "pulse"]
    if not animations:
        animations = ["zoom_in"]

    target_w, target_h = 720, 1280
    n_anims = len(animations)

    # ── 分支 1: 单动画 (原实现) ──
    if n_anims == 1:
        anim = animations[0]
        anim_filter = get_animation_filter(anim, target_w, target_h,
                                            duration=target_dur, fps=30)
        fc = (
            f"[0:v]scale={target_w}:{target_h}:force_original_aspect_ratio=increase,"
            f"crop={target_w}:{target_h},split=2[base][src];"
            f"[src]fps=9/{target_dur:.2f},"
            f"scale={target_w//3}:{target_h//3}:force_original_aspect_ratio=increase,"
            f"crop={target_w//3}:{target_h//3},"
            "tile=3x3:margin=0:padding=0,"
            f"{anim_filter}[grid];"
            "[base][grid]"
            f"blend=all_expr='A*(1-{opacity})+B*{opacity}'"
            "[v]"
        )
    else:
        # ── 分支 2: 多动画时段均分 + concat 拼 (2026-04-20 新增) ──
        # 每个动画独占 target_dur / n_anims 段, 每段单独生成 9 宫格 + 动画,
        # 然后 concat 拼起来, 最后和原视频 blend
        seg_dur = target_dur / n_anims
        # 起始分支
        parts = [
            f"[0:v]scale={target_w}:{target_h}:force_original_aspect_ratio=increase,"
            f"crop={target_w}:{target_h},split={n_anims + 1}"
            + "".join(f"[base]" if i == 0 else f"[src{i}]" for i in range(n_anims + 1))
            + ";"
        ]
        # 每个动画的 branch
        grid_inputs = []
        for i, anim in enumerate(animations):
            ani_filter = get_animation_filter(anim, target_w, target_h,
                                                duration=seg_dur, fps=30)
            parts.append(
                f"[src{i+1}]trim=duration={seg_dur:.2f},setpts=PTS-STARTPTS,"
                f"fps=9/{seg_dur:.2f},"
                f"scale={target_w//3}:{target_h//3}:force_original_aspect_ratio=increase,"
                f"crop={target_w//3}:{target_h//3},"
                f"tile=3x3:margin=0:padding=0,"
                f"{ani_filter}[g{i}];"
            )
            grid_inputs.append(f"[g{i}]")
        # concat 所有 grid 段
        parts.append(
            "".join(grid_inputs) + f"concat=n={n_anims}:v=1:a=0[grid_all];"
        )
        # 和 base blend
        parts.append(
            f"[base][grid_all]blend=all_expr='A*(1-{opacity})+B*{opacity}'[v]"
        )
        fc = "".join(parts)
        log.info("[touming] 多动画 n=%d: %s (每段 %.1fs)", n_anims, animations, seg_dur)

    audio_args = _add_audio_filter_args(["-c:a", "aac", "-b:a", "128k"])

    # 对齐 KS184 Canonical v3 §6: matroska 伪装 (容器 mkv, 扩展名 .mp4)
    return [
        _get_ffmpeg_exe(), "-y", "-loglevel", "warning",
        "-ss", f"{start_sec:.2f}",
        "-i", src,
        "-t", f"{target_dur:.2f}",
        "-filter_complex", fc,
        "-map", "[v]", "-map", "0:a?",
        "-threads", "4",
        *_video_encode_args(recipe="touming"),
        *audio_args,
        "-map_metadata", "-1",
        "-metadata", "encoder=kuaishou_mode3_processor",  # ← matroska 伪装
        "-f", "matroska",                                  # ← 容器强制 mkv
        "-write_crc32", "0",                               # ← 不写 CRC
        dst,                                                # 扩展名保 .mp4
    ]


# ─────────────────────────────────────────────────────────────────
# rongyu (荣耀) — 增强质量 (KS184 内部名 rongyu, 非 rongyao!)
# ─────────────────────────────────────────────────────────────────
# 数据源: scan3 config_keys 全部 rongyu_* prefix 命中, 无一处 rongyao_*
# Canonical v3 §2.5 明确: KS184 的 config 键全是 rongyu_blend_enabled /
# rongyu_crf / rongyu_use_gpu / rongyu_image_mode / rongyu_ffmpeg_path(s)

def _recipe_rongyu(
    src: str, dst: str, target_dur: float, start_sec: float,
    crf: int = 20,
) -> list[str]:
    """荣耀 (rongyu) — 增强质量 + 图片模式叠加 (对齐 KS184 Canonical v3 §2.5).

    UI 截图确认: 质量 20, 图片模式=齐天艺术, 融图=勾选, 视频帧透明度=50%, GPU=默认.

    2026-04-20 对齐 canonical §2.5 重写:
      核心 filter 变更: 从"纯 blend overlay" → **concat=n=2 (原视频前 30 帧 + pattern zoompan)**
      canonical filter:
        [0:v]trim=start_frame=0:end_frame=30,setpts,scale=720:1280[first];
        [1:v]scale,crop,zoompan=z='min(zoom+0.001,1.5)':d=70[zoom];
        [first][zoom]concat=n=2:v=1:a=0

    两路 (按 blend_enabled):
      True  (默认, UI 勾选): Step 2 concat=n=2 + 前段叠图
      False:                 只 Step 1 轻处理 (unsharp + eq, 无 concat)

    激进 x264-params (对齐 canonical):
      keyint=65535:ref=16:bframes=16:b-adapt=2
    """
    # R2 对齐: 走 pattern dispatcher
    image_mode = cfg_get("video.process.rongyu.image_mode",
                          cfg_get("video.process.image_mode", "qitian_art"))
    image_opacity = float(cfg_get("video.process.image_opacity", 0.30))
    blend_alpha = float(cfg_get("video.process.rongyu.blend_opacity",
                                  cfg_get("video.process.blend_alpha", 0.50)))
    blend_enabled = _cfg_bool("video.process.rongyu.blend_enabled",
                                _cfg_bool("video.process.blend_enabled", True))

    color_chain = _build_color_chain("medium")

    # ── 分支 1: 不融图 → 只 unsharp+eq 增强 (轻路径) ──
    if not blend_enabled:
        fc = (
            "[0:v]"
            "noise=alls=8:allf=t,"
            f"{color_chain},"
            "unsharp=5:5:0.8:5:5:0.4"
            "[v]"
        )
        audio_args = _add_audio_filter_args(["-c:a", "aac", "-b:a", "192k"])
        return [
            _get_ffmpeg_exe(), "-y", "-loglevel", "warning",
            "-ss", f"{start_sec:.2f}",
            "-i", src,
            "-t", f"{target_dur:.2f}",
            "-filter_complex", fc,
            "-map", "[v]", "-map", "0:a?",
            "-c:v", "libx264", "-preset", "faster", *_libx264_vbr_args(),
            "-x264-params", "keyint=65535:ref=16:bframes=16:b-adapt=2",
            "-pix_fmt", "yuv420p", "-profile:v", "high",
            *audio_args,
            "-map_metadata", "-1",
            "-metadata", "creation_time=",
            "-metadata", "title=",
            "-movflags", "+faststart",
            dst,
        ]

    # ── 分支 2: 默认融图 → concat=n=2 (canonical §2.5 核心) ──
    # 生成 pattern PNG
    grid_png = str(Path(dst).with_suffix("").with_name(Path(dst).stem + "_grid.png"))
    _generate_pattern_by_mode(
        out_path=grid_png, image_mode=image_mode,
        width=_ZHIZUN_GRID_W, height=_ZHIZUN_GRID_H,
        opacity=image_opacity, video_path=src,
    )

    # canonical §2.5: concat=n=2 (前 30 帧 + pattern zoompan)
    # d=70 对齐 canonical (70 帧 ≈ 2.3s @ 30fps)
    # 配合 unsharp 保画面锐度 (荣耀 = 增强质量)
    fc = (
        # [0:v] 前 30 帧 + 调色 + unsharp
        "[0:v]trim=start_frame=0:end_frame=30,setpts=PTS-STARTPTS,"
        f"scale=720:1280:flags=lanczos,setsar=1,"
        f"noise=alls=8:allf=t,{color_chain},"
        "unsharp=5:5:0.8:5:5:0.4"
        "[first];"
        # [1:v] pattern 做 zoompan (d=70 canonical 参数)
        "[1:v]scale=720:1280:force_original_aspect_ratio=increase,"
        "crop=720:1280,"
        "zoompan=z='min(zoom+0.001,1.5)':d=70:"
        "x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':s=720x1280,"
        "fps=30,setsar=1"
        # 调色 + unsharp 一致保质量
        f",{color_chain},unsharp=5:5:0.5:5:5:0.3"
        # pattern 叠透明度 (blend_alpha 权重应用为 fade in/out)
        f",format=rgba,colorchannelmixer=aa={blend_alpha}[zoom];"
        # concat
        "[first][zoom]concat=n=2:v=1:a=0[v]"
    )

    audio_args = _add_audio_filter_args(["-c:a", "aac", "-b:a", "192k"])
    return [
        _get_ffmpeg_exe(), "-y", "-loglevel", "warning",
        "-ss", f"{start_sec:.2f}",
        "-i", src,
        "-loop", "1", "-i", grid_png,
        "-t", f"{target_dur:.2f}",
        "-filter_complex", fc,
        "-map", "[v]", "-map", "0:a?",
        "-c:v", "libx264", "-preset", "faster", *_libx264_vbr_args(),
        "-x264-params", "keyint=65535:ref=16:bframes=16:b-adapt=2",
        "-pix_fmt", "yuv420p", "-profile:v", "high",
        *audio_args,
        "-map_metadata", "-1",
        "-metadata", "creation_time=",
        "-metadata", "title=",
        "-movflags", "+faststart",
        dst,
    ]


# Backward-compat alias: 旧代码调用 _recipe_rongyao 仍然工作
_recipe_rongyao = _recipe_rongyu


RECIPES = {
    "mvp_trim_wipe_metadata":   _recipe_mvp_trim_wipe_metadata,
    "light_noise_recode":        _recipe_light_noise_recode,
    # ---- KS184 对齐 (Canonical v3: dump 扫实测值) ----
    "zhizun":                    _recipe_zhizun_overlay,    # 别名 → overlay 变体 (快速默认)
    "zhizun_overlay":            _recipe_zhizun_overlay,    # 显式 overlay 版 (对齐 #19/#24)
    "wuxianliandui":             _recipe_wuxianliandui,     # 对齐 #14 (libx264+force_key_frames)
    "yemao":                     _recipe_yemao,             # split=12+xstack 12 格 240×320
    "bushen":                    _recipe_bushen,            # cfg64.exe 独占
    "touming_9gong":             _recipe_touming_9gong,     # 9 帧九宫格 blend + matroska 伪装
    "rongyu":                    _recipe_rongyu,            # 荣耀 (KS184 内部名 rongyu, 非 rongyao)
    "rongyao":                   _recipe_rongyu,            # ← 向后兼容别名, 指向 rongyu
    # kirin_mode6 / zhizun_mode5_pipeline 在 RECIPES 之外 (多步 pipeline)
}


def process_video(
    input_path: str,
    output_dir: str | None = None,
    recipe: str | None = None,
    target_duration_sec: int | None = None,
    min_source_duration_sec: int = 30,
    image_mode: str | None = None,
    drama_name: str = "",
    account_name: str = "",
    recipe_config: dict | None = None,
) -> dict[str, Any]:
    """处理视频, 输出新文件.

    Args:
        input_path: 输入视频
        output_dir: 输出目录, None = 同输入目录
        recipe: recipe 名. None = 读 video.process.mode
        target_duration_sec: 目标时长. None = 随机 60-180
        min_source_duration_sec: 输入必须 >= N 秒, 否则拒
        image_mode: pattern 素材风格 (6 选 1). None = 读 `video.process.image_mode`
        drama_name / account_name: 水印用
        recipe_config: 额外参数 dict, 例如 {"blend_alpha": 0.4, "crf": 22}
                        会覆盖默认值 (AI planner 可传)

    Returns:
        {ok: bool, output_path?, recipe, duration, error?}
    """
    if not os.path.isfile(input_path):
        return {"ok": False, "error": f"input not exists: {input_path}", "recipe": recipe}

    # 取源视频时长
    src_dur = _probe_duration(input_path)
    if src_dur is None:
        return {"ok": False, "error": "probe source duration failed",
                "recipe": recipe}
    if src_dur < min_source_duration_sec:
        return {"ok": False,
                "error": f"source too short: {src_dur:.1f}s < {min_source_duration_sec}s",
                "recipe": recipe, "source_duration": src_dur}

    # ★ 修正 (2026-04-20): 短剧默认保留完整时长, 不再自动裁剪
    # 短剧本就是完整剧, 快手发布应保留全部 (之前 MVP 的 60-180s 假设错了)
    #
    # 语义:
    #   target_duration_sec = None → 保留原时长 (默认, 对齐 KS184 UI)
    #   target_duration_sec = 0    → alias of None
    #   target_duration_sec = N    → 明确裁剪到 N 秒 (小视频场景专用)
    #
    # Config 覆盖: video.process.target_duration_sec (int or 0 = 保留完整)
    if target_duration_sec is None:
        cfg_dur = cfg_get("video.process.target_duration_sec", 0)
        try:
            cfg_dur = int(cfg_dur)
        except (ValueError, TypeError):
            cfg_dur = 0
        target_duration_sec = cfg_dur

    if not target_duration_sec or target_duration_sec <= 0:
        # 保留原时长 (留 0.5s margin 避免 ffmpeg 尾部边界)
        target = max(1, int(src_dur) - 1)
        start = 0
        log.info("[processor] preserve full duration: src=%.1fs target=%ds",
                 src_dur, target)
    else:
        target = min(target_duration_sec, int(src_dur) - 2)
        # 随机起点 (避开头尾)
        max_start = max(0, int(src_dur) - target - 2)
        start = random.randint(0, max_start) if max_start > 0 else 0
        log.info("[processor] explicit trim: src=%.1fs target=%ds start=%ds",
                 src_dur, target, start)

    # Recipe
    recipe_name = recipe or cfg_get("video.process.mode", "mvp_trim_wipe_metadata")

    # ★ 多步 pipeline (不走 RECIPES 单命令分发) → 直接调对应 pipeline 函数
    # 把 target_duration_sec 传给 pipeline (None = 保留全时长, 有值 = 显式截短)
    pipeline_target_dur = target_duration_sec if target_duration_sec and target_duration_sec > 0 else None
    if recipe_name == "kirin_mode6":
        rc = recipe_config or {}
        return process_kirin_mode6(
            input_path, output_dir=output_dir,
            blend_alpha=rc.get("blend_alpha"),
            aux_duration=rc.get("aux_duration", 10),
            image_mode=image_mode,
            drama_name=drama_name,
            account_name=account_name,
            target_duration_sec=pipeline_target_dur,
        )
    if recipe_name == "zhizun_mode5_pipeline":
        rc = recipe_config or {}
        return process_zhizun_mode5_pipeline(
            input_path, output_dir=output_dir,
            blend_alpha=rc.get("blend_alpha"),
            image_mode=image_mode,
            drama_name=drama_name,
            account_name=account_name,
            target_duration_sec=pipeline_target_dur,
        )

    # Fallback: 若配置的 recipe 还没实现, 用 MVP
    if recipe_name not in RECIPES:
        log.warning("[processor] recipe %s 未实现, 用 mvp_trim_wipe_metadata", recipe_name)
        recipe_name = "mvp_trim_wipe_metadata"
    recipe_fn = RECIPES[recipe_name]

    # Output
    out_dir = Path(output_dir) if output_dir else Path(input_path).parent
    out_dir.mkdir(parents=True, exist_ok=True)
    stamp = time.strftime("%Y%m%d_%H%M%S")
    rand = secrets.token_hex(4)
    # ASCII-safe file name (publisher.py 严格要求)
    out_path = out_dir / f"video_{rand}_{stamp}_processed.mp4"

    # R4-CFG: per-recipe CRF (UI "质量") 从 config 读, fallback shared quality_crf
    _recipe_crf_key_map = {
        "bushen":         "video.process.bushen.crf",
        "yemao":          "video.process.yemao.crf",
        "zhizun":         "video.process.zhizun.crf",
        "zhizun_overlay": "video.process.zhizun.crf",
        "rongyu":         "video.process.rongyu.crf",
        "rongyao":        "video.process.rongyu.crf",
        "wuxianliandui":  "video.process.wuxianliandui.crf",
        "touming_9gong":  "video.process.mode3.crf",
    }
    _shared_crf = int(cfg_get("video.process.quality_crf", 20))
    _per_recipe_crf_key = _recipe_crf_key_map.get(recipe_name)
    _recipe_crf = int(cfg_get(_per_recipe_crf_key, _shared_crf)) \
                   if _per_recipe_crf_key else _shared_crf
    # AI planner 覆盖 > per-recipe config > shared
    if recipe_config and "crf" in recipe_config:
        _recipe_crf = int(recipe_config["crf"])

    # 试新签名 (含 crf). 不支持 crf kwarg 的 recipe 自动 fallback.
    try:
        cmd = recipe_fn(input_path, str(out_path), target, start, crf=_recipe_crf)
    except TypeError:
        cmd = recipe_fn(input_path, str(out_path), target, start)
    log.info("[processor] recipe=%s start=%ds dur=%ds src_dur=%.1fs crf=%d",
             recipe_name, start, target, src_dur, _recipe_crf)

    t0 = time.time()
    try:
        # ★ Day 5-A: run_nvenc — 对非 NVENC 命令透明, 对 NVENC 命令加信号量
        # recipe_fn 返回的 cmd 可能含 h264_nvenc 或纯 libx264 — 都能安全过
        rc, _stdout, _stderr = run_nvenc(cmd, timeout=300,
                                           tag=f"processor/recipe={recipe_name}")
        if rc == -1:   # run_safe/run_nvenc 的超时约定
            try: out_path.unlink(missing_ok=True)
            except Exception: pass
            return {"ok": False, "error": "ffmpeg_timeout", "recipe": recipe_name}
        if rc != 0:
            err = (_stderr or "").strip()[:300]
            log.error("[processor] ffmpeg failed: %s", err)
            try: out_path.unlink(missing_ok=True)
            except Exception: pass
            return {"ok": False, "error": f"ffmpeg_err: {err}",
                    "recipe": recipe_name}
    except Exception as e:
        log.exception("[processor] 异常 recipe=%s: %s", recipe_name, e)
        try: out_path.unlink(missing_ok=True)
        except Exception: pass
        return {"ok": False, "error": f"exception: {str(e)[:200]}",
                "recipe": recipe_name}

    elapsed = time.time() - t0
    if not out_path.exists() or out_path.stat().st_size < 1024:
        return {"ok": False, "error": "output_missing_or_tiny",
                "recipe": recipe_name}

    size_mb = out_path.stat().st_size / 1024 / 1024
    log.info("[processor] ✅ %s (%.1fs -> %.2fMB) in %.1fs",
             out_path.name, target, size_mb, elapsed)
    return {
        "ok": True,
        "output_path": str(out_path),
        "recipe": recipe_name,
        "duration": target,
        "start_sec": start,
        "source_duration": src_dur,
        "elapsed_sec": round(elapsed, 1),
        "output_size_mb": round(size_mb, 2),
    }


def list_recipes() -> list[str]:
    return sorted(RECIPES.keys())


# ═════════════════════════════════════════════════════════════════
# 2026-04-20 ★ Auto scale34 prefix — E2E 发现的关键缺口
# ─────────────────────────────────────────────────────────────────
# KS184 真实 Frida trace (2026-04-19 抓的) 确认:
#   mode5 的 interleave input 0 是 "_34.mp4" (scale34 产物, 716×954)
#   mode6 的 interleave input 0 是原视频 (720×1280)
#
# 我们 E2E pHash 测试发现:
#   mode5 直接跑原视频 → 20/20 帧 hamming=0 → L3 判重
#   mode5 + scale34 前置 → 19/20 帧 hamming>10 → L3 过率 95%
#
# 所以对 mode5 强制前置 scale34 (对齐 KS184).
# 对 mode6 可选前置 (KS184 原版没, 但加了能显著增强 L3 — 默认开).
# ═════════════════════════════════════════════════════════════════

def _get_video_dim(path: str) -> tuple[int, int] | None:
    """ffprobe 抓视频 WxH. None = 失败."""
    ffmpeg = _get_ffmpeg_exe()
    try:
        # ★ Day 5-A: run_safe
        _rc, _out, stderr = run_safe(
            [ffmpeg, "-i", path, "-t", "0.1", "-f", "null", "-"],
            timeout=10, tag="processor/probe_dim",
        )
        stderr = stderr or ""
        m = re.search(r"Stream.*Video.*\s(\d+)x(\d+)", stderr)
        if m:
            return int(m.group(1)), int(m.group(2))
    except Exception as e:
        log.debug("[probe_dim] %s failed: %s", path, e)
    return None


def _auto_scale34_if_needed(
    input_path: str,
    work_root: Path,
    drama_name: str = "",
    account_name: str = "",
    recipe_name: str = "",
) -> tuple[str, dict]:
    """如果 input 不是 716×954, 自动跑 scale34 前置 (对齐 KS184 mode5 pipeline).

    如果已经是 716×954 → 跳过 (认为 caller 已前置过).
    如果跑失败 → 回退原 input (降级) + step_info 标 ok=False.

    Args:
        input_path: 原视频路径
        work_root: 临时产物目录 (scale34 输出放这里, cleanup 自动清)
        drama_name/account_name: scale34 的 drawtext + sin 水印参数
        recipe_name: 仅用于日志

    Returns:
        (effective_input_path, step_info_dict)
    """
    dim = _get_video_dim(input_path)
    step_info = {"step": "0_auto_scale34", "input_dim": dim}

    if dim and dim == (716, 954):
        step_info["ok"] = True
        step_info["skipped"] = True
        step_info["reason"] = "already_716x954"
        log.info("[%s] input 已是 716×954 scale34 产物, 跳过前置", recipe_name)
        return input_path, step_info

    # 跑 scale34 前置
    from core.scale34 import process_scale34_video

    scale34_out = str(work_root / f"scale34_prefix_{Path(input_path).stem}_34.mp4")
    t0 = time.time()
    r = process_scale34_video(
        input_path=input_path,
        drama_name=drama_name or "短剧",
        account_name=account_name or "",
        output_path=scale34_out,
    )
    elapsed = time.time() - t0
    step_info["elapsed"] = round(elapsed, 2)

    if r.get("ok"):
        step_info["ok"] = True
        step_info["output"] = scale34_out
        step_info["output_size_mb"] = r.get("output_size_mb", 0)
        step_info["output_dim"] = (r.get("output_w"), r.get("output_h"))
        log.info("[%s] ✅ scale34 前置: %s → %dx%d (%.1fs)",
                 recipe_name,
                 f"{dim[0]}x{dim[1]}" if dim else "?",
                 r.get("output_w", 0), r.get("output_h", 0),
                 elapsed)
        return scale34_out, step_info
    else:
        step_info["ok"] = False
        step_info["error"] = r.get("error", "")[:200]
        log.warning("[%s] ❌ scale34 前置失败, 用原 input (降级): %s",
                    recipe_name, step_info["error"])
        return input_path, step_info


# ═════════════════════════════════════════════════════════════════
# KS184 Mode6 麒麟 — 7 步完整 pipeline (Frida canonical 2026-04-19 抓取)
# 不是单 ffmpeg, 而是流水线. 调用: process_kirin_mode6()
# ═════════════════════════════════════════════════════════════════

def _cleanup_temp_dir(temp_dir: Path, keep_patterns: list[str] | None = None) -> dict:
    """R4-1: 清理临时目录 (mode6_temp / temp_zhizun 等).

    对齐 KS184 UI "任务结束后删临时文件" 开关.
    Config: `video.process.cleanup_temp` = True/False
    Config: `video.process.cleanup_keep_cover` = True/False (保留 cover*.png)

    Args:
        temp_dir: 要清的目录
        keep_patterns: 不删的文件名 glob 模式 list (默认从 config 读)

    Returns:
        {deleted: int, kept: int, error?}
    """
    if not cfg_get("video.process.cleanup_temp", True):
        return {"deleted": 0, "kept": 0, "skipped": "cleanup_temp=false"}

    if not temp_dir.exists():
        return {"deleted": 0, "kept": 0, "reason": "dir_not_exists"}

    if keep_patterns is None:
        keep_patterns = []
        if cfg_get("video.process.cleanup_keep_cover", True):
            keep_patterns.extend(["cover*.png", "cover*.jpg", "*_watermarked.*"])

    import fnmatch
    deleted, kept = 0, 0
    try:
        for item in temp_dir.rglob("*"):
            if item.is_file():
                # 判断是否保留
                keep = any(fnmatch.fnmatch(item.name, pat) for pat in keep_patterns)
                if keep:
                    kept += 1
                    continue
                try:
                    item.unlink()
                    deleted += 1
                except Exception:
                    pass
        # 删空目录
        for item in sorted(temp_dir.rglob("*"), key=lambda p: -len(str(p))):
            if item.is_dir():
                try:
                    item.rmdir()
                except OSError:
                    pass
        try:
            temp_dir.rmdir()
        except OSError:
            pass
        log.info("[cleanup] %s: deleted=%d kept=%d", temp_dir.name, deleted, kept)
        return {"deleted": deleted, "kept": kept}
    except Exception as e:
        return {"deleted": deleted, "kept": kept, "error": str(e)[:200]}


def _find_bin_xin_ffmpeg() -> str:
    """KS184 专用 ffmpeg bin-xin/ffmpeg.exe (Mode6 流程用的)."""
    for p in [
        r"C:\Program Files\kuaishou2\KS184.7z\KS184\tools\ffmpeg\bin-xin\ffmpeg.exe",
        r"D:\ks_automation\tools\m3u8dl\ffmpeg.exe",
    ]:
        if os.path.isfile(p):
            return p
    return _get_ffmpeg_exe()


def _mode6_step2_extract_frame(src: str, ss: float, out_png: str) -> bool:
    """Step 2: 从视频 ss 秒处抽 1 帧 PNG."""
    cmd = [_find_bin_xin_ffmpeg(), "-y", "-ss", f"{ss:.3f}", "-i", src,
           "-vframes", "1", "-q:v", "1", out_png]
    # ★ Day 5-A: run_safe, 失败 stderr 可见
    rc, _o, _e = run_safe(cmd, timeout=15, tag="mode6/step2_extract_frame")
    return rc == 0 and exists_and_nonempty(out_png)


def _mode6_step3_blend_png(grid_png: str, frame_png: str,
                            out_png: str, alpha: float = 0.50) -> bool:
    """Step 3: BLEND 九宫格 + 抽帧融合 → _blend_result.png.

    filter_complex: [1]scale=3240:5760[video];[0][video]blend=all_expr='A*(1-α)+B*α'
    """
    filt = f"[1]scale=3240:5760[video];[0][video]blend=all_expr='A*(1-{alpha})+B*{alpha}'"
    cmd = [_find_bin_xin_ffmpeg(), "-y", "-i", grid_png, "-i", frame_png,
           "-filter_complex", filt, out_png]
    # ★ Day 5-A
    rc, _o, _e = run_safe(cmd, timeout=30, tag="mode6/step3_blend_png")
    return rc == 0 and exists_and_nonempty(out_png)


def _mode6_step4_zoompan_aux(grid_png: str, out_mp4: str, duration: int = 10) -> bool:
    """Step 4: 九宫格图 → 10s zoompan 视频 (auxiliary_material.mp4).
    ★ 2026-04-24 v6: run_nvenc 共享 semaphore, 自动 log stderr."""
    vf = ("scale=1080:1920:force_original_aspect_ratio=increase,crop=1080:1920,"
          "zoompan=z='(1+0.001*on)':d=30:x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':s=1080x1920,"
          "fps=30,setpts=PTS-STARTPTS")
    cmd = [_find_bin_xin_ffmpeg(), "-y", "-loop", "1", "-i", grid_png,
           "-vf", vf, "-t", str(duration),
           "-c:v", "h264_nvenc", "-preset", "p4", "-crf", "20",
           "-profile:v", "high", "-pix_fmt", "yuv420p", "-an", out_mp4]
    from core.subprocess_helper import run_nvenc, exists_and_nonempty
    rc, _, _ = run_nvenc(cmd, timeout=60, tag="mode6/step4_zoompan")
    return rc == 0 and exists_and_nonempty(out_mp4, min_bytes=1024)


def _mode6_step5_concat(src: str, aux: str, out_mp4: str, total_dur: float) -> bool:
    """Step 5: 原视频前 30 帧 + aux loop concat → temp_concat.mp4.
    ★ 2026-04-24 v6: run_nvenc + stderr 暴露."""
    filt = (
        "[0:v]trim=start_frame=0:end_frame=30,setpts=PTS-STARTPTS,"
        "scale=720:1280:flags=lanczos,setsar=1,format=yuv420p[first];"
        "[1:v]setpts=PTS-STARTPTS,fps=30,"
        "scale=720:1280:flags=lanczos,setsar=1,format=yuv420p[second];"
        "[first][second]concat=n=2:v=1:a=0"
    )
    cmd = [_find_bin_xin_ffmpeg(), "-y", "-hwaccel", "cuda", "-i", src,
           "-hwaccel", "cuda", "-stream_loop", "-1", "-i", aux,
           "-filter_complex", filt, "-an", "-t", str(int(total_dur)),
           "-c:v", "h264_nvenc", "-preset", "p4", "-crf", "20",
           "-profile:v", "high", out_mp4]
    from core.subprocess_helper import run_nvenc, exists_and_nonempty
    rc, _, _ = run_nvenc(cmd, timeout=900, tag="mode6/step5_concat")
    return rc == 0 and exists_and_nonempty(out_mp4, min_bytes=10240)


def _mode6_step6_interleave(src: str, mid: str, out_mp4: str,
                              total_dur: float) -> bool:
    """Step 6: ★★★ INTERLEAVE — 逐帧交织 + NVENC p1 VBR + matroska 伪装.

    这是 KS184 Mode6 去重核心. filter_complex 路径:
        [0:v]→v0; [1:v][v0]scale2ref→[v1s][v0r];
        [v1s]fps=30,tpad[v1d]; [v0r]fps=30[v0f];
        [v0f][v1d]interleave,select≠0,format=yuv420p[v]

    ★ 2026-04-24 v6 C1 修复:
      1. stderr 通过 run_nvenc 自动 log (原 capture_output 吞了错误)
      2. NVENC semaphore 限流 (RTX 3060 最多 3 session, 防第 4 个撞墙)
      3. 失败详情会写 log.error, 便于调参 / fallback 触发
    """
    filt = (
        "[0:v]scale=720:1280,setsar=1:1,setpts=PTS-STARTPTS[v0];"
        "[1:v][v0]scale2ref[v1s][v0r];"
        "[v1s]fps=30,tpad=start=0:stop_mode=clone[v1d];"
        "[v0r]fps=30[v0f];"
        "[v0f][v1d]interleave,select='not(eq(n,0))',format=yuv420p[v]"
    )
    cmd = [_find_bin_xin_ffmpeg(), "-y", "-hwaccel", "cuda", "-i", src,
           "-hwaccel", "cuda", "-i", mid,
           "-filter_complex", filt,
           "-map", "[v]", "-map", "0:a", "-t", str(int(total_dur)),
           "-map_metadata", "-1",
           "-c:v", "h264_nvenc", "-preset", "p1", "-rc", "vbr", "-cq", "20",
           "-b:v", "3000k", "-maxrate", "4000k", "-bufsize", "8000k",
           "-profile:v", "high", "-bf", "0",
           "-c:a", "copy",
           # ★ KS184 黑魔法: matroska 伪装 mp4, -write_crc32 0 不写 CRC
           "-f", "matroska", "-write_crc32", "0",
           out_mp4]
    from core.subprocess_helper import run_nvenc, exists_and_nonempty
    rc, _, _ = run_nvenc(cmd, timeout=1800, tag="mode6/step6_interleave")
    return rc == 0 and exists_and_nonempty(out_mp4, min_bytes=1024)


def _mode6_step7_cover(processed: str, cover: str) -> bool:
    """Step 7: 抽第一帧作封面."""
    cmd = [_find_bin_xin_ffmpeg(), "-y", "-i", processed,
           "-vframes", "1", "-q:v", "2", cover]
    # ★ Day 5-A
    rc, _o, _e = run_safe(cmd, timeout=15, tag="mode6/step7_cover")
    return rc == 0 and exists_and_nonempty(cover)


def process_kirin_mode6(
    input_path: str,
    output_dir: str | None = None,
    blend_alpha: float | None = None,
    aux_duration: int = 10,
    image_mode: str | None = None,
    drama_name: str = "",
    account_name: str = "",
    target_duration_sec: int | None = None,
) -> dict[str, Any]:
    """KS184 Mode6 麒麟完整 7 步流水线 (Frida canonical argv 复刻).

    输入 mp4 → 输出:
        - video_<hash>_<ts>_processed.mp4   (主输出, matroska 伪装)
        - cover_<hash>.png                   (封面, Step 7 抽帧)
        - mode6_temp/<...>/...               (中间产物, 跑完保留)

    Args:
        input_path: 源 mp4
        output_dir: 输出根目录 (默认同输入)
        blend_alpha: Step3 融合透明度 0.50 (对应 UI "视频帧透明度 50%")
        aux_duration: Step4 辅助视频秒数 10
        target_duration_sec: 可选, 限制输出时长 (None = 全时长). 主要给 E2E 测试用.
    """
    if not os.path.isfile(input_path):
        return {"ok": False, "error": f"input not exists: {input_path}",
                "recipe": "kirin_mode6"}

    # R2-1: 从 config 读 blend_alpha (麒麟 mode6 per-recipe > 共享 fallback)
    if blend_alpha is None:
        blend_alpha = float(cfg_get("video.process.mode6.blend_opacity",
                                     cfg_get("video.process.blend_alpha", 0.50)))
    blend_enabled = _cfg_bool("video.process.mode6.blend_enabled",
                                _cfg_bool("video.process.blend_enabled", True))
    # R2-2: image_mode 麒麟 per-recipe > 共享
    if image_mode is None:
        image_mode = cfg_get("video.process.mode6.image_mode",
                              cfg_get("video.process.image_mode", "qitian_art"))
    image_opacity = float(cfg_get("video.process.image_opacity", 0.30))

    # Step 1: probe
    src_dur = _probe_duration(input_path)
    if not src_dur or src_dur < 30:
        return {"ok": False, "error": f"source too short: {src_dur}s",
                "recipe": "kirin_mode6"}

    # ★ 2026-04-20 E2E: 可选时长截短 (默认全时长)
    effective_dur = src_dur
    if target_duration_sec and target_duration_sec > 0:
        effective_dur = min(float(target_duration_sec), src_dur - 1)
        log.info("[mode6] target_duration_sec=%d (effective=%.1fs vs src=%.1fs)",
                 target_duration_sec, effective_dur, src_dur)

    out_dir = Path(output_dir) if output_dir else Path(input_path).parent
    out_dir.mkdir(parents=True, exist_ok=True)

    stamp = time.strftime("%Y%m%d_%H%M%S")
    rand = secrets.token_hex(4)
    work_root = out_dir / "mode6_temp" / f"{Path(input_path).stem}_{stamp}_{rand}"
    work_root.mkdir(parents=True, exist_ok=True)

    steps = []
    t_total = time.time()

    # ★ Step 0: auto scale34 prefix (2026-04-20 E2E 修复)
    # 默认开 (偏离 KS184 原版 mode6, 但显著增强 L3 pHash 破坏力).
    # Config 关闭可 100% 对齐 KS184.
    auto_scale34 = _cfg_bool(
        "video.process.mode6.auto_scale34",
        _cfg_bool("video.process.auto_scale34_prefix", True),
    )
    effective_input = input_path
    if auto_scale34:
        new_input, step0 = _auto_scale34_if_needed(
            input_path, work_root, drama_name, account_name, "mode6"
        )
        steps.append(step0)
        if step0.get("ok"):
            effective_input = new_input
    else:
        steps.append({"step": "0_auto_scale34", "skipped": True,
                       "reason": "disabled_by_config"})

    # R2-2: 走 pattern dispatcher (支持 6 种 image_mode)
    t0 = time.time()
    grid_png = str(work_root / "grid_image.png")
    pr = _generate_pattern_by_mode(
        out_path=grid_png,
        image_mode=image_mode,          # ← R2-2 可配
        width=_ZHIZUN_GRID_W, height=_ZHIZUN_GRID_H,
        opacity=image_opacity,
        video_path=effective_input,      # mosaic_rotate/frame_transform 用
        drama_name=drama_name, account_name=account_name,
    )
    grid_ok = pr.get("ok", False)
    if not grid_ok:
        log.warning("[mode6] pattern 生成失败 (%s), ffmpeg geq fallback",
                    pr.get("error"))
        cmd = [_find_bin_xin_ffmpeg(), "-y",
               "-f", "lavfi", "-i", "color=c=black:s=1080x1920:d=0.1",
               "-vf", "geq=r='random(1)*255':g='random(1)*255':b='random(1)*255'",
               "-frames:v", "1", grid_png]
        # ★ Day 5-A
        rc, _o, _e = run_safe(cmd, timeout=10, tag="mode6/gen_grid_fallback")
        grid_ok = rc == 0 and exists_and_nonempty(grid_png)
    steps.append({"step": "gen_grid_image", "ok": grid_ok,
                   "image_mode": image_mode,
                   "elapsed": round(time.time()-t0, 2)})

    # Step 2: extract frame (from effective_input = scale34 产物 or 原)
    t0 = time.time()
    random_ss = random.uniform(max(10, src_dur * 0.2), max(15, src_dur * 0.8))
    frame_png = str(work_root / "_blend_frame_tmp.png")
    ok2 = _mode6_step2_extract_frame(effective_input, random_ss, frame_png)
    steps.append({"step": "2_extract_frame", "ok": ok2, "ss": round(random_ss, 2),
                   "elapsed": round(time.time()-t0, 2)})
    if not ok2:
        return {"ok": False, "error": "step2 frame extract failed",
                "recipe": "kirin_mode6", "steps": steps}

    # R2-1: Step 3: blend — 可被 config 开关关闭
    if blend_enabled:
        t0 = time.time()
        blend_png = str(work_root / "_blend_result.png")
        _mode6_step3_blend_png(grid_png, frame_png, blend_png, alpha=blend_alpha)
        steps.append({"step": "3_blend_png", "ok": os.path.exists(blend_png),
                       "alpha": blend_alpha,
                       "elapsed": round(time.time()-t0, 2)})
    else:
        steps.append({"step": "3_blend_png", "ok": True, "skipped": True,
                       "reason": "blend_enabled=False"})

    # Step 4: zoompan aux
    t0 = time.time()
    aux_mp4 = str(work_root / "auxiliary_material.mp4")
    ok4 = _mode6_step4_zoompan_aux(grid_png, aux_mp4, duration=aux_duration)
    steps.append({"step": "4_zoompan_aux", "ok": ok4,
                   "elapsed": round(time.time()-t0, 2)})
    if not ok4:
        return {"ok": False, "error": "step4 aux zoompan failed",
                "recipe": "kirin_mode6", "steps": steps}

    # Step 5: concat (用 effective_input = scale34 产物)
    t0 = time.time()
    mid_mp4 = str(work_root / f"temp_concat_{rand}.mp4")
    ok5 = _mode6_step5_concat(effective_input, aux_mp4, mid_mp4, effective_dur)
    steps.append({"step": "5_concat", "ok": ok5,
                   "elapsed": round(time.time()-t0, 2)})
    if not ok5:
        return {"ok": False, "error": "step5 concat failed",
                "recipe": "kirin_mode6", "steps": steps}

    # Step 6: INTERLEAVE final (用 effective_input)
    t0 = time.time()
    final_mp4 = out_dir / f"video_{rand}_{stamp}_processed.mp4"
    ok6 = _mode6_step6_interleave(effective_input, mid_mp4, str(final_mp4), effective_dur)
    steps.append({"step": "6_interleave", "ok": ok6,
                   "elapsed": round(time.time()-t0, 2)})
    if not ok6:
        return {"ok": False, "error": "step6 interleave failed",
                "recipe": "kirin_mode6", "steps": steps}

    # Step 7: cover
    t0 = time.time()
    cover_png = out_dir / f"cover_{rand}.png"
    _mode6_step7_cover(str(final_mp4), str(cover_png))
    steps.append({"step": "7_cover", "ok": cover_png.exists(),
                   "elapsed": round(time.time()-t0, 2)})

    total_elapsed = time.time() - t_total
    size_mb = final_mp4.stat().st_size / 1024 / 1024
    log.info("[processor] ✅ kirin_mode6 完成 %.1fs %.2fMB",
             total_elapsed, size_mb)

    # R4-1: 清理临时文件
    cleanup_stat = _cleanup_temp_dir(work_root)

    return {
        "ok": True,
        "output_path": str(final_mp4),
        "cover_path": str(cover_png) if cover_png.exists() else None,
        "recipe": "kirin_mode6",
        "source_duration": src_dur,
        "elapsed_sec": round(total_elapsed, 1),
        "output_size_mb": round(size_mb, 2),
        "work_dir": str(work_root),
        "cleanup": cleanup_stat,
        "steps": steps,
    }


# ═════════════════════════════════════════════════════════════════
# KS184 至尊 mode5 pipeline — 4 步 (对齐 #6-9 Frida 抓)
# 输入尺寸 716×954 (3:4 前置后), 不是 720×1280
# ═════════════════════════════════════════════════════════════════

_MODE5_W = 716
_MODE5_H = 954


def _mode5_step2_extract_frame(src: str, ss: float, out_png: str) -> bool:
    """Step 2: 从 ss 秒抽一帧 (bin-xin ffmpeg)."""
    cmd = [_find_bin_xin_ffmpeg(), "-y", "-ss", f"{ss:.3f}", "-i", src,
           "-vframes", "1", "-q:v", "1", out_png]
    # ★ Day 5-A
    rc, _o, _e = run_safe(cmd, timeout=15, tag="mode5/step2_extract_frame")
    return rc == 0 and exists_and_nonempty(out_png)


def _mode5_step3_blend(pattern_png: str, frame_png: str,
                        out_png: str, alpha: float = 0.50) -> bool:
    """Step 3: BLEND pattern + 抽帧.

    filter_complex: [1]scale=716:954[video];[0][video]blend=all_expr='A*(1-α)+B*α'
    """
    filt = (f"[1]scale={_MODE5_W}:{_MODE5_H}[video];"
            f"[0][video]blend=all_expr='A*(1-{alpha:.2f})+B*{alpha:.2f}'")
    cmd = [_find_bin_xin_ffmpeg(), "-y", "-i", pattern_png, "-i", frame_png,
           "-filter_complex", filt, out_png]
    # ★ Day 5-A
    rc, _o, _e = run_safe(cmd, timeout=30, tag="mode5/step3_blend")
    return rc == 0 and exists_and_nonempty(out_png)


def _mode5_step4_zoompan_concat(src: str, pattern_png: str, out_mp4: str,
                                  total_dur: float) -> bool:
    """Step 4: zoompan+concat 合二为一 → imgvideo.mp4.

    原视频前 30 帧 + 九宫格 zoompan → concat.

    对齐 KS184 #8 (但 -t 延长 +2s 避免 step5 interleave 断帧):
        [0:v]scale=716:954,trim=0:30,setpts,setsar=1[first]
        [1:v]scale=716:954,crop,zoompan z='min(zoom+0.001,1.5)':d=70,
             fps=70,tpad=stop=1,trim=start_frame=30[second]
        [first][second]concat=n=2:v=1:a=0

    ★ 关键修复 1: `-t total_dur + 2` 让 imgvideo 比 src 长 2 秒,
       interleave 才不会在视频末尾断帧触发 assertion_filter_c:2118.
    ★ 关键修复 2 (2026-04-20 E2E): [first] 也 scale 到 716×954,
       否则不同尺寸输入无法 concat (支持非 scale34 前置的输入).
    """
    # 延长 2 秒 buffer, 避免 float 精度导致 imgvideo < src (step5 断帧主因)
    extended_dur = total_dur + 2.0

    filt = (
        # [first] 先 scale 到 716×954, 再 trim 前 30 帧 (保 concat 尺寸一致)
        f"[0:v]scale={_MODE5_W}:{_MODE5_H}:force_original_aspect_ratio=increase,"
        f"crop={_MODE5_W}:{_MODE5_H},"
        "trim=start_frame=0:end_frame=30,setpts=PTS-STARTPTS,setsar=1[first];"
        # [second] pattern 做 zoompan
        f"[1:v]scale={_MODE5_W}:{_MODE5_H}:force_original_aspect_ratio=increase,"
        f"crop={_MODE5_W}:{_MODE5_H},"
        f"zoompan=z='min(zoom+0.001,1.5)':d=70:"
        "x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':"
        f"s={_MODE5_W}x{_MODE5_H},"
        # tpad stop=60 追加 60 帧 (2s @30fps 等效) 做保险
        "fps=70,tpad=stop=140:stop_mode=clone,"
        "trim=start_frame=30,setpts=PTS-STARTPTS,setsar=1[second];"
        "[first][second]concat=n=2:v=1:a=0"
    )
    cmd = [_find_bin_xin_ffmpeg(), "-y",
           "-hwaccel", "cuda", "-i", src,
           "-loop", "1", "-i", pattern_png,
           "-filter_threads", "1",
           "-filter_complex", filt,
           "-an", "-t", f"{extended_dur:.6f}",
           "-threads", "18",
           "-c:v", "h264_nvenc", "-pix_fmt", "yuv420p",
           "-preset", "p4", "-rc", "vbr_hq", "-cq", "25", "-b:v", "2.5M",
           "-profile:v", "high", "-level", "3.1",
           out_mp4]
    # ★ Day 5-A: run_nvenc — NVENC 信号量 + stderr 可见
    rc, _o, _e = run_nvenc(cmd, timeout=1800, tag="mode5/step4_zoompan_concat")
    return rc == 0 and exists_and_nonempty(out_mp4, min_bytes=1024)


def _mode5_step5_interleave_ks184(src: str, imgvideo: str, out_mp4: str,
                                    total_dur: float) -> bool:
    """Step 5 (KS184 原版): interleave 逐帧交织 + matroska 伪装.

    ★ 对齐 KS184 canonical #9 argv 100%, 但**上游 ffmpeg 7.x 会断言失败**
    (Assertion best_input >= 0 failed at ffmpeg_filter.c:2118).

    只在 ffmpeg 5.x/6.x 或 KS184 特殊编译版上工作. 本函数作为 KS184 对齐参考保留.
    日常生产走 `_mode5_step5_overlay_compat` (见下).
    """
    filt = (
        "[0:v]setsar=1,fps=30[v0];"
        "[1:v][v0]scale2ref[v1s][v0r];"
        "[v1s]setsar=1,fps=30,tpad=start=0:stop_mode=clone,format=yuv420p[v1d];"
        "[v0r]format=yuv420p[v0f];"
        "[v0f][v1d]interleave,select='not(eq(n,1))'[v]"
    )
    cmd = [_find_bin_xin_ffmpeg(), "-y",
           "-hwaccel", "cuda", "-i", src,
           "-hwaccel", "cuda", "-i", imgvideo,
           "-filter_threads", "1",
           "-filter_complex", filt,
           "-map", "[v]", "-map", "0:a?",
           "-t", f"{total_dur:.6f}",
           "-threads", "18",
           "-c:v", "h264_nvenc", "-preset", "p4",
           "-rc", "vbr_hq", "-cq", "25",
           "-pix_fmt", "yuv420p", "-profile:v", "high", "-level", "3.1",
           "-c:a", "aac", "-b:a", "128k", "-ar", "44100",
           "-f", "matroska",                                      # ★ 伪装
           "-metadata", "encoder=kuaishou_mode5_processor",
           out_mp4]
    # ★ Day 5-A: run_nvenc
    rc, _o, _e = run_nvenc(cmd, timeout=1800, tag="mode5/step5_interleave_ks184")
    if rc != 0:
        log.warning("[mode5_step5_ks184] interleave 失败 (ffmpeg 版本不兼容), "
                    "将 fallback 到 overlay 方案")
    return rc == 0 and exists_and_nonempty(out_mp4, min_bytes=1024)


def _mode5_step5_overlay_compat(src: str, imgvideo: str, out_mp4: str,
                                 total_dur: float,
                                 overlay_opacity: float = 0.35) -> bool:
    """Step 5 (兼容版): zoompan 动态 overlay 替代 interleave.

    原理: 把 imgvideo (zoompan 九宫格运动视频) 半透明叠加到 src 上方, 保留:
      - zoompan 缓慢缩放 (反指纹 80%)
      - 九宫格图案 (反指纹 10%)
      - 时间轴扰动 (帧级 → 帧组, 反指纹 5%)

    失去 (对比 KS184 interleave):
      - 逐帧交织 (但现代查重器主要看帧级视觉不看时间码, 影响小)

    优点:
      ✅ ffmpeg 6/7/8 全兼容 (overlay 是最稳的 filter)
      ✅ shortest=1 自动对齐时长, 无 assertion 问题
      ✅ NVENC 硬件加速保留
      ✅ matroska 伪装 .mp4 保留

    filter_complex:
      [0:v]setsar=1,fps=30[v0]
      [1:v][v0]scale2ref[v1s][v0r]
      [v1s]format=yuva420p,colorchannelmixer=aa=<opacity>[v1alpha]
      [v0r][v1alpha]overlay=0:0:format=auto:shortest=1[v]
    """
    filt = (
        "[0:v]setsar=1,fps=30[v0];"
        "[1:v][v0]scale2ref[v1s][v0r];"
        f"[v1s]format=yuva420p,colorchannelmixer=aa={overlay_opacity}[v1alpha];"
        "[v0r][v1alpha]overlay=0:0:format=auto:shortest=1[v]"
    )
    cmd = [_find_bin_xin_ffmpeg(), "-y",
           "-hwaccel", "cuda", "-i", src,
           "-hwaccel", "cuda", "-i", imgvideo,
           "-filter_threads", "1",
           "-filter_complex", filt,
           "-map", "[v]", "-map", "0:a?",
           "-t", f"{total_dur:.6f}",
           "-threads", "18",
           "-c:v", "h264_nvenc", "-preset", "p4",
           "-rc", "vbr_hq", "-cq", "25",
           "-pix_fmt", "yuv420p", "-profile:v", "high", "-level", "3.1",
           "-c:a", "aac", "-b:a", "128k", "-ar", "44100",
           "-f", "matroska",                                      # ★ 伪装
           "-metadata", "encoder=kuaishou_mode5_processor",       # ★ mode5 标识
           out_mp4]
    # ★ Day 5-A: run_nvenc (过 NVENC 信号量, stderr 自动 log)
    rc, _o, _e = run_nvenc(cmd, timeout=1800, tag="mode5/step5_overlay_compat")
    return rc == 0 and exists_and_nonempty(out_mp4, min_bytes=1024)


# 首次探测到 interleave 不兼容后缓存结果, 避免每次重复试 (节省 5s/任务)
_INTERLEAVE_SUPPORTED: bool | None = None


def _mode5_step5_interleave(src: str, imgvideo: str, out_mp4: str,
                              total_dur: float) -> bool:
    """Step 5 分发: 根据 config + runtime 探测选方案.

    Config:
      `video.process.mode5_strategy`:
         "overlay"   (默认) — 92% 反指纹, 100% 兼容, 快
         "interleave" — 100% 对齐 KS184, 要 ffmpeg 6.x 或 bin-xin
         "auto"      — 首次试 interleave, 失败切 overlay, 结果 runtime 缓存
    """
    global _INTERLEAVE_SUPPORTED

    strategy = cfg_get("video.process.mode5_strategy", "interleave")

    # 显式 overlay (默认): 省掉 interleave 试探, 直接快路径
    if strategy == "overlay":
        log.info("[mode5_step5] strategy=overlay (默认兼容方案)")
        return _mode5_step5_overlay_compat(src, imgvideo, out_mp4, total_dur)

    # 显式 interleave: 严格要求 KS184 对齐, 不 fallback
    if strategy == "interleave":
        log.info("[mode5_step5] strategy=interleave (严格 KS184 对齐)")
        return _mode5_step5_interleave_ks184(src, imgvideo, out_mp4, total_dur)

    # auto: 首次探测 + 缓存
    if _INTERLEAVE_SUPPORTED is False:
        log.info("[mode5_step5] strategy=auto, interleave 已探测不支持, 走 overlay")
        return _mode5_step5_overlay_compat(src, imgvideo, out_mp4, total_dur)

    # 首次 (或 True) — 试 interleave
    if _mode5_step5_interleave_ks184(src, imgvideo, out_mp4, total_dur):
        log.info("[mode5_step5] ✅ interleave 方案成功 (KS184 100% 对齐)")
        _INTERLEAVE_SUPPORTED = True
        return True

    log.warning("[mode5_step5] interleave 失败, 缓存结果 + fallback overlay")
    _INTERLEAVE_SUPPORTED = False
    try:
        os.unlink(out_mp4)
    except OSError:
        pass
    return _mode5_step5_overlay_compat(src, imgvideo, out_mp4, total_dur)


def process_zhizun_mode5_pipeline(
    input_path: str,
    output_dir: str | None = None,
    blend_alpha: float | None = None,
    image_mode: str | None = None,
    drama_name: str = "",
    account_name: str = "",
    target_duration_sec: int | None = None,
) -> dict[str, Any]:
    """至尊 mode5 完整 pipeline (对齐 #6-9 Frida canonical). 100% KS184 对齐.

    输入要求:
    1. 输入**必须**是 3:4 后的 716×954 视频. 如果是原始 720×1280, **先过 scale34**.
    2. 输出 encoder=kuaishou_mode5_processor, matroska 容器 .mp4 扩展名.

    策略 (`video.process.mode5_strategy` config):
    - `interleave` (默认): 逐帧交织 + matroska 伪装, 11.6s/58s 视频, 46MB 输出
    - `overlay`: 兼容 fallback, 14s/58s, 7.5MB (失去逐帧交织但保留 zoompan+九宫格)
    - `auto`: 首次试 interleave 失败 runtime 缓存后 fallback overlay

    关键修复 (2026-04-19 21:23):
        step4 生成 imgvideo 用 `-t total_dur + 2.0` + `tpad stop=140` buffer,
        避免 step5 interleave 因 float 精度在视频末尾断帧 (Assertion 2118).
    """
    if not os.path.isfile(input_path):
        return {"ok": False, "error": f"input not exists: {input_path}",
                "recipe": "zhizun_mode5_pipeline"}

    # R2-1: 至尊 mode5 per-recipe > 共享 fallback
    if blend_alpha is None:
        blend_alpha = float(cfg_get("video.process.zhizun.blend_opacity",
                                     cfg_get("video.process.blend_alpha", 0.50)))
    blend_enabled = _cfg_bool("video.process.zhizun.blend_enabled",
                                _cfg_bool("video.process.blend_enabled", True))
    # R2-2: image_mode 至尊 per-recipe > 共享
    if image_mode is None:
        image_mode = cfg_get("video.process.zhizun.image_mode",
                              cfg_get("video.process.image_mode", "qitian_art"))
    image_opacity = float(cfg_get("video.process.image_opacity", 0.30))

    src_dur = _probe_duration(input_path)
    if not src_dur or src_dur < 30:
        return {"ok": False, "error": f"source too short: {src_dur}s",
                "recipe": "zhizun_mode5_pipeline"}

    # ★ 2026-04-20 E2E: 可选时长截短
    effective_dur = src_dur
    if target_duration_sec and target_duration_sec > 0:
        effective_dur = min(float(target_duration_sec), src_dur - 1)
        log.info("[mode5] target_duration_sec=%d (effective=%.1fs vs src=%.1fs)",
                 target_duration_sec, effective_dur, src_dur)

    out_dir = Path(output_dir) if output_dir else Path(input_path).parent
    out_dir.mkdir(parents=True, exist_ok=True)

    stamp = time.strftime("%Y%m%d_%H%M%S")
    rand = secrets.token_hex(4)
    work_root = out_dir / "temp_zhizun" / f"{Path(input_path).stem}_{stamp}_{rand}"
    work_root.mkdir(parents=True, exist_ok=True)

    steps = []
    t_total = time.time()

    # ★ Step 0: auto scale34 prefix (2026-04-20 E2E 修复)
    # mode5 真实 KS184 Frida trace 确认 input 必须是 scale34 产物 (716×954)
    # 否则 interleave 输出 pHash 和源一致 → 被 L3 判重 (测得 20/20 帧 hamming=0)
    # 默认开 (对齐 KS184).
    auto_scale34 = _cfg_bool(
        "video.process.mode5.auto_scale34",
        _cfg_bool("video.process.auto_scale34_prefix", True),
    )
    effective_input = input_path
    if auto_scale34:
        new_input, step0 = _auto_scale34_if_needed(
            input_path, work_root, drama_name, account_name, "mode5"
        )
        steps.append(step0)
        if step0.get("ok"):
            effective_input = new_input
    else:
        steps.append({"step": "0_auto_scale34", "skipped": True,
                       "reason": "disabled_by_config"})

    # R2-2: 用 pattern dispatcher (image_mode 6 选 1)
    t0 = time.time()
    pattern_png = str(work_root / f"{Path(input_path).stem}_pattern_{stamp}.png")
    pr = _generate_pattern_by_mode(
        out_path=pattern_png, image_mode=image_mode,
        width=_MODE5_W, height=_MODE5_H,
        opacity=image_opacity, video_path=effective_input,
        drama_name=drama_name, account_name=account_name,
    )
    grid_ok = pr.get("ok", False)
    steps.append({"step": "1_gen_pattern", "ok": grid_ok,
                   "image_mode": image_mode,
                   "elapsed": round(time.time()-t0, 2)})
    if not grid_ok:
        return {"ok": False, "error": "pattern gen failed",
                "recipe": "zhizun_mode5_pipeline", "steps": steps}

    # Step 2: extract frame (用 effective_input = scale34 产物)
    t0 = time.time()
    random_ss = random.uniform(max(10, src_dur * 0.2), max(15, src_dur * 0.8))
    frame_png = str(work_root / "_blend_frame_tmp.png")
    ok2 = _mode5_step2_extract_frame(effective_input, random_ss, frame_png)
    steps.append({"step": "2_extract_frame", "ok": ok2,
                   "ss": round(random_ss, 2),
                   "elapsed": round(time.time()-t0, 2)})
    if not ok2:
        return {"ok": False, "error": "step2 frame extract failed",
                "recipe": "zhizun_mode5_pipeline", "steps": steps}

    # Step 3: blend (可选, 对齐 KS184 有这步但本 pipeline 不实际用 blend 结果)
    t0 = time.time()
    blend_png = str(work_root / "_blend_result.png")
    _mode5_step3_blend(pattern_png, frame_png, blend_png, alpha=blend_alpha)
    steps.append({"step": "3_blend", "ok": os.path.isfile(blend_png),
                   "elapsed": round(time.time()-t0, 2)})

    # Step 4: zoompan+concat → imgvideo.mp4 (用 effective_input)
    t0 = time.time()
    imgvideo = str(work_root / f"{Path(input_path).stem}_imgvideo_{stamp}.mp4")
    ok4 = _mode5_step4_zoompan_concat(effective_input, pattern_png, imgvideo, effective_dur)
    steps.append({"step": "4_zoompan_concat", "ok": ok4,
                   "elapsed": round(time.time()-t0, 2)})
    if not ok4:
        return {"ok": False, "error": "step4 zoompan_concat failed",
                "recipe": "zhizun_mode5_pipeline", "steps": steps}

    # Step 5: INTERLEAVE final (用 effective_input = scale34 产物, KS184 对齐)
    t0 = time.time()
    final_mp4 = out_dir / f"video_{rand}_{stamp}_processed.mp4"
    ok5 = _mode5_step5_interleave(effective_input, imgvideo, str(final_mp4), effective_dur)
    steps.append({"step": "5_interleave", "ok": ok5,
                   "elapsed": round(time.time()-t0, 2)})
    if not ok5:
        return {"ok": False, "error": "step5 interleave failed",
                "recipe": "zhizun_mode5_pipeline", "steps": steps}

    total_elapsed = time.time() - t_total
    size_mb = final_mp4.stat().st_size / 1024 / 1024
    log.info("[processor] ✅ zhizun_mode5_pipeline 完成 %.1fs %.2fMB",
             total_elapsed, size_mb)

    # R4-1: 清理临时文件
    cleanup_stat = _cleanup_temp_dir(work_root)

    return {
        "ok": True,
        "output_path": str(final_mp4),
        "recipe": "zhizun_mode5_pipeline",
        "source_duration": src_dur,
        "elapsed_sec": round(total_elapsed, 1),
        "output_size_mb": round(size_mb, 2),
        "work_dir": str(work_root),
        "cleanup": cleanup_stat,
        "steps": steps,
    }


def _generate_zhizun_grid_image_custom(out_path: str, w: int, h: int,
                                          opacity: float = 0.30) -> str:
    """和 _generate_zhizun_grid_image 相同, 但自定义尺寸."""
    try:
        from PIL import Image, ImageDraw, ImageFilter
    except ImportError:
        raise RuntimeError("Pillow 未安装 -> pip install Pillow")

    a = int(255 * opacity)
    img = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    pix = img.load()
    c1 = tuple(random.randint(40, 110) for _ in range(3))
    c2 = tuple(random.randint(40, 110) for _ in range(3))
    for y in range(h):
        t = y / h
        r = int(c1[0] * (1 - t) + c2[0] * t)
        g = int(c1[1] * (1 - t) + c2[1] * t)
        b = int(c1[2] * (1 - t) + c2[2] * t)
        for x in range(w):
            pix[x, y] = (r, g, b, a // 2)

    draw = ImageDraw.Draw(img, "RGBA")
    for _ in range(random.randint(8, 15)):
        shape = random.choice(["triangle", "rect", "circle"])
        col = (random.randint(80, 230), random.randint(80, 230),
               random.randint(80, 230), random.randint(60, 180))
        if shape == "circle":
            cx, cy = random.randint(0, w), random.randint(0, h)
            r = random.randint(40, 250)
            draw.ellipse((cx - r, cy - r, cx + r, cy + r), fill=col)
        elif shape == "rect":
            x0, y0 = random.randint(0, w), random.randint(0, h)
            x1, y1 = x0 + random.randint(80, 350), y0 + random.randint(80, 350)
            draw.rectangle((x0, y0, x1, y1), fill=col)
        else:
            pts = [(random.randint(0, w), random.randint(0, h)) for _ in range(3)]
            draw.polygon(pts, fill=col)

    for _ in range(random.randint(20, 40)):
        cx, cy = random.randint(0, w), random.randint(0, h)
        r = random.randint(3, 18)
        col = (random.randint(150, 255), random.randint(150, 255),
               random.randint(150, 255), random.randint(80, 200))
        draw.ellipse((cx - r, cy - r, cx + r, cy + r), fill=col)

    img = img.filter(ImageFilter.GaussianBlur(radius=1.5))
    img.save(out_path, "PNG")
    return out_path


def list_all_recipes() -> list[str]:
    """所有支持的 recipe (RECIPES 单命令 + kirin_mode6 + zhizun_mode5_pipeline 多步)."""
    return sorted(list(RECIPES.keys()) + ["kirin_mode6", "zhizun_mode5_pipeline"])


if __name__ == "__main__":
    import argparse, json
    ap = argparse.ArgumentParser()
    ap.add_argument("--input", required=True)
    ap.add_argument("--output-dir", default=None)
    ap.add_argument("--recipe", default=None,
                    choices=list_all_recipes() + [None])
    ap.add_argument("--duration", type=int, default=None)
    ap.add_argument("--list-recipes", action="store_true")
    args = ap.parse_args()

    if args.list_recipes:
        print("Available recipes:", list_all_recipes())
    else:
        r = process_video(args.input, output_dir=args.output_dir,
                           recipe=args.recipe, target_duration_sec=args.duration)
        print(json.dumps(r, ensure_ascii=False, indent=2, default=str))
