# -*- coding: utf-8 -*-
"""Pattern 素材动画生成器 — 对齐 KS184 UI "动画效果 7 选 N".

对齐 UI (v3 Canonical):
  ☐ 放大 (zoom_in)
  ☐ 缩小 (zoom_out)
  ☐ 脉冲 (zoom_pulse)   ← KS184 内部叫 zoom_pulse, 不是 pulse
  ☐ 右移 (pan_right)
  ☐ 左移 (pan_left)
  ☐ 顺转 (rotate_cw)
  ☐ 逆转 (rotate_ccw)

这些动画决定**pattern PNG 转成 zoompan aux.mp4 时的视觉运动方式**.
至尊/麒麟/荣耀的 step4 (zoompan aux) 都可以选这些.
透明叠加 mode3 的 animations list 也用这 7 个.

### 公式来源
全部从 KS184 `Qx64_pid6844_full.dmp` memory dump 里扫出来的原文公式
(非猜测, 详见 `KS184_下载剪辑去重_Canonical参考v3.md` §1).

用法:
    from core.pattern_animator import get_animation_filter

    vf = get_animation_filter("zoom_in", width=720, height=1280,
                                 duration=10, fps=30)

    # 或随机选 N 个 (AI planner 驱动)
    from core.pattern_animator import pick_animations
    anims = pick_animations(n=3, pool=None)  # 随机 3 个
"""
from __future__ import annotations

import logging
import random
from typing import Any

log = logging.getLogger(__name__)


# KS184 Canonical v3: zoom_pulse (不是 pulse!)
AVAILABLE_ANIMATIONS = [
    "zoom_in",       # 放大
    "zoom_out",      # 缩小
    "zoom_pulse",    # 脉冲 (sin 呼吸, 周期 4 秒)
    "pan_right",     # 右移
    "pan_left",      # 左移
    "rotate_cw",     # 顺转
    "rotate_ccw",    # 逆转
]

# 兼容旧代码: "pulse" 作为 zoom_pulse 的 alias
_ANIMATION_ALIASES = {
    "pulse": "zoom_pulse",
}

ANIMATION_CN_NAMES = {
    "zoom_in":     "放大",
    "zoom_out":    "缩小",
    "zoom_pulse":  "脉冲",
    "pan_right":   "右移",
    "pan_left":    "左移",
    "rotate_cw":   "顺转",
    "rotate_ccw":  "逆转",
}


def _resolve_name(animation: str) -> str:
    """把旧名 "pulse" 映射到新名 "zoom_pulse"."""
    return _ANIMATION_ALIASES.get(animation, animation)


