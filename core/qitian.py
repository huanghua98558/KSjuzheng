# -*- coding: utf-8 -*-
"""齐天 (qitian) 图片模式 — 6 种 PIL 风格生成.

对齐 KS184 Q_X64 反编译文档 §8.3:
    图片生成模式 ('random_pattern'随机字符, 'frame_based'视频帧变换, 'yemao_rotate' 马赛克旋转)
    出图模式: qitian_art / gradient_random / random_shapes /
              mosaic_rotate / frame_transform / random_chars

用法 (独立 PIL, 不依赖 ffmpeg, 输出 PNG/JPG):

    from core.qitian import generate, AVAILABLE_STYLES

    out_path = generate(
        style="qitian_art",
        drama_name="小小武神不好惹",
        account_name="思莱短剧",
        output_path="/tmp/cover.png",
        video_path=None,   # frame_transform 需要
    )

所有风格:
    1. qitian_art       — 抽象艺术 (多层渐变 + 随机几何 + 散点光斑)
    2. gradient_random  — 纯双色渐变 + 大字
    3. random_shapes    — 随机几何阵列
    4. mosaic_rotate    — 马赛克旋转 (yemao_rotate 对应, 用视频抽帧)
    5. frame_transform  — 视频单帧变换 (滤镜 + 文字)
    6. random_chars     — 随机字符阵列 (KS184 random_pattern)
"""
from __future__ import annotations

import logging
import math
import random
import string
import subprocess
from pathlib import Path
from typing import Any

log = logging.getLogger(__name__)

# ── 默认尺寸 (对齐快手 cover 3:4 竖屏) ──
DEFAULT_W = 720
DEFAULT_H = 960  # 3:4 比例

# ── 字体 ──
FONT_MSYH = r"C:\Windows\Fonts\msyh.ttc"
FONT_MSYH_BD = r"C:\Windows\Fonts\msyhbd.ttc"

AVAILABLE_STYLES = [
    "qitian_art",
    "gradient_random",
    "random_shapes",
    "mosaic_rotate",
    "frame_transform",
    "random_chars",
]


# ══════════════════════════════════════════════════════════════
# 工具函数
# ══════════════════════════════════════════════════════════════

def _load_font(size: int, bold: bool = True):
    from PIL import ImageFont
    path = FONT_MSYH_BD if bold else FONT_MSYH
    try:
        return ImageFont.truetype(path, size)
    except Exception:
        try:
            return ImageFont.truetype(FONT_MSYH, size)
        except Exception:
            return ImageFont.load_default()


def _random_dark_color() -> tuple[int, int, int]:
    """深色 (背景用)."""
    return (random.randint(20, 80), random.randint(20, 80),
             random.randint(20, 80))


def _random_bright_color() -> tuple[int, int, int]:
    """鲜艳色 (强调用)."""
    palettes = [
        (255, 87, 87),   # 红
        (255, 195, 0),   # 金
        (72, 219, 251),  # 青
        (162, 155, 254), # 紫
        (55, 224, 161),  # 绿
        (255, 165, 111), # 橙
    ]
    return random.choice(palettes)


def _linear_gradient(img, top_color, bottom_color) -> None:
    """填充垂直线性渐变 (in-place)."""
    w, h = img.size
    for y in range(h):
        t = y / h
        r = int(top_color[0] * (1 - t) + bottom_color[0] * t)
        g = int(top_color[1] * (1 - t) + bottom_color[1] * t)
        b = int(top_color[2] * (1 - t) + bottom_color[2] * t)
        for x in range(w):
            img.putpixel((x, y), (r, g, b))


def _linear_gradient_fast(w, h, top_color, bottom_color):
    """快速生成渐变 (用 numpy 如可用)."""
    try:
        import numpy as np
        from PIL import Image
        grad = np.zeros((h, w, 3), dtype=np.uint8)
        for y in range(h):
            t = y / h
            grad[y, :, 0] = int(top_color[0] * (1 - t) + bottom_color[0] * t)
            grad[y, :, 1] = int(top_color[1] * (1 - t) + bottom_color[1] * t)
            grad[y, :, 2] = int(top_color[2] * (1 - t) + bottom_color[2] * t)
        return Image.fromarray(grad, "RGB")
    except ImportError:
        from PIL import Image
        img = Image.new("RGB", (w, h))
        _linear_gradient(img, top_color, bottom_color)
        return img


