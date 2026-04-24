# -*- coding: utf-8 -*-
"""3:4 竖屏前置处理 — 对齐 KS184 scale34_style_service.

来源:
- Frida 2026-04-19 19:19:45 捕获 #2 完整 argv (canonical v2 doc §二)
- KS184 Q_x64 dump: `multi_device/services/scale34_style_service.py` 独立模块
- UI 模式: "等比缩放 模糊背景填充" / "3:4 比例处理 + 水印"

KS184 #2 argv 逻辑 (720×1280 → 716×954):
    Step 1: [0:v]scale=716:802,boxblur=20:5[blur]      — 原视频压扁高度 + 模糊当背景
    Step 2: [0:v]scale=448:802[fg]                      — 原视频再缩一份作前景 (窄)
    Step 3: [blur][fg]overlay=134:0[video_area]         — 前景居中 overlay ((716-448)/2=134)
    Step 4: [video_area]pad=716:954:0:76:black[base]    — 垂直填黑 (上下各 76, 总高 802+152=954)
    Step 5: drawtext 剧名 (顶部白色 38px msyh.ttc, y=38 居中在顶部黑边)
    Step 6: drawtext "影视效果 请勿模仿" (底部红色 38px, y=916 居中在底部黑边)
    Step 7: drawtext 账号水印 (23px white@0.3, sin 波动位置)
    编码: libx264 -preset medium -crf 23 + aac 192k

★ 动态水印 sin 公式 — 每秒位置都在变, 强反指纹:
    x = 50 + 258 + 258*sin(2π*t/T1) + 129*sin(2π*t/T2 + φ1)
    y = 76 + 50 + 336 + 336*sin(2π*t/T3 + φ2) + 168*sin(2π*t/T4 + φ3)
    周期 T1-T4 ∈ [45, 86] 秒, 相位 φ 随机
"""
from __future__ import annotations

import logging
import math
import os
import random
import re
import subprocess
import tempfile
import time
from pathlib import Path
from typing import Any

from core.app_config import get as cfg_get

log = logging.getLogger(__name__)

# ── 尺寸常量 (对齐 KS184 #2) ──
_W_OUT = 716          # 3:4 输出宽度
_H_OUT = 954          # 3:4 输出高度 (= _H_VIDEO + 2 × _PAD)
_H_VIDEO = 802        # 视频内容高度
_W_FG = 448           # 前景视频宽度 (比输出窄, 模拟手机竖屏视频居中)
_PAD = 76             # 上下黑边高度 ((954 - 802) / 2 = 76)

# ── 字体 ──
_FONT_MSYH = r"C:\Windows\Fonts\msyh.ttc"

# ── 默认文本 (底部警示) ──
_DEFAULT_BOTTOM_TEXT = "影视效果 请勿模仿"


def _ffmpeg_exe() -> str:
    """返回 KS184 tools/ffmpeg/bin/ffmpeg.exe (优先), 否则 fallback.

    注: 这个 bin/ffmpeg.exe 是 libx264 版 (无 NVENC), 用于 CPU 编码.
    """
    for p in [
        r"C:\Program Files\kuaishou2\KS184.7z\KS184\tools\ffmpeg\bin\ffmpeg.exe",
        r"D:\ks_automation\tools\ffmpeg\bin\ffmpeg.exe",
        r"D:\ks_automation\tools\m3u8dl\ffmpeg.exe",
    ]:
        if os.path.isfile(p):
            return p
    return "ffmpeg"


def _ffmpeg_nvenc() -> str:
    """返回支持 NVENC 的 ffmpeg (bin-xin full_build 版).

    CLAUDE.md §7 确认: tools/ffmpeg/bin-xin/ffmpeg.exe = NVENC 版 (kirin/mode5 用的).
    fallback 到 _ffmpeg_exe() 如果找不到.
    """
    for p in [
        r"C:\Program Files\kuaishou2\KS184.7z\KS184\tools\ffmpeg\bin-xin\ffmpeg.exe",
        r"D:\ks_automation\tools\ffmpeg\bin-xin\ffmpeg.exe",
    ]:
        if os.path.isfile(p):
            return p
    log.warning("[scale34] NVENC ffmpeg not found, fallback to libx264 CPU 版")
    return _ffmpeg_exe()