def get_animation_filter(
    animation: str,
    width: int = 720,
    height: int = 1280,
    duration: float = 10.0,
    fps: int = 30,
    zoom_max: float = 1.5,
    rotate_period: float | None = None,
) -> str:
    """获取指定动画的 ffmpeg filter 字符串 (对齐 KS184 Canonical v3).

    输入: pattern PNG (loop 静态)
    输出: 动态视频 filter (zoompan / crop / rotate)

    Args:
        animation: 7 种之一 ("pulse" 自动映射到 "zoom_pulse")
        width/height: 目标尺寸 (KS184 默认 720x1280)
        duration: 视频时长秒
        fps: 帧率
        zoom_max: 最大缩放倍数 (放大/缩小用, KS184 默认 1.5)
        rotate_period: 旋转周期秒 (默认 = duration, 即整视频转 π/2=90°)

    Returns:
        filter 字符串, 用于 ffmpeg -vf 或 filter_complex.
        所有 filter 都以 scale+crop 开头保证输出 size.
    """
    animation = _resolve_name(animation)
    total_frames = int(duration * fps)
    s = f"{width}x{height}"

    # 共通的 scale + crop (保 size)
    scale_crop = (f"scale={width}:{height}:force_original_aspect_ratio=increase,"
                   f"crop={width}:{height},")

    if animation == "zoom_in":
        # KS184 原文: zoompan=z='min(zoom+0.001,1.5)':d=750:x=...:y=...:s=720x1280
        # 系数 0.001 (非 0.0015!), d = total_frames (非固定 750)
        return (
            scale_crop +
            f"zoompan=z='min(zoom+0.001,{zoom_max})':"
            f"d={total_frames}:"
            f"x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':"
            f"s={s},fps={fps}"
        )

    if animation == "zoom_out":
        # KS184 原文: zoompan=z='max(1.5-zoom*0.001,1.0)':d=1:...
        # 从 1.5 渐降, d=1 每帧重算
        return (
            scale_crop +
            f"zoompan=z='max({zoom_max}-zoom*0.001,1.0)':"
            f"d=1:"
            f"x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':"
            f"s={s},fps={fps}"
        )

    if animation == "zoom_pulse":
        # KS184 dump 原文用 t, 但 ffmpeg zoompan 只支持 on (帧号).
        # 等价公式: 周期 4 秒 = 4*fps 帧, sin(2π * on / (4*fps))
        # 范围 1.15 ± 0.15 = [1.0, 1.3]
        period_frames = 4 * fps
        return (
            scale_crop +
            f"zoompan=z='1.15+0.15*sin(2*3.14159265359*on/{period_frames})':"
            f"d=1:"
            f"x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':"
            f"s={s},fps={fps}"
        )

    if animation == "pan_right":
        # KS184 原文: crop=<w>:<h>:x='t/<T>*<max_x>':y=0
        # 不是 zoompan! 是 crop 的 x 用 t 线性表达式.
        # 预先 scale 到 2 倍宽做 pan 素材 (pan_w = 2*width)
        pan_w = int(width * 1.5)
        max_x = pan_w - width
        T = duration
        return (
            f"scale={pan_w}:{height}:force_original_aspect_ratio=increase,"
            f"crop={width}:{height}:x='t/{T}*{max_x}':y=0,"
            f"fps={fps}"
        )

    if animation == "pan_left":
        # KS184 原文: crop=<w>:<h>:x='<max_x>-t/<T>*<max_x>':y=0
        pan_w = int(width * 1.5)
        max_x = pan_w - width
        T = duration
        return (
            f"scale={pan_w}:{height}:force_original_aspect_ratio=increase,"
            f"crop={width}:{height}:x='{max_x}-t/{T}*{max_x}':y=0,"
            f"fps={fps}"
        )

    if animation == "rotate_cw":
        # KS184 原文: rotate=a='2*3.14159265359*t/<T>/4':c=none:ow=<w>:oh=<h>
        # 速度 2π/T/4 = π/(2T) rad/s, T 秒转 π/2 (90°)
        T = rotate_period if rotate_period else duration
        return (
            scale_crop +
            f"fps={fps},"
            f"rotate=a='2*3.14159265359*t/{T}/4':c=none:"
            f"ow={width}:oh={height}"
        )

    if animation == "rotate_ccw":
        # KS184 原文: rotate=a='-2*3.14159265359*t/<T>/4':c=none:ow=<w>:oh=<h>
        T = rotate_period if rotate_period else duration
        return (
            scale_crop +
            f"fps={fps},"
            f"rotate=a='-2*3.14159265359*t/{T}/4':c=none:"
            f"ow={width}:oh={height}"
        )

    # Unknown — fallback 默认 zoom_in
    log.warning("[animator] unknown animation=%s, fallback zoom_in", animation)
    return get_animation_filter("zoom_in", width, height, duration, fps,
                                 zoom_max)


def pick_animations(
    n: int = 1,
    pool: list[str] | None = None,
    seed: int | None = None,
) -> list[str]:
    """随机选 N 个动画.

    Args:
        n: 选几个 (≥1)
        pool: 候选池 (None = 全部 7 种)
        seed: 随机种子 (测试用)

    Returns:
        选中的 animation 名 list
    """
    if seed is not None:
        random.seed(seed)
    candidates = pool or AVAILABLE_ANIMATIONS
    n = max(1, min(n, len(candidates)))
    return random.sample(candidates, n)


