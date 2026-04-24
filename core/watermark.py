# -*- coding: utf-8 -*-
"""封面水印 — ffmpeg drawtext 烧 短剧名 + @账号名 到封面 PNG.

来源 (KS184 bytecode):
  `multi_drama_mode2_manager._copy_cover_with_watermark`
  co_varnames: [self, source_cover_path, dest_cover_path, drama_name,
                account_name, log_func, watermark_config, subprocess, ...]

推测 KS184 逻辑:
  1. shutil copy 源封面 → dest
  2. 读 watermark_config (drama_name_style + account_style)
  3. 2 次 ffmpeg drawtext: 剧名 (居中大字) + 账号名 (右下小字)

配置 (`app_config.cover.watermark.*`, migrate_v18 已落 11 项):
  cover.watermark.enabled                = true
  cover.watermark.drama_name.enabled     = true
  cover.watermark.drama_name.size        = 48
  cover.watermark.drama_name.color       = random | white | yellow | #FF5500
  cover.watermark.drama_name.position    = center | top | bottom
  cover.watermark.drama_name.style.stroke = true/false
  cover.watermark.drama_name.style.random = true/false
  cover.watermark.account.enabled        = true
  cover.watermark.account.size           = 20
  cover.watermark.account.color          = white | yellow | ...
  cover.watermark.account.position       = bottom_right | bottom_left | top_*
  cover.watermark.account.opacity        = 70  (%)

使用:
    from core.watermark import burn_cover
    r = burn_cover(
        source_cover="/path/cover.png",
        drama_name="少年叶飞鸿",
        account_name="百洁短剧工厂",
        out_cover="/path/cover_watermarked.png",
    )
    # → {"ok": True, "output_path": "...", "elapsed_sec": 0.5}
"""
from __future__ import annotations

import logging
import os
import random
import subprocess
from pathlib import Path
from typing import Any

from core.app_config import get as cfg_get

log = logging.getLogger(__name__)


def _get_ffmpeg() -> str:
    """ffmpeg 路径 — 优先 KS184 bin-xin (有 drawtext 完整支持)."""
    for p in [
        r"C:\Program Files\kuaishou2\KS184.7z\KS184\tools\ffmpeg\bin-xin\ffmpeg.exe",
        r"C:\Program Files\kuaishou2\KS184.7z\KS184\tools\ffmpeg\bin\ffmpeg.exe",
        r"D:\ks_automation\tools\m3u8dl\ffmpeg.exe",
    ]:
        if os.path.isfile(p):
            return p
    return "ffmpeg"


def _find_chinese_font() -> str | None:
    """找字体给 drawtext 用 — 优先 font_pool (KS184 8 字体), fallback 系统字体.

    R1-2 升级: 用 core.font_pool 支持 random/fixed/system 三种 mode.
    配置: watermark.font.mode = random/fixed/system
    """
    try:
        from core.font_pool import pick_font
        mode = cfg_get("watermark.font.mode", "random")
        explicit = cfg_get("watermark.font.explicit", "") or None
        prefer_bold = cfg_get("watermark.font.prefer_bold", False)
        font = pick_font(mode=mode, explicit=explicit, prefer_bold=prefer_bold)
        if font and os.path.isfile(font):
            return font
    except Exception as e:
        log.debug("[watermark] font_pool failed: %s", e)

    # Fallback: 系统字体
    for p in [
        r"C:\Windows\Fonts\msyh.ttc",
        r"C:\Windows\Fonts\msyh.ttf",
        r"C:\Windows\Fonts\msyhbd.ttc",
        r"C:\Windows\Fonts\simhei.ttf",
        r"C:\Windows\Fonts\simsun.ttc",
    ]:
        if os.path.isfile(p):
            return p
    return None