def _cfg_bool(key: str, default: bool) -> bool:
    """Config bool coerce (同 processor._cfg_bool)."""
    v = cfg_get(key, None)
    if v is None:
        return default
    if isinstance(v, bool):
        return v
    if isinstance(v, str):
        return v.strip().lower() in ("true", "1", "yes", "on")
    return bool(v)


def _escape_drawtext_text(text: str) -> str:
    """drawtext text= 值的特殊字符转义 (冒号/反斜杠/单引号)."""
    # 按 ffmpeg drawtext 规范, ' → \', : → \:, \ → \\
    return text.replace("\\", "\\\\").replace("'", "\\'").replace(":", "\\:")


def _make_sin_position_expr() -> tuple[str, str]:
    """生成 KS184 风格的 sin 动态水印位置表达式 (x, y).

    对齐 #2 argv:
      x = 50 + 258 + 258*sin(2π*t/T1) + 129*sin(2π*t/T2 + φ1)
      y = 76 + 50 + 336 + 336*sin(2π*t/T3 + φ2) + 168*sin(2π*t/T4 + φ3)

    KS184 的 T1=85.97200125, T2=50.571765441176474, T3=68.777601, T4=45.851734
    相位 φ1=1.2, φ2=0.5, φ3=2.1 (每次任务随机即可)
    """
    t1 = random.uniform(70.0, 95.0)
    t2 = random.uniform(40.0, 60.0)
    t3 = random.uniform(55.0, 80.0)
    t4 = random.uniform(35.0, 55.0)
    p1 = random.uniform(0.0, 2 * math.pi)
    p2 = random.uniform(0.0, 2 * math.pi)
    p3 = random.uniform(0.0, 2 * math.pi)

    x_expr = (
        f"(50+258+258*sin(2*PI*t/{t1:.6f})+"
        f"129*sin(2*PI*t/{t2:.6f}+{p1:.4f}))"
    )
    y_expr = (
        f"({_PAD}+50+336+336*sin(2*PI*t/{t3:.6f}+{p2:.4f})+"
        f"168*sin(2*PI*t/{t4:.6f}+{p3:.4f}))"
    )
    return x_expr, y_expr


def _probe_video_size(path: str) -> tuple[int, int, float] | None:
    """ffprobe 拿视频 宽×高×时长. 返回 None 表示失败."""
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
    except Exception as e:
        log.warning("[scale34] probe failed: %s", e)
        return None


def _build_filter_complex(
    drama_name: str,
    account_name: str,
    bottom_text: str = _DEFAULT_BOTTOM_TEXT,
    top_fontsize: int = 38,
    top_color: str = "white",
    bottom_fontsize: int = 38,
    bottom_color: str = "red",
    wm_fontsize: int = 23,
    wm_color: str = "white@0.3",
    enable_dynamic_wm: bool = True,
) -> tuple[str, str]:
    """生成 KS184 风格的 filter_complex 字符串 (对齐 #2 argv).

    Returns: (filter_complex_str, final_label_str)
    """
    # ffmpeg drawtext fontfile 路径 escape (反斜杠全变正斜杠, 冒号前加反斜杠)
    ff_font = _FONT_MSYH.replace("\\", "/").replace("C:", "C\\:")

    drama_esc = _escape_drawtext_text(drama_name)
    account_esc = _escape_drawtext_text(account_name)
    bottom_esc = _escape_drawtext_text(bottom_text)

    parts = [
        # 1+2+3 模糊背景+前景 overlay
        f"[0:v]scale={_W_OUT}:{_H_VIDEO},boxblur=20:5[blur]",
        f"[0:v]scale={_W_FG}:{_H_VIDEO}[fg]",
        f"[blur][fg]overlay={(_W_OUT - _W_FG) // 2}:0[video_area]",
        # 4 上下黑边 pad
        f"[video_area]pad={_W_OUT}:{_H_OUT}:0:{_PAD}:black[base]",
        # 5 顶部剧名 (居中在顶部黑边内, y=_PAD/2 位置)
        f"[base]drawtext=text='{drama_esc}':fontfile='{ff_font}':"
        f"fontsize={top_fontsize}:fontcolor={top_color}:"
        f"x=(w-text_w)/2:y={_PAD // 2 + _PAD // 2}-text_h/2[withtop]",
        # 6 底部红字 (居中在底部黑边内)
        f"[withtop]drawtext=text='{bottom_esc}':fontfile='{ff_font}':"
        f"fontsize={bottom_fontsize}:fontcolor={bottom_color}:"
        f"x=(w-text_w)/2:y={_H_OUT - _PAD + _PAD // 2}-text_h/2[withbottom]",
    ]

    # 7 动态水印 (账号名 sin 波动)
    if enable_dynamic_wm and account_name:
        x_expr, y_expr = _make_sin_position_expr()
        parts.append(
            f"[withbottom]drawtext=text='{account_esc}':fontfile='{ff_font}':"
            f"fontsize={wm_fontsize}:fontcolor={wm_color}:"
            f"x='{x_expr}':y='{y_expr}'[final]"
        )
        final_label = "[final]"
    else:
        # 没水印时直接映射 withbottom
        final_label = "[withbottom]"

    return ";".join(parts), final_label


