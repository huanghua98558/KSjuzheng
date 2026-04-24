# -*- coding: utf-8 -*-
"""字体池 + 随机选择器.

对齐 KS184 "字体 auto" 功能. 8 个艺术字体从 KS184/fonts/ 复制来.

用法:
    from core.font_pool import pick_font, FONT_POOL

    path = pick_font()                    # 随机选一个 (默认)
    path = pick_font(style="bold")        # 优先选粗体
    path = pick_font(name="ziHun")        # 模糊匹配
    path = pick_font(explicit="msyh.ttc") # 强制系统字体

配置 app_config:
    watermark.font.mode      = "random" | "fixed" | "system"
    watermark.font.explicit  = "msyh.ttc"  (当 mode=fixed 时)
    watermark.font.prefer_bold = false
"""
from __future__ import annotations

import logging
import os
import random
from pathlib import Path

log = logging.getLogger(__name__)


# ── 字体池根目录 ──
FONTS_DIR = Path(r"D:\ks_automation\assets\fonts")

# ── Windows 系统字体 fallback ──
SYSTEM_FONTS = {
    "msyh":    r"C:\Windows\Fonts\msyh.ttc",       # 微软雅黑
    "msyhbd":  r"C:\Windows\Fonts\msyhbd.ttc",     # 微软雅黑粗
    "simhei":  r"C:\Windows\Fonts\simhei.ttf",     # 黑体
    "simsun":  r"C:\Windows\Fonts\simsun.ttc",     # 宋体
    "simkai":  r"C:\Windows\Fonts\simkai.ttf",     # 楷体
}


def _scan_fonts() -> list[Path]:
    """扫描 FONTS_DIR 所有 ttf/ttc/otf 文件 (Windows 大小写去重)."""
    if not FONTS_DIR.exists():
        return []
    seen: set[str] = set()
    out = []
    for ext in ("*.ttf", "*.ttc", "*.otf"):
        for p in FONTS_DIR.glob(ext):
            key = str(p).lower()
            if key in seen:
                continue
            seen.add(key)
            out.append(p)
    return sorted(out, key=lambda p: p.name.lower())


# 初始化时扫描
FONT_POOL: list[Path] = _scan_fonts()


def list_fonts() -> list[str]:
    """列出所有可用字体的路径 (str)."""
    return [str(p) for p in FONT_POOL]


def refresh_pool() -> int:
    """重新扫描字体目录 (Dashboard '刷新字体' 按钮调这个).

    Returns: 当前字体池大小.
    """
    global FONT_POOL
    FONT_POOL = _scan_fonts()
    log.info("[font_pool] 刷新: %d 个字体", len(FONT_POOL))
    return len(FONT_POOL)


def _is_drawtext_safe(path: Path) -> bool:
    """ffmpeg drawtext 的 fontfile 参数对特殊字符敏感, 过滤只保留纯 ASCII 文件名.
    (括号 / 中文 / 空格都会让 drawtext 报 'Fontconfig error').
    """
    name = path.name
    if not name.isascii():
        return False
    if any(c in name for c in "() "):
        return False
    return True


def pick_font(
    mode: str = "random",
    name: str | None = None,
    explicit: str | None = None,
    prefer_bold: bool = False,
    drawtext_safe: bool = True,
) -> str:
    """选字体.

    Args:
        mode: "random" / "fixed" / "system"
        name: 模糊匹配子串 (仅 mode="random" 时)
        explicit: 强制指定路径或系统字体 key (mode=fixed 时必填)
        prefer_bold: 优先选粗体系列 (有 "bd", "bold", "heavy" 字样)

    Returns:
        ffmpeg 可用的字体路径 (Windows 用 / 斜杠, C: 前加 \\:)
    """
    if mode == "fixed" and explicit:
        # 支持系统 key (如 'msyh')
        if explicit in SYSTEM_FONTS:
            return SYSTEM_FONTS[explicit]
        # 支持绝对路径
        if os.path.isfile(explicit):
            return explicit
        # 降级
        log.warning("[font_pool] fixed font not found: %s, fall back random",
                     explicit)

    if mode == "system":
        # 系统字体之一
        keys = list(SYSTEM_FONTS.keys())
        if prefer_bold:
            keys = [k for k in keys if "bd" in k] or keys
        return SYSTEM_FONTS[random.choice(keys)]

    # random (default)
    if not FONT_POOL:
        log.warning("[font_pool] 池空, 用系统 msyh")
        return SYSTEM_FONTS["msyh"]

    # 模糊匹配
    pool = FONT_POOL
    if name:
        filtered = [p for p in pool if name.lower() in p.name.lower()]
        if filtered:
            pool = filtered

    # drawtext-safe 过滤 (默认开, 因为 drawtext 不接受括号/中文文件名)
    if drawtext_safe:
        safe = [p for p in pool if _is_drawtext_safe(p)]
        if safe:
            pool = safe
        else:
            log.warning("[font_pool] 无 drawtext-safe 字体, 用系统 msyh")
            return SYSTEM_FONTS["msyh"]

    # 粗体偏好 (从文件名找 bold/bd/heavy)
    if prefer_bold:
        bold_pool = [p for p in pool if any(kw in p.name.lower()
                                              for kw in ("bold", "bd", "heavy",
                                                         "black", "粗"))]
        if bold_pool:
            pool = bold_pool

    return str(random.choice(pool))


def ffmpeg_escape(font_path: str) -> str:
    """把字体路径转成 ffmpeg drawtext 用的格式.

    Windows 要把 C:\\... 改成 C\\:/... (冒号前加反斜杠, 反斜杠转正斜杠).
    """
    path = font_path.replace("\\", "/")
    # 处理 drive letter 冒号
    if len(path) >= 2 and path[1] == ":":
        path = path[0] + "\\:" + path[2:]
    return path


# ═══════════════════════════════════════════════════════════════
# CLI
# ═══════════════════════════════════════════════════════════════

if __name__ == "__main__":
    import argparse
    import sys
    sys.stdout.reconfigure(encoding="utf-8")

    ap = argparse.ArgumentParser()
    ap.add_argument("--list", action="store_true", help="列出所有字体")
    ap.add_argument("--pick", action="store_true", help="随机选一个")
    ap.add_argument("--refresh", action="store_true", help="刷新池")
    ap.add_argument("--mode", default="random",
                    choices=["random", "fixed", "system"])
    ap.add_argument("--name", default=None)
    ap.add_argument("--explicit", default=None)
    ap.add_argument("--prefer-bold", action="store_true")
    ap.add_argument("--count", type=int, default=5, help="连续选几次")
    args = ap.parse_args()

    if args.refresh:
        n = refresh_pool()
        print(f"刷新完成: {n} 个字体")
    elif args.list:
        for i, p in enumerate(FONT_POOL, 1):
            size_mb = p.stat().st_size / 1024 / 1024
            print(f"  {i:2d}. [{size_mb:5.1f}MB] {p.name}")
        print(f"\n合计 {len(FONT_POOL)} 个字体 (FONTS_DIR={FONTS_DIR})")
    elif args.pick:
        print(f"连续选 {args.count} 次 (mode={args.mode}):")
        for _ in range(args.count):
            p = pick_font(mode=args.mode, name=args.name,
                           explicit=args.explicit,
                           prefer_bold=args.prefer_bold)
            print(f"  → {p}")
    else:
        ap.print_help()