def _resolve_drama_style() -> dict:
    """★ R3-4: 解析 drama 水印样式 (5 选 N).

    配置:
      cover.watermark.drama_name.style.random = True → 随机挑 1-3 种组合
      否则按 stroke/shadow/glow/bold 各自的 bool 开关

    Returns:
        {"stroke": bool, "shadow": bool, "glow": bool, "bold": bool}
    """
    random_mode = cfg_get("cover.watermark.drama_name.style.random", False)
    # 处理 str 的 bool
    if isinstance(random_mode, str):
        random_mode = random_mode.lower() in ("true", "1", "yes")

    all_styles = ["stroke", "shadow", "glow", "bold"]

    if random_mode:
        import random as _rnd
        # 至少选 1 个, 最多 3 个 (glow 和 stroke 不冲突, 但同时开有重复感)
        n = _rnd.randint(1, 3)
        picked = _rnd.sample(all_styles, n)
        result = {s: s in picked for s in all_styles}
        # glow 强时去掉 stroke (避免重复描边)
        if result.get("glow") and result.get("stroke"):
            result["stroke"] = False
        log.info("[watermark] style.random picked: %s", picked)
        return result

    # 显式模式
    def _cfg_bool(key: str, default: bool) -> bool:
        v = cfg_get(key, default)
        if isinstance(v, bool):
            return v
        if isinstance(v, str):
            return v.lower() in ("true", "1", "yes", "on")
        return bool(v)

    return {
        "stroke": _cfg_bool("cover.watermark.drama_name.style.stroke", True),
        "shadow": _cfg_bool("cover.watermark.drama_name.style.shadow", False),
        "glow":   _cfg_bool("cover.watermark.drama_name.style.glow", False),
        "bold":   _cfg_bool("cover.watermark.drama_name.style.bold", False),
    }


_COLOR_MAP = {
    "white":  "white",
    "black":  "black",
    "yellow": "#FFD700",
    "red":    "#FF3333",
    "orange": "#FF7F00",
}


def _resolve_color(name: str) -> str:
    """把 'random' / 'white' 等转成 ffmpeg 能用的 color."""
    if name.startswith("#"):
        return name
    name = name.lower()
    if name == "random":
        # 随机鲜艳色 (避免暗黑)
        choices = ["#FFD700", "#FF3333", "#FF7F00", "#FF00A6",
                    "#00D2FF", "#FF69B4", "white"]
        return random.choice(choices)
    return _COLOR_MAP.get(name, "white")


def _drama_position_xy(position: str, size: int) -> str:
    """剧名位置 → drawtext x:y 表达式 (基于视频 W/H)."""
    if position == "top":
        return f"x=(w-text_w)/2:y=40"
    if position == "bottom":
        return f"x=(w-text_w)/2:y=h-text_h-60"
    return f"x=(w-text_w)/2:y=(h-text_h)/2"   # center


def _account_position_xy(position: str, margin: int = 15) -> str:
    if position == "bottom_right":
        return f"x=w-text_w-{margin}:y=h-text_h-{margin}"
    if position == "bottom_left":
        return f"x={margin}:y=h-text_h-{margin}"
    if position == "top_right":
        return f"x=w-text_w-{margin}:y={margin}"
    if position == "top_left":
        return f"x={margin}:y={margin}"
    return f"x=w-text_w-{margin}:y=h-text_h-{margin}"


def _escape_drawtext_textfile_path(path: str) -> str:
    """drawtext textfile= 的路径转义 (: 和 \\)."""
    return path.replace("\\", "/").replace(":", "\\:")


def _wrap_text(text: str, max_chars_per_line: int = 8, max_lines: int = 2) -> str:
    """长剧名自动折行 (对齐 KS184 `line1, line2, max_chars_per_line` 变量).

    中文 1 字符算 1 格 (简化). 超 max_lines 截断.
    """
    if len(text) <= max_chars_per_line:
        return text
    lines = []
    remaining = text
    for _ in range(max_lines):
        if not remaining:
            break
        lines.append(remaining[:max_chars_per_line])
        remaining = remaining[max_chars_per_line:]
    return "\n".join(lines)


def _write_text_to_tempfile(text: str, work_dir: Path) -> str:
    """把文字写进临时文件供 drawtext textfile= 用.

    KS184 这么做是因为 drawtext text= 有严重转义坑 (emoji / 单引号 / 特殊字符),
    textfile= 直接读字节无转义问题.
    """
    import secrets as _sec
    work_dir.mkdir(parents=True, exist_ok=True)
    f = work_dir / f"dt_{_sec.token_hex(4)}.txt"
    # 写 UTF-8 BOM-less (ffmpeg 友好)
    f.write_bytes(text.encode("utf-8"))
    return str(f)