def process_scale34_video(
    input_path: str,
    drama_name: str,
    account_name: str,
    output_path: str | None = None,
    bottom_text: str | None = None,
    threads: int = 4,
    crf: int | None = None,
    enable_dynamic_watermark: bool = True,
    use_gpu: bool | None = None,
) -> dict[str, Any]:
    """KS184 3:4 前置处理 — 模糊背景 + 小视频前景 + 上下文字.

    对齐 KS184 #2 argv (2026-04-19 Frida 抓).

    Args:
        input_path: 原视频 mp4 (720×1280 或其他竖屏)
        drama_name: 剧名 (顶部文字)
        account_name: 账号名 (动态水印文字)
        output_path: 输出 mp4. None = 同目录加 `_34` 后缀
        bottom_text: 底部警示. None = "影视效果 请勿模仿"
        threads: ffmpeg -threads
        crf: 质量 (GPU 模式=NVENC cq 22, CPU 模式=libx264 crf 23).
             None = 从 config 读
        enable_dynamic_watermark: 是否加 sin 动态水印 (默认 True)
        use_gpu: 是否用 NVENC 硬编. None = 从 config 读 (默认 True).
                 True  → NVENC p4 cq 22 (10x 速度, 质量接近 libx264 crf 23)
                 False → libx264 preset=medium crf 23 (KS184 原版 CPU 模式)

    Returns:
        {ok, output_path?, input_size, output_size, error?}

    2026-04-20 更新:
      - 默认走 NVENC (省 90s/任务, L3 pHash 过率保持 95%)
      - 可 config `video.process.scale34.use_gpu=false` 切回 CPU
    """
    if not os.path.isfile(input_path):
        return {"ok": False, "error": f"input not exists: {input_path}"}

    # 输出路径
    if output_path is None:
        p = Path(input_path)
        output_path = str(p.with_name(p.stem + "_34" + p.suffix))

    # ★ 2026-04-20 配置化: GPU/CPU + crf
    if use_gpu is None:
        use_gpu = _cfg_bool("video.process.scale34.use_gpu", True)
    if crf is None:
        # NVENC cq 22 ≈ libx264 crf 23
        default_crf = 22 if use_gpu else 23
        crf = int(cfg_get("video.process.scale34.crf", default_crf))

    # 探测
    dims = _probe_video_size(input_path)
    if dims is None:
        return {"ok": False, "error": "probe failed"}
    in_w, in_h, in_dur = dims
    log.info("[scale34] 输入 %dx%d %.1fs → 输出 %dx%d (use_gpu=%s crf=%d)",
             in_w, in_h, in_dur, _W_OUT, _H_OUT, use_gpu, crf)

    # 构 filter_complex
    fc, final_label = _build_filter_complex(
        drama_name=drama_name,
        account_name=account_name,
        bottom_text=bottom_text or _DEFAULT_BOTTOM_TEXT,
        enable_dynamic_wm=enable_dynamic_watermark,
    )

    # ── 编码器参数分支 (GPU NVENC vs CPU libx264) ──
    if use_gpu:
        # NVENC 硬编: 快 10x, 质量对标 libx264 (cq 22 ≈ crf 23)
        # 注: NVENC 默认 VBR 可能爆码率, 要加 -b:v + -maxrate + -bufsize 控制
        target_kbps = int(cfg_get("video.process.target_bitrate_kbps", 2500))
        ffmpeg_bin = _ffmpeg_nvenc()
        codec_args = [
            "-c:v", "h264_nvenc",
            "-preset", "p4",              # p1=最快, p7=最高质量; p4 平衡
            "-rc", "vbr",
            "-cq", str(crf),              # 质量目标
            "-b:v", f"{target_kbps}k",
            "-maxrate", f"{target_kbps * 2}k",
            "-bufsize", f"{target_kbps * 4}k",
            "-profile:v", "high",
            "-pix_fmt", "yuv420p",
            "-bf", "2",                   # B-frames (NVENC 默认 0, 开 2 个改善压缩)
        ]
    else:
        # CPU libx264 (KS184 原版, 慢 10x 但质量基准)
        ffmpeg_bin = _ffmpeg_exe()
        codec_args = [
            "-c:v", "libx264", "-preset", "medium", "-crf", str(crf),
            "-pix_fmt", "yuv420p",
        ]

    cmd = [
        ffmpeg_bin, "-y",
        "-i", input_path,
        "-filter_complex", fc,
        "-map", final_label,
        "-map", "0:a?",
        "-threads", str(threads),
        *codec_args,
        "-c:a", "aac", "-b:a", "192k",
        output_path,
    ]

    t0 = time.time()
    log.info("[scale34] ffmpeg start: drama=%r account=%r dyn_wm=%s",
             drama_name, account_name, enable_dynamic_watermark)

    try:
        r = subprocess.run(
            cmd, capture_output=True, timeout=600,
            encoding="utf-8", errors="replace",
        )
    except subprocess.TimeoutExpired:
        return {"ok": False, "error": "ffmpeg_timeout"}
    except Exception as e:
        return {"ok": False, "error": f"ffmpeg_exception: {e}"}

    elapsed = time.time() - t0
    if r.returncode != 0:
        err_tail = (r.stderr or "")[-400:]
        log.error("[scale34] ffmpeg failed: %s", err_tail)
        return {"ok": False, "error": f"ffmpeg_err: {err_tail}",
                "elapsed_sec": round(elapsed, 1)}

    if not os.path.isfile(output_path) or os.path.getsize(output_path) < 1024:
        return {"ok": False, "error": "output missing or tiny"}

    out_size_mb = os.path.getsize(output_path) / 1024 / 1024
    in_size_mb = os.path.getsize(input_path) / 1024 / 1024
    log.info("[scale34] ✅ %.1fMB → %.1fMB in %.1fs (ratio=%.2f)",
             in_size_mb, out_size_mb, elapsed, out_size_mb / in_size_mb)

    return {
        "ok": True,
        "output_path": output_path,
        "input_size_mb": round(in_size_mb, 2),
        "output_size_mb": round(out_size_mb, 2),
        "input_w": in_w,
        "input_h": in_h,
        "output_w": _W_OUT,
        "output_h": _H_OUT,
        "duration_sec": in_dur,
        "elapsed_sec": round(elapsed, 1),
        "dynamic_watermark": enable_dynamic_watermark,
    }


# ═════════════════════════════════════════════════════════════════
# CLI
# ═════════════════════════════════════════════════════════════════
if __name__ == "__main__":
    import argparse, json, sys
    sys.stdout.reconfigure(encoding="utf-8")

    ap = argparse.ArgumentParser()
    ap.add_argument("--input", required=True)
    ap.add_argument("--drama", required=True)
    ap.add_argument("--account", required=True)
    ap.add_argument("--output", default=None)
    ap.add_argument("--bottom-text", default=None)
    ap.add_argument("--no-dyn-wm", action="store_true")
    ap.add_argument("--crf", type=int, default=23)
    args = ap.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")

    r = process_scale34_video(
        args.input, args.drama, args.account,
        output_path=args.output,
        bottom_text=args.bottom_text,
        enable_dynamic_watermark=not args.no_dyn_wm,
        crf=args.crf,
    )
    print(json.dumps(r, ensure_ascii=False, indent=2, default=str))
    sys.exit(0 if r.get("ok") else 1)