def _draw_text_centered_with_border(draw, text, center_xy, font,
                                      fill, border=4, border_fill=(0, 0, 0)):
    """中心对齐文字, 带黑描边."""
    x, y = center_xy
    # 用 textbbox 拿尺寸
    try:
        bbox = draw.textbbox((0, 0), text, font=font)
        tw = bbox[2] - bbox[0]
        th = bbox[3] - bbox[1]
    except Exception:
        tw = th = 0

    tx = x - tw // 2
    ty = y - th // 2

    # 描边
    for dx in range(-border, border + 1):
        for dy in range(-border, border + 1):
            if dx or dy:
                draw.text((tx + dx, ty + dy), text, font=font, fill=border_fill)
    # 正文
    draw.text((tx, ty), text, font=font, fill=fill)


# ══════════════════════════════════════════════════════════════
# 6 种风格
# ══════════════════════════════════════════════════════════════

def _gen_qitian_art(drama_name: str, account_name: str,
                     w: int = DEFAULT_W, h: int = DEFAULT_H) -> "Image.Image":
    """1. 齐天艺术 — 多层渐变 + 几何 + 散点光斑 + 剧名."""
    from PIL import Image, ImageDraw, ImageFilter

    # 深色渐变背景
    c1 = _random_dark_color()
    c2 = _random_dark_color()
    img = _linear_gradient_fast(w, h, c1, c2)
    img = img.convert("RGBA")
    draw = ImageDraw.Draw(img, "RGBA")

    # 几何形状 (6-10 个)
    for _ in range(random.randint(6, 10)):
        shape = random.choice(["triangle", "rect", "circle"])
        col = _random_bright_color() + (random.randint(60, 140),)  # 半透明
        if shape == "circle":
            cx, cy = random.randint(0, w), random.randint(0, h)
            r = random.randint(60, 200)
            draw.ellipse((cx - r, cy - r, cx + r, cy + r), fill=col)
        elif shape == "rect":
            x0, y0 = random.randint(0, w), random.randint(0, h)
            x1, y1 = x0 + random.randint(80, 300), y0 + random.randint(80, 300)
            draw.rectangle((x0, y0, x1, y1), fill=col)
        else:
            pts = [(random.randint(0, w), random.randint(0, h)) for _ in range(3)]
            draw.polygon(pts, fill=col)

    # 散点光斑
    for _ in range(random.randint(30, 50)):
        cx, cy = random.randint(0, w), random.randint(0, h)
        r = random.randint(3, 15)
        col = (random.randint(200, 255), random.randint(200, 255),
               random.randint(200, 255), random.randint(100, 200))
        draw.ellipse((cx - r, cy - r, cx + r, cy + r), fill=col)

    # 轻度模糊让叠加柔和
    img = img.filter(ImageFilter.GaussianBlur(radius=1.2))

    # 剧名 (大字居中)
    draw = ImageDraw.Draw(img)
    font_big = _load_font(72, bold=True)
    _draw_text_centered_with_border(
        draw, drama_name, (w // 2, h // 2 - 40),
        font_big, fill=(255, 255, 255), border=5,
    )

    # 账号小字 (右下)
    font_small = _load_font(24)
    draw.text((w - 180, h - 50), f"@{account_name}", font=font_small,
               fill=(255, 255, 255, 220))

    return img.convert("RGB")


def _gen_gradient_random(drama_name: str, account_name: str,
                          w: int = DEFAULT_W, h: int = DEFAULT_H) -> "Image.Image":
    """2. 纯渐变 + 大字 (极简)."""
    from PIL import ImageDraw

    c_top = _random_bright_color()
    c_bot = tuple(max(0, c - 100) for c in c_top)  # 同色系暗
    img = _linear_gradient_fast(w, h, c_top, c_bot)
    draw = ImageDraw.Draw(img)

    font_big = _load_font(80, bold=True)
    _draw_text_centered_with_border(
        draw, drama_name, (w // 2, h // 2),
        font_big, fill=(255, 255, 255), border=6,
    )

    font_small = _load_font(26)
    draw.text((w - 200, h - 55), f"@{account_name}", font=font_small,
               fill=(255, 255, 255))
    return img


def _gen_random_shapes(drama_name: str, account_name: str,
                        w: int = DEFAULT_W, h: int = DEFAULT_H) -> "Image.Image":
    """3. 随机几何阵列 (紧凑 grid)."""
    from PIL import Image, ImageDraw

    img = Image.new("RGB", (w, h), _random_dark_color())
    draw = ImageDraw.Draw(img, "RGBA")

    # 4×6 grid cells
    cell_w = w // 4
    cell_h = h // 6
    for row in range(6):
        for col in range(4):
            x0 = col * cell_w + random.randint(5, 15)
            y0 = row * cell_h + random.randint(5, 15)
            x1 = x0 + cell_w - random.randint(10, 30)
            y1 = y0 + cell_h - random.randint(10, 30)
            shape = random.choice(["rect", "circle", "triangle"])
            color = _random_bright_color() + (random.randint(150, 220),)
            if shape == "rect":
                draw.rectangle((x0, y0, x1, y1), fill=color)
            elif shape == "circle":
                draw.ellipse((x0, y0, x1, y1), fill=color)
            else:
                draw.polygon([(x0, y1), ((x0 + x1) // 2, y0), (x1, y1)], fill=color)

    # 剧名 (居中偏上)
    font = _load_font(60, bold=True)
    _draw_text_centered_with_border(
        draw, drama_name, (w // 2, h // 3),
        font, fill=(255, 255, 255), border=5,
    )

    # 账号 右下
    font_small = _load_font(24)
    draw.text((w - 200, h - 50), f"@{account_name}", font=font_small,
               fill=(255, 255, 255))
    return img.convert("RGB")


def _gen_mosaic_rotate(drama_name: str, account_name: str,
                        video_path: str | None = None,
                        w: int = DEFAULT_W, h: int = DEFAULT_H) -> "Image.Image":
    """4. 马赛克旋转 (yemao_rotate 对应). 用视频抽 9 帧, 随机裁剪+旋转 3×3 拼."""
    from PIL import Image, ImageDraw

    if video_path and Path(video_path).exists():
        frames = _extract_video_frames(video_path, 9)
    else:
        # 无视频时用几何块 fallback
        frames = [_make_random_block(w // 3, h // 3) for _ in range(9)]

    img = Image.new("RGB", (w, h), (0, 0, 0))
    cell_w = w // 3
    cell_h = h // 3
    for i, frame in enumerate(frames[:9]):
        row, col = i // 3, i % 3
        # 随机旋转 ±15°
        angle = random.uniform(-15, 15)
        frame = frame.convert("RGBA")
        # Resize 到 cell 大小然后稍微放大 (防旋转后黑边)
        crop_w = int(cell_w * 1.2)
        crop_h = int(cell_h * 1.2)
        frame = frame.resize((crop_w, crop_h), Image.LANCZOS)
        frame = frame.rotate(angle, resample=Image.BICUBIC, expand=False)
        # 中心 crop 到 cell_w × cell_h
        cx, cy = frame.size[0] // 2, frame.size[1] // 2
        frame = frame.crop((cx - cell_w // 2, cy - cell_h // 2,
                              cx + cell_w // 2, cy + cell_h // 2))
        img.paste(frame, (col * cell_w, row * cell_h), frame)

    draw = ImageDraw.Draw(img)
    # 半透明黑条 (让文字可见)
    overlay = Image.new("RGBA", (w, 120), (0, 0, 0, 120))
    img.paste(overlay, (0, h // 2 - 60), overlay)

    draw = ImageDraw.Draw(img)
    font = _load_font(56, bold=True)
    _draw_text_centered_with_border(
        draw, drama_name, (w // 2, h // 2),
        font, fill=(255, 255, 255), border=4,
    )

    font_small = _load_font(22)
    draw.text((w - 180, h - 45), f"@{account_name}", font=font_small,
               fill=(255, 255, 255))
    return img


def _gen_frame_transform(drama_name: str, account_name: str,
                           video_path: str | None = None,
                           w: int = DEFAULT_W, h: int = DEFAULT_H) -> "Image.Image":
    """5. 视频帧变换 (抽 1 帧做滤镜 + 调色)."""
    from PIL import Image, ImageDraw, ImageEnhance, ImageFilter

    if video_path and Path(video_path).exists():
        frames = _extract_video_frames(video_path, 1)
        if frames:
            img = frames[0]
        else:
            img = _linear_gradient_fast(w, h, _random_dark_color(),
                                          _random_dark_color())
    else:
        img = _linear_gradient_fast(w, h, _random_dark_color(),
                                      _random_dark_color())

    img = img.resize((w, h), Image.LANCZOS).convert("RGB")

    # 滤镜叠加: blur / posterize / saturation boost 随机选
    effect = random.choice(["blur", "saturate", "darken"])
    if effect == "blur":
        img = img.filter(ImageFilter.GaussianBlur(radius=4))
    elif effect == "saturate":
        img = ImageEnhance.Color(img).enhance(1.8)
        img = ImageEnhance.Contrast(img).enhance(1.3)
    else:  # darken
        img = ImageEnhance.Brightness(img).enhance(0.5)

    # 文字
    draw = ImageDraw.Draw(img)
    font = _load_font(72, bold=True)
    _draw_text_centered_with_border(
        draw, drama_name, (w // 2, h // 2),
        font, fill=(255, 255, 255), border=5,
    )
    font_small = _load_font(24)
    draw.text((w - 200, h - 50), f"@{account_name}", font=font_small,
               fill=(255, 255, 255))
    return img


def _gen_random_chars(drama_name: str, account_name: str,
                       w: int = DEFAULT_W, h: int = DEFAULT_H) -> "Image.Image":
    """6. 随机字符阵列 (random_pattern)."""
    from PIL import Image, ImageDraw

    c = _random_dark_color()
    img = Image.new("RGB", (w, h), c)
    draw = ImageDraw.Draw(img, "RGBA")

    # 背景铺满随机字符
    chars_pool = string.ascii_letters + string.digits + "·•★☆♦✦✧"
    font_bg = _load_font(30)
    for y in range(0, h, 36):
        for x in range(0, w, 36):
            ch = random.choice(chars_pool)
            col = _random_bright_color() + (random.randint(60, 160),)
            draw.text((x + random.randint(-5, 5),
                         y + random.randint(-5, 5)),
                        ch, font=font_bg, fill=col)

    # 半透明黑框 + 剧名
    band_h = 180
    overlay = Image.new("RGBA", (w, band_h), (0, 0, 0, 180))
    img.paste(overlay, (0, h // 2 - band_h // 2), overlay)

    draw = ImageDraw.Draw(img)
    font = _load_font(64, bold=True)
    _draw_text_centered_with_border(
        draw, drama_name, (w // 2, h // 2),
        font, fill=(255, 255, 255), border=5,
    )

    font_small = _load_font(24)
    draw.text((w - 200, h - 50), f"@{account_name}", font=font_small,
               fill=(255, 255, 255))
    return img


# ══════════════════════════════════════════════════════════════
# 视频抽帧助手
# ══════════════════════════════════════════════════════════════

def _extract_video_frames(video_path: str, n: int = 9) -> list["Image.Image"]:
    """用 ffmpeg 从视频均匀抽 n 帧, 返回 PIL Image list."""
    from PIL import Image
    import tempfile
    import os

    # 探测时长
    try:
        from core.processor import _probe_duration
        dur = _probe_duration(video_path) or 60
    except Exception:
        dur = 60

    # 抽帧时间点
    if n == 1:
        points = [dur * 0.5]
    else:
        points = [dur * (i + 0.5) / n for i in range(n)]

    from core.processor import _get_ffmpeg_exe
    ffmpeg = _get_ffmpeg_exe()
    tmp_dir = tempfile.mkdtemp(prefix="qitian_frames_")
    frames = []
    try:
        for i, t in enumerate(points):
            out_path = os.path.join(tmp_dir, f"frame_{i}.jpg")
            cmd = [ffmpeg, "-y", "-ss", f"{t:.3f}", "-i", video_path,
                   "-frames:v", "1", "-q:v", "3", out_path]
            r = subprocess.run(cmd, capture_output=True, timeout=15)
            if r.returncode == 0 and os.path.isfile(out_path):
                try:
                    frames.append(Image.open(out_path).copy())
                except Exception:
                    pass
    finally:
        # 清理临时目录
        import shutil
        try:
            shutil.rmtree(tmp_dir, ignore_errors=True)
        except Exception:
            pass
    return frames


def _make_random_block(w: int, h: int) -> "Image.Image":
    """生成随机色块 (fallback 无视频时)."""
    from PIL import Image, ImageDraw
    img = Image.new("RGB", (w, h), _random_bright_color())
    draw = ImageDraw.Draw(img, "RGBA")
    for _ in range(3):
        shape = random.choice(["rect", "circle"])
        col = _random_bright_color() + (150,)
        if shape == "rect":
            x0, y0 = random.randint(0, w), random.randint(0, h)
            x1, y1 = x0 + random.randint(30, 100), y0 + random.randint(30, 100)
            draw.rectangle((x0, y0, x1, y1), fill=col)
        else:
            cx, cy = random.randint(0, w), random.randint(0, h)
            r = random.randint(20, 60)
            draw.ellipse((cx - r, cy - r, cx + r, cy + r), fill=col)
    return img


# ══════════════════════════════════════════════════════════════
# 主入口
# ══════════════════════════════════════════════════════════════

_GENERATORS = {
    "qitian_art":       _gen_qitian_art,
    "gradient_random":  _gen_gradient_random,
    "random_shapes":    _gen_random_shapes,
    "mosaic_rotate":    _gen_mosaic_rotate,
    "frame_transform":  _gen_frame_transform,
    "random_chars":     _gen_random_chars,
}


def generate(
    style: str,
    drama_name: str,
    account_name: str,
    output_path: str,
    video_path: str | None = None,
    width: int = DEFAULT_W,
    height: int = DEFAULT_H,
    quality: int = 95,
) -> dict[str, Any]:
    """生成一张 qitian 图片.

    Args:
        style: 6 种风格之一
        drama_name, account_name: 文字内容
        output_path: PNG/JPG 输出路径
        video_path: mosaic_rotate / frame_transform 需要
        width, height: 尺寸
        quality: JPG quality (PNG 忽略)

    Returns:
        {ok, output_path, style, width, height, size_kb, error?}
    """
    import time
    if style not in _GENERATORS:
        return {"ok": False,
                "error": f"unknown style: {style}, available: {AVAILABLE_STYLES}"}

    fn = _GENERATORS[style]
    t0 = time.time()
    try:
        # 根据签名分发
        if style in ("mosaic_rotate", "frame_transform"):
            img = fn(drama_name, account_name,
                      video_path=video_path, w=width, h=height)
        else:
            img = fn(drama_name, account_name, w=width, h=height)
    except Exception as e:
        import traceback
        return {"ok": False, "error": f"{type(e).__name__}: {e}",
                "traceback": traceback.format_exc()[:500]}

    # 保存
    Path(output_path).parent.mkdir(parents=True, exist_ok=True)
    ext = Path(output_path).suffix.lower()
    if ext in (".jpg", ".jpeg"):
        img.save(output_path, "JPEG", quality=quality, optimize=True)
    else:
        img.save(output_path, "PNG", optimize=True)

    elapsed = time.time() - t0
    size_kb = Path(output_path).stat().st_size / 1024

    log.info("[qitian] %s → %s (%.1fKB, %.2fs)",
             style, output_path, size_kb, elapsed)

    return {
        "ok": True,
        "output_path": output_path,
        "style": style,
        "width": width, "height": height,
        "size_kb": round(size_kb, 1),
        "elapsed_sec": round(elapsed, 2),
    }


# ══════════════════════════════════════════════════════════════
# CLI
# ══════════════════════════════════════════════════════════════

if __name__ == "__main__":
    import argparse, json, sys
    sys.stdout.reconfigure(encoding="utf-8")
    logging.basicConfig(level=logging.INFO, format="[%(asctime)s] %(message)s")

    ap = argparse.ArgumentParser()
    ap.add_argument("--style", required=True,
                    choices=AVAILABLE_STYLES + ["all"],
                    help="6 种风格之一, 或 all 一次生成全部")
    ap.add_argument("--drama", default="小小武神不好惹")
    ap.add_argument("--account", default="思莱短剧")
    ap.add_argument("--output", default=None,
                    help="输出路径 (单 style) 或目录 (all)")
    ap.add_argument("--video", default=None,
                    help="视频路径 (mosaic_rotate / frame_transform 需要)")
    ap.add_argument("--width", type=int, default=DEFAULT_W)
    ap.add_argument("--height", type=int, default=DEFAULT_H)
    args = ap.parse_args()

    if args.style == "all":
        out_dir = args.output or "qitian_samples"
        Path(out_dir).mkdir(exist_ok=True)
        results = {}
        for style in AVAILABLE_STYLES:
            out_path = str(Path(out_dir) / f"{style}.png")
            r = generate(style=style, drama_name=args.drama,
                          account_name=args.account,
                          output_path=out_path, video_path=args.video,
                          width=args.width, height=args.height)
            results[style] = r
        print(json.dumps(results, ensure_ascii=False, indent=2, default=str))
    else:
        out_path = args.output or f"qitian_{args.style}.png"
        r = generate(style=args.style, drama_name=args.drama,
                      account_name=args.account,
                      output_path=out_path, video_path=args.video,
                      width=args.width, height=args.height)
        print(json.dumps(r, ensure_ascii=False, indent=2, default=str))