def _build_drawtext_filter(
    text: str, font_path: str | None, size: int,
    color: str, position_expr: str,
    opacity: float = 1.0,
    stroke: bool = True, stroke_color: str = "black", stroke_w: int = 2,
    textfile_path: str | None = None,
    # R3 新增: 4 种样式
    shadow: bool = False, shadow_x: int = 3, shadow_y: int = 3,
    shadow_color: str = "black@0.6",
) -> str:
    """组 drawtext filter 字符串 (基础版).

    优先用 textfile= (KS184 对齐, 避免特殊字符炸).
    没 textfile_path 时 fallback 到 text=.

    R3-1/R3-2: shadow 支持 (drawtext 原生 shadowx/y/color 参数)
    """
    parts = []
    if textfile_path:
        parts.append(f"textfile='{_escape_drawtext_textfile_path(textfile_path)}'")
        parts.append("reload=0")  # 不重载 (一次渲染)
    else:
        # Fallback: 原 text= 模式
        escaped = (text.replace("\\", "\\\\")
                       .replace(":", r"\:")
                       .replace("'", r"\'")
                       .replace("%", r"\%"))
        parts.append(f"text='{escaped}'")
    if font_path:
        fp = font_path.replace("\\", "/").replace(":", "\\:")
        parts.append(f"fontfile='{fp}'")
    parts.append(f"fontsize={size}")
    if opacity < 1.0:
        parts.append(f"fontcolor={color}@{opacity:.2f}")
    else:
        parts.append(f"fontcolor={color}")
    if stroke:
        parts.append(f"bordercolor={stroke_color}")
        parts.append(f"borderw={stroke_w}")
    # R3-1 shadow (drawtext 原生)
    if shadow:
        parts.append(f"shadowx={shadow_x}")
        parts.append(f"shadowy={shadow_y}")
        parts.append(f"shadowcolor={shadow_color}")
    # 支持多行: text_align=MC (middle-center)
    parts.append("text_align=M+C")
    parts.append(position_expr)
    return "drawtext=" + ":".join(parts)


def _build_drawtext_with_glow(
    text: str, font_path: str | None, size: int,
    color: str, position_expr: str,
    opacity: float = 1.0,
    textfile_path: str | None = None,
    glow_color: str = "white@0.8",
    glow_radius: int = 4,
) -> list[str]:
    """★ R3-2: glow (发光) 效果 — 多层 drawtext 叠加.

    原理: 把同文字用 glow_color 多次绘制, 每次 borderw 从大到小 + 递增透明度,
          形成"光晕", 最后绘一次原色文字.

    返回 filter list (会被外层用 , 连接).
    """
    filters = []
    # 发光层: 3 层 border 递减
    for i in range(glow_radius, 0, -1):
        layer_alpha = 0.2 + 0.15 * (glow_radius - i)  # 0.2 ~ 0.65
        layer_alpha = min(0.9, layer_alpha)
        filters.append(_build_drawtext_filter(
            text=text, font_path=font_path, size=size,
            color="white",  # 发光层用中性白, 避免污染
            position_expr=position_expr,
            opacity=layer_alpha,
            stroke=True, stroke_color=glow_color.split("@")[0], stroke_w=i * 2,
            textfile_path=textfile_path,
        ))
    # 正文层 (在发光层之上)
    filters.append(_build_drawtext_filter(
        text=text, font_path=font_path, size=size, color=color,
        position_expr=position_expr, opacity=opacity,
        stroke=False, textfile_path=textfile_path,
    ))
    return filters


