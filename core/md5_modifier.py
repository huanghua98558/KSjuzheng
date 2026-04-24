# -*- coding: utf-8 -*-
"""MP4 MD5 修改器 — 对抗快手 md5-based 查重.

来源线索 (KS184 bytecode dump `multi_drama_mode2_manager._copy_and_modify_md5`):
    co_varnames: [self, source_path, dest_path, log_func, shutil, random, hashlib,
                  f, original_md5, time, random_bytes, new_md5, e]

推测逻辑 (从变量名+顺序):
    1. shutil.copy 源 → dest_path
    2. hashlib 读原 md5
    3. 打开 dest_path 'ab' (append binary)
    4. 写 8-32 个 random_bytes
    5. 读新 md5 (应该不同)
    6. 记 log

原理: MP4 容器允许文件末尾有"trailing data" (多数播放器忽略).
      追加随机字节能改 MD5 但不破坏播放.

使用:
    from core.md5_modifier import modify_mp4_md5
    r = modify_mp4_md5("/path/to.mp4")
    # → {"ok": True, "original_md5": "...", "new_md5": "...", "bytes_added": 16}
"""
from __future__ import annotations

import hashlib
import logging
import os
import secrets
from pathlib import Path
from typing import Any

from core.app_config import get as cfg_get

log = logging.getLogger(__name__)


def compute_file_md5(path: str | Path, chunk: int = 1024 * 1024) -> str:
    """计算文件 MD5."""
    h = hashlib.md5()
    with open(path, "rb") as f:
        while True:
            data = f.read(chunk)
            if not data:
                break
            h.update(data)
    return h.hexdigest()


def modify_mp4_md5(
    path: str | Path,
    min_bytes: int = 8,
    max_bytes: int = 32,
) -> dict[str, Any]:
    """往 MP4 末尾追加随机字节改 MD5. in-place 操作.

    Args:
        path: MP4 文件路径 (将被 **修改**, 不生成新文件)
        min_bytes / max_bytes: 追加字节数范围

    Returns:
        {ok, original_md5, new_md5, bytes_added, size_before, size_after, error?}
    """
    path = Path(path)
    if not path.is_file():
        return {"ok": False, "error": f"file_not_found: {path}"}

    try:
        size_before = path.stat().st_size
        if size_before < 1024:
            return {"ok": False, "error": f"file_too_small: {size_before}B"}

        original_md5 = compute_file_md5(path)

        n = secrets.randbelow(max_bytes - min_bytes + 1) + min_bytes
        random_bytes = secrets.token_bytes(n)

        with open(path, "ab") as f:
            f.write(random_bytes)

        new_md5 = compute_file_md5(path)
        size_after = path.stat().st_size

        if new_md5 == original_md5:
            return {"ok": False, "error": "md5_unchanged_unexpected",
                    "original_md5": original_md5}

        log.info("[md5_mod] %s: %s → %s (+%dB)",
                 path.name, original_md5[:10], new_md5[:10], n)

        return {
            "ok": True,
            "original_md5": original_md5,
            "new_md5": new_md5,
            "bytes_added": n,
            "size_before": size_before,
            "size_after": size_after,
        }
    except Exception as e:
        log.exception("[md5_mod] exception on %s", path)
        return {"ok": False, "error": f"exception: {e}"}


def modify_if_enabled(path: str | Path) -> dict[str, Any]:
    """按 app_config 开关决定是否改 MD5. 给 pipeline 用的便捷入口."""
    if not cfg_get("video.process.modify_md5", True):
        return {"ok": True, "skipped": True, "reason": "disabled_in_config"}

    # 从 config 读范围 (可选, 有默认)
    min_b = cfg_get("video.process.md5_append_min_bytes", 8)
    max_b = cfg_get("video.process.md5_append_max_bytes", 32)
    return modify_mp4_md5(path, min_bytes=min_b, max_bytes=max_b)


if __name__ == "__main__":
    import sys, json, argparse
    sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser()
    ap.add_argument("--input", required=True)
    ap.add_argument("--min-bytes", type=int, default=8)
    ap.add_argument("--max-bytes", type=int, default=32)
    args = ap.parse_args()

    r = modify_mp4_md5(args.input, min_bytes=args.min_bytes, max_bytes=args.max_bytes)
    print(json.dumps(r, ensure_ascii=False, indent=2))
