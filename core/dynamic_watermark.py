# -*- coding: utf-8 -*-
"""动态水印 — 独立模块, 所有 recipe 可选用.

对齐 KS184 scale34 的 sin 波动水印 (强反指纹).

用法:
    # 1. 拿到 processed video 后可选加动态水印
    from core.dynamic_watermark import apply_dynamic_watermark

    result = apply_dynamic_watermark(
        input_video="processed.mp4",
        output_video="processed_wm.mp4",
        drama_name="小小武神",       # 可选 — None 则不加顶部剧名
        account_name="思莱短剧",     # 动态水印内容
        enable_top_drama=True,       # 顶部剧名 (固定位置)
        enable_bottom_warning=False, # 底部警示语
        enable_dynamic_account=True, # 动态账号水印 (sin)
    )

或者**自动模式** (从 app_config 读):
    result = apply_dynamic_watermark_auto(
        input_video, output_video, drama_name, account_name,
    )

配置:
    video.dynamic_watermark.enabled     = True/False  (总开关)
    video.dynamic_watermark.account_opacity = 0.3     (账号水印透明度)
    video.dynamic_watermark.size            = 23
    video.dynamic_watermark.color           = white
"""
from __future__ import annotations

import logging
import math
import os
import random
import subprocess
import time
from pathlib import Path
from typing import Any

from core.app_config import get as cfg_get

log = logging.getLogger(__name__)

# 默认底部警示语
DEFAULT_BOTTOM_TEXT = "影视效果 请勿模仿"


def _ffmpeg_exe() -> str:
    for p in [
        r"C:\Program Files\kuaishou2\KS184.7z\KS184\tools\ffmpeg\bin\ffmpeg.exe",
        r"D:\ks_automation\tools\ffmpeg\bin\ffmpeg.exe",
    ]:
        if os.path.isfile(p):
            return p
    return "ffmpeg"


def make_sin_position_expr(
    base_x: int = 50 + 258,       # 中心 x
    base_y: int = 50 + 336,       # 中心 y
    amp_x: int = 258,             # 主振幅 x
    amp_y: int = 336,             # 主振幅 y
) -> tuple[str, str]:
    """KS184 风格 sin 动态水印位置 — 每秒变化, 强反指纹.

    x = base_x + amp_x*sin(2π*t/T1) + (amp_x/2)*sin(2π*t/T2 + φ1)
    y = base_y + amp_y*sin(2π*t/T3 + φ2) + (amp_y/2)*sin(2π*t/T4 + φ3)

    T1-T4 随机选 [35, 95] 秒周期, φ 随机 → 每次任务轨迹不同.

    Returns: (x_expr, y_expr) ffmpeg drawtext 表达式字符串
    """
    t1 = random.uniform(70.0, 95.0)
    t2 = random.uniform(40.0, 60.0)
    t3 = random.uniform(55.0, 80.0)
    t4 = random.uniform(35.0, 55.0)
    p1 = random.uniform(0.0, 2 * math.pi)
    p2 = random.uniform(0.0, 2 * math.pi)
    p3 = random.uniform(0.0, 2 * math.pi)

    half_x = amp_x // 2
    half_y = amp_y // 2
    x_expr = (
        f"({base_x}+{amp_x}*sin(2*PI*t/{t1:.6f})+"
        f"{half_x}*sin(2*PI*t/{t2:.6f}+{p1:.4f}))"
    )
    y_expr = (
        f"({base_y}+{amp_y}*sin(2*PI*t/{t3:.6f}+{p2:.4f})+"
        f"{half_y}*sin(2*PI*t/{t4:.6f}+{p3:.4f}))"
    )
    return x_expr, y_expr


def _escape_drawtext_text(text: str) -> str:
    """drawtext text= 值的特殊字符转义."""
    return text.replace("\\", "\\\\").replace("'", "\\'").replace(":", "\\:")


def _probe_dims(path: str) -> tuple[int, int, float] | None:
    """ffprobe 拿 宽×高×时长."""
    import re
    ffmpeg = _ffmpeg_exe()
    try:
        r = subprocess.run(
            [ffmpeg, "-i", path, "-t", "0.1", "-f", "null", "-"],
            capture_output=True, text=True, timeout=10,
            encoding="utf-8", errors="replace",
        )
        stderr = r.stderr or ""
        m_dim = re.search(r"Stream.*Video.*\s(\d{3,4})x(\d{3,4})", stderr)
        m_dur = re.search(r"Duration:\s*(\d+):(\d+):(\d+\.\d+)", stderr)
        if not m_dim or not m_dur:
            return None
        w, h = int(m_dim.group(1)), int(m_dim.group(2))
        dur = (int(m_dur.group(1)) * 3600 + int(m_dur.group(2)) * 60
               + float(m_dur.group(3)))
        return w, h, dur
    except Exception:
        return None