def burn_cover(
    source_cover: str | Path,
    drama_name: str,
    account_name: str,
    out_cover: str | Path,
) -> dict[str, Any]:
    """主入口 — 按 app_config 给封面烧 drama_name + account_name 水印.

    Returns:
        {ok, output_path, elapsed_sec, filters_used, error?}
    """
    import time as _t
    t0 = _t.time()

    if not cfg_get("cover.watermark.enabled", True):
        # 复制原封面
        import shutil
        shutil.copy(source_cover, out_cover)
        return {"ok": True, "output_path": str(out_cover),
                "skipped": True, "reason": "disabled"}

    if not os.path.isfile(source_cover):
        return {"ok": False, "error": f"source_cover not found: {source_cover}"}

    font = _find_chinese_font()
    if not font:
        log.warning("[watermark] 未找到中文字体, drawtext 可能渲染方块")

    filters = []
    # 临时目录 (给 drawtext textfile=)
    tmp_dir = Path(out_cover).parent / ".wm_tmp"
    temp_textfiles: list[str] = []

    # ─── 剧名水印 (长标题自动折行 + R3 多样式支持) ───
    if cfg_get("cover.watermark.drama_name.enabled", True) and drama_name:
        # UI "大小" (font_size) 新 key, 向后兼容旧 size
        size = cfg_get("cover.watermark.drama_name.font_size",
                        cfg_get("cover.watermark.drama_name.size", 48))
        color_key = cfg_get("cover.watermark.drama_name.color", "random")
        # UI 自定义色 (custom_color=#FF5500) 优先生效
        custom_color = cfg_get("cover.watermark.drama_name.custom_color", "")
        if custom_color and color_key == "custom":
            color = custom_color
        else:
            color = _resolve_color(color_key)
        position = cfg_get("cover.watermark.drama_name.position", "center")
        max_chars = cfg_get("cover.watermark.drama_name.max_chars_per_line", 8)
        # UI "透明度" 0-100
        drama_opacity_pct = cfg_get("cover.watermark.drama_name.opacity", 100)
        try: drama_opacity_pct = int(drama_opacity_pct)
        except Exception: drama_opacity_pct = 100

        # R3 样式解析 (5 选 N)
        style = _resolve_drama_style()

        # R3-3: bold — 切粗体字体 (若 font_pool 有 bold 版)
        drama_font = font
        if style["bold"]:
            try:
                from core.font_pool import pick_font
                drama_font = pick_font(mode=cfg_get("watermark.font.mode", "random"),
                                        prefer_bold=True)
            except Exception:
                pass

        # 自动折行
        wrapped_drama = _wrap_text(drama_name, max_chars_per_line=max_chars, max_lines=2)
        tf = _write_text_to_tempfile(wrapped_drama, tmp_dir)
        temp_textfiles.append(tf)

        pos_expr = _drama_position_xy(position, size)

        # R3-2: glow 需要多层 drawtext, 独立分支
        if style["glow"]:
            glow_filters = _build_drawtext_with_glow(
                text=wrapped_drama, font_path=drama_font, size=size, color=color,
                position_expr=pos_expr,
                textfile_path=tf,
                glow_color=cfg_get("cover.watermark.drama_name.glow_color",
                                    "white@0.8"),
                glow_radius=int(cfg_get("cover.watermark.drama_name.glow_radius", 4)),
            )
            filters.extend(glow_filters)
        else:
            # 普通路径 (stroke + shadow 组合)
            filters.append(_build_drawtext_filter(
                text=wrapped_drama, font_path=drama_font, size=size, color=color,
                position_expr=pos_expr,
                stroke=style["stroke"],
                stroke_color=cfg_get("cover.watermark.drama_name.stroke_color", "black"),
                stroke_w=int(cfg_get("cover.watermark.drama_name.stroke_w", 2)),
                shadow=style["shadow"],
                shadow_x=int(cfg_get("cover.watermark.drama_name.shadow_x", 3)),
                shadow_y=int(cfg_get("cover.watermark.drama_name.shadow_y", 3)),
                shadow_color=cfg_get("cover.watermark.drama_name.shadow_color",
                                      "black@0.6"),
                textfile_path=tf,
            ))

    # ─── 账号水印 @账号名 (UI 新 key cover.watermark.account_name.*, 兼容旧 account.*) ───
    account_enabled = cfg_get("cover.watermark.account_name.enabled",
                               cfg_get("cover.watermark.account.enabled", True))
    if account_enabled and account_name:
        size = cfg_get("cover.watermark.account_name.font_size",
                        cfg_get("cover.watermark.account.size", 20))
        color_key = cfg_get("cover.watermark.account_name.color",
                             cfg_get("cover.watermark.account.color", "white"))
        custom_color = cfg_get("cover.watermark.account_name.custom_color", "")
        if custom_color and color_key == "custom":
            color = custom_color
        else:
            color = _resolve_color(color_key)
        position = cfg_get("cover.watermark.account_name.position",
                            cfg_get("cover.watermark.account.position", "bottom_right"))
        opacity_pct = cfg_get("cover.watermark.account_name.opacity",
                               cfg_get("cover.watermark.account.opacity", 70))
        margin = cfg_get("cover.watermark.account_name.margin", 15)
        try: opacity_pct = int(opacity_pct)
        except Exception: opacity_pct = 70
        try: margin = int(margin)
        except Exception: margin = 15
        # 独立字体 (若 account_name.font != auto)
        acct_font = font
        acct_font_key = cfg_get("cover.watermark.account_name.font", "auto")
        if acct_font_key and acct_font_key != "auto":
            try:
                from core.font_pool import pick_font
                acct_font = pick_font(mode="fixed", explicit=acct_font_key)
            except Exception:
                pass
        text = f"@{account_name}"
        tf = _write_text_to_tempfile(text, tmp_dir)
        temp_textfiles.append(tf)
        filters.append(_build_drawtext_filter(
            text=text,
            font_path=acct_font, size=size, color=color,
            position_expr=_account_position_xy(position, margin=margin),
            opacity=opacity_pct / 100,
            stroke=True, stroke_w=1,
            textfile_path=tf,
        ))

    if not filters:
        import shutil
        shutil.copy(source_cover, out_cover)
        return {"ok": True, "output_path": str(out_cover),
                "skipped": True, "reason": "all_disabled"}

    # 拼 -vf: 多个 drawtext 用 , 连接
    vf = ",".join(filters)

    ffmpeg = _get_ffmpeg()
    out_cover = Path(out_cover)
    out_cover.parent.mkdir(parents=True, exist_ok=True)

    cmd = [
        ffmpeg, "-y", "-loglevel", "error",
        "-i", str(source_cover),
        "-vf", vf,
        str(out_cover),
    ]
    try:
        r = subprocess.run(cmd, capture_output=True, text=True,
                           timeout=30, encoding="utf-8", errors="replace")
        if r.returncode != 0:
            err = (r.stderr or "").strip()[:300]
            log.warning("[watermark] ffmpeg failed: %s", err)
            return {"ok": False, "error": f"ffmpeg: {err}",
                    "filters_used": filters}

        if not out_cover.exists() or out_cover.stat().st_size < 256:
            return {"ok": False, "error": "output_missing_or_tiny"}

        # 清理临时 textfiles
        for f in temp_textfiles:
            try: os.unlink(f)
            except Exception: pass
        try:
            if tmp_dir.exists() and not any(tmp_dir.iterdir()):
                tmp_dir.rmdir()
        except Exception: pass

        elapsed = round(_t.time() - t0, 2)
        log.info("[watermark] ✅ %s (%.1fs)", out_cover.name, elapsed)
        return {
            "ok": True,
            "output_path": str(out_cover),
            "elapsed_sec": elapsed,
            "filters_used": filters,
            "output_size": out_cover.stat().st_size,
        }
    except subprocess.TimeoutExpired:
        return {"ok": False, "error": "timeout"}
    except Exception as e:
        return {"ok": False, "error": f"exception: {e}"}


if __name__ == "__main__":
    import sys, json as _j, argparse
    sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser()
    ap.add_argument("--cover", required=True, help="源封面")
    ap.add_argument("--drama", default="测试剧名")
    ap.add_argument("--account", default="测试账号")
    ap.add_argument("--output", default=None)
    args = ap.parse_args()

    out = args.output or (Path(args.cover).with_name(
        Path(args.cover).stem + "_wm" + Path(args.cover).suffix))
    r = burn_cover(args.cover, args.drama, args.account, out)
    print(_j.dumps(r, ensure_ascii=False, indent=2, default=str))