def resolve_animations_from_config() -> list[str]:
    """从 app_config 读启用的动画 (UI "动画效果" 多选).

    支持 4 种 config 格式:
      video.process.animations = "zoom_in,pan_right"    (逗号分隔)
      video.process.animations = "*"                     (全 7 种)
      video.process.animations = "random:2"              (随机 2 个)
      video.process.animations = ""                      (无动画, fallback zoom_in)

    **同时** 也会读 7 个独立 bool 开关 (UI checkbox 对齐):
      video.process.mode3.overlay_anim_zoom_in   (bool)
      video.process.mode3.overlay_anim_zoom_out
      video.process.mode3.overlay_anim_zoom_pulse
      video.process.mode3.overlay_anim_pan_left
      video.process.mode3.overlay_anim_pan_right
      video.process.mode3.overlay_anim_rotate_cw
      video.process.mode3.overlay_anim_rotate_ccw

    如果 bool 开关存在且至少有一个 True, 优先用 bool 开关结果.
    否则用 animations 字符串.
    """
    from core.app_config import get as cfg_get

    # 优先读 7 个独立 bool checkbox (对齐 KS184 UI)
    bool_keys = {
        "zoom_in":    "video.process.mode3.overlay_anim_zoom_in",
        "zoom_out":   "video.process.mode3.overlay_anim_zoom_out",
        "zoom_pulse": "video.process.mode3.overlay_anim_zoom_pulse",
        "pan_left":   "video.process.mode3.overlay_anim_pan_left",
        "pan_right":  "video.process.mode3.overlay_anim_pan_right",
        "rotate_cw":  "video.process.mode3.overlay_anim_rotate_cw",
        "rotate_ccw": "video.process.mode3.overlay_anim_rotate_ccw",
    }
    def _to_bool(v):
        if isinstance(v, bool):
            return v
        if isinstance(v, str):
            return v.strip().lower() in ("true", "1", "yes", "on")
        if v is None:
            return None
        return bool(v)

    enabled: list[str] = []
    any_set = False
    for anim, key in bool_keys.items():
        try:
            v = cfg_get(key, None)
            if v is None:
                continue
            any_set = True
            if _to_bool(v):
                enabled.append(anim)
        except Exception:
            pass
    if any_set and enabled:
        return enabled

    # Fallback: animations 字符串
    v = cfg_get("video.process.animations", "zoom_in")
    if not v or not isinstance(v, str):
        return ["zoom_in"]
    v = v.strip()

    if v == "*":
        return list(AVAILABLE_ANIMATIONS)

    if v.startswith("random:"):
        try:
            n = int(v.split(":", 1)[1])
            return pick_animations(n)
        except Exception:
            return ["zoom_in"]

    # 逗号分隔
    parts = [p.strip() for p in v.split(",") if p.strip()]
    # 把 "pulse" 老名映射成 "zoom_pulse"
    parts = [_resolve_name(p) for p in parts]
    valid = [p for p in parts if p in AVAILABLE_ANIMATIONS]
    if not valid:
        return ["zoom_in"]
    return valid


def describe(animation: str) -> str:
    """动画名中文描述."""
    animation = _resolve_name(animation)
    return ANIMATION_CN_NAMES.get(animation, animation)


if __name__ == "__main__":
    import argparse, sys
    sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser()
    ap.add_argument("--list", action="store_true")
    ap.add_argument("--filter", type=str, help="预览 filter 字符串")
    ap.add_argument("--pick", type=int, default=None, help="随机选 N 个")
    args = ap.parse_args()

    if args.list:
        print("7 种动画 (对齐 KS184 Canonical v3):")
        for a in AVAILABLE_ANIMATIONS:
            print(f"  {a:12s} ({describe(a)})")
    elif args.filter:
        print(f"=== {args.filter} ({describe(args.filter)}) ===")
        print(get_animation_filter(args.filter, 720, 1280, 10, 30))
    elif args.pick:
        picked = pick_animations(args.pick)
        print(f"随机选 {args.pick}: {picked}")
        print(f"中文: {[describe(p) for p in picked]}")
    else:
        ap.print_help()