def apply_dynamic_watermark(
    input_video: str,
    output_video: str,
    drama_name: str = "",
    account_name: str = "",
    enable_top_drama: bool = False,
    enable_bottom_warning: bool = False,
    enable_dynamic_account: bool = True,
    top_size: int = 38,
    top_color: str = "white",
    bottom_text: str | None = None,
    bottom_size: int = 38,
    bottom_color: str = "red",
    account_size: int | None = None,
    account_color: str | None = None,
    account_opacity: float | None = None,
    font_path: str | None = None,
    crf: int = 23,
) -> dict[str, Any]:
    """给任意视频加动态水印 (sin 位置) + 可选顶部/底部静态文字.

    Args:
        input_video: 已处理好的 mp4
        output_video: 带水印输出
        drama_name/account_name: 水印文字
        enable_top_drama: 顶部加剧名 (固定居中)
        enable_bottom_warning: 底部加警示语 (固定居中, 红色)
        enable_dynamic_account: 账号水印 sin 波动 (反指纹核心)
        其他: 各文字样式参数 (None 则读 config)

    Returns:
        {ok, output_path, duration_sec, elapsed_sec, error?}
    """
    if not os.path.isfile(input_video):
        return {"ok": False, "error": f"input not exists: {input_video}"}

    dims = _probe_dims(input_video)
    if dims is None:
        return {"ok": False, "error": "probe failed"}
    w, h, dur = dims

    # 从 config 默认
    if account_size is None:
        account_size = int(cfg_get("video.dynamic_watermark.size", 23))
    if account_color is None:
        account_color = cfg_get("video.dynamic_watermark.color", "white")
    if account_opacity is None:
        account_opacity = float(
            cfg_get("video.dynamic_watermark.account_opacity", 0.3))

    # 字体路径
    if font_path is None:
        try:
            from core.font_pool import pick_font
            mode = cfg_get("watermark.font.mode", "random")
            font_path = pick_font(mode=mode, drawtext_safe=True)
        except Exception:
            font_path = r"C:\Windows\Fonts\msyh.ttc"

    # ffmpeg fontfile 路径 escape (任意盘符)
    ff_font = font_path.replace("\\", "/")
    if len(ff_font) >= 2 and ff_font[1] == ":":
        ff_font = ff_font[0] + "\\:" + ff_font[2:]

    # 构 filter_complex
    parts = []
    last_label = "[0:v]"

    # 顶部剧名 (固定居中, 上方 y=size/2 附近)
    if enable_top_drama and drama_name:
        drama_esc = _escape_drawtext_text(drama_name)
        parts.append(
            f"{last_label}drawtext=text='{drama_esc}':fontfile='{ff_font}':"
            f"fontsize={top_size}:fontcolor={top_color}:"
            f"x=(w-text_w)/2:y={top_size}-text_h/2[v_top]"
        )
        last_label = "[v_top]"

    # 底部警示语 (固定居中, 红色, 下方 y=h-size 附近)
    if enable_bottom_warning:
        warn_text = bottom_text or DEFAULT_BOTTOM_TEXT
        warn_esc = _escape_drawtext_text(warn_text)
        parts.append(
            f"{last_label}drawtext=text='{warn_esc}':fontfile='{ff_font}':"
            f"fontsize={bottom_size}:fontcolor={bottom_color}:"
            f"x=(w-text_w)/2:y={h - bottom_size}-text_h/2[v_bot]"
        )
        last_label = "[v_bot]"

    # 动态账号水印 (sin, 反指纹核心)
    if enable_dynamic_account and account_name:
        # 按视频尺寸自适应 amp/base
        base_x = min(50 + 258, w // 2)
        base_y = min(50 + 336, h // 2)
        amp_x = min(258, (w - 100) // 2)
        amp_y = min(336, (h - 100) // 2)
        x_expr, y_expr = make_sin_position_expr(base_x, base_y, amp_x, amp_y)
        acc_esc = _escape_drawtext_text(account_name)
        parts.append(
            f"{last_label}drawtext=text='{acc_esc}':fontfile='{ff_font}':"
            f"fontsize={account_size}:fontcolor={account_color}@{account_opacity:.2f}:"
            f"x='{x_expr}':y='{y_expr}'[v_final]"
        )
        last_label = "[v_final]"

    # 如果没有任何 drawtext, 直接复制
    if not parts:
        import shutil
        shutil.copy(input_video, output_video)
        return {"ok": True, "output_path": output_video,
                "skipped": True, "reason": "no_watermark_enabled"}

    fc = ";".join(parts)

    cmd = [
        _ffmpeg_exe(), "-y", "-loglevel", "warning",
        "-i", input_video,
        "-filter_complex", fc,
        "-map", last_label, "-map", "0:a?",
        "-c:v", "libx264", "-preset", "medium", "-crf", str(crf),
        "-c:a", "copy",
        "-movflags", "+faststart",
        output_video,
    ]

    t0 = time.time()
    try:
        r = subprocess.run(cmd, capture_output=True, timeout=600,
                           encoding="utf-8", errors="replace")
    except subprocess.TimeoutExpired:
        return {"ok": False, "error": "ffmpeg_timeout"}

    elapsed = time.time() - t0
    if r.returncode != 0:
        err = (r.stderr or "")[-400:]
        return {"ok": False, "error": f"ffmpeg_err: {err}",
                "elapsed_sec": round(elapsed, 1)}

    if not os.path.isfile(output_video) or os.path.getsize(output_video) < 1024:
        return {"ok": False, "error": "output missing or tiny"}

    out_mb = os.path.getsize(output_video) / 1024 / 1024
    log.info("[dynamic_wm] ✅ %dx%d → %s (%.1fMB, %.1fs)",
             w, h, output_video, out_mb, elapsed)

    return {
        "ok": True,
        "output_path": output_video,
        "input_w": w, "input_h": h,
        "duration_sec": dur,
        "elapsed_sec": round(elapsed, 1),
        "output_size_mb": round(out_mb, 2),
        "layers": {
            "top_drama": enable_top_drama,
            "bottom_warning": enable_bottom_warning,
            "dynamic_account": enable_dynamic_account,
        },
    }


def apply_dynamic_watermark_auto(
    input_video: str,
    output_video: str,
    drama_name: str = "",
    account_name: str = "",
) -> dict[str, Any]:
    """自动模式: 从 app_config 读所有开关.

    主要配置:
      video.dynamic_watermark.enabled          = true/false (总开关)
      video.dynamic_watermark.layer.top        = false
      video.dynamic_watermark.layer.bottom     = false
      video.dynamic_watermark.layer.account    = true

    总开关关则直接 copy 文件, 不加任何水印.
    """
    enabled = cfg_get("video.dynamic_watermark.enabled", False)
    if isinstance(enabled, str):
        enabled = enabled.lower() in ("true", "1", "yes", "on")
    if not enabled:
        import shutil
        shutil.copy(input_video, output_video)
        return {"ok": True, "output_path": output_video,
                "skipped": True, "reason": "dynamic_watermark.enabled=false"}

    def _cfg_bool(k, d):
        v = cfg_get(k, d)
        if isinstance(v, bool):
            return v
        if isinstance(v, str):
            return v.lower() in ("true", "1", "yes", "on")
        return bool(v)

    return apply_dynamic_watermark(
        input_video=input_video, output_video=output_video,
        drama_name=drama_name, account_name=account_name,
        enable_top_drama=_cfg_bool("video.dynamic_watermark.layer.top", False),
        enable_bottom_warning=_cfg_bool("video.dynamic_watermark.layer.bottom", False),
        enable_dynamic_account=_cfg_bool("video.dynamic_watermark.layer.account", True),
    )


if __name__ == "__main__":
    import argparse, json, sys
    sys.stdout.reconfigure(encoding="utf-8")
    logging.basicConfig(level=logging.INFO, format="[%(asctime)s] %(message)s")

    ap = argparse.ArgumentParser()
    ap.add_argument("--input", required=True)
    ap.add_argument("--output", required=True)
    ap.add_argument("--drama", default="")
    ap.add_argument("--account", default="思莱短剧")
    ap.add_argument("--top", action="store_true", help="加顶部剧名")
    ap.add_argument("--bottom", action="store_true", help="加底部警示")
    ap.add_argument("--no-dyn", action="store_true", help="关动态水印")
    args = ap.parse_args()

    r = apply_dynamic_watermark(
        input_video=args.input, output_video=args.output,
        drama_name=args.drama, account_name=args.account,
        enable_top_drama=args.top,
        enable_bottom_warning=args.bottom,
        enable_dynamic_account=not args.no_dyn,
    )
    print(json.dumps(r, ensure_ascii=False, indent=2, default=str))
