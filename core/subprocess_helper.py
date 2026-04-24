# -*- coding: utf-8 -*-
"""subprocess 统一 wrapper — 失败必暴露 stderr, 可选 NVENC semaphore.

★ 2026-04-24 v6 E5: 老代码 120+ 处 `subprocess.run(capture_output=True)` 失败时
吞掉 stderr, 线上故障只剩 returncode 无内容, 调试极难. 统一入口后全局 stderr 可见.

用法:
    from core.subprocess_helper import run_safe, run_nvenc

    rc, stdout, stderr = run_safe(
        ["ffmpeg", "-y", "-i", src, ...],
        timeout=900, tag="mode6/step6_interleave",
    )
    if rc != 0:
        # 失败时 stderr 已自动 log.error 了 (tail 500 字符)
        return False

    # NVENC session 限流 (RTX 3060 硬限 3 个)
    rc, _, _ = run_nvenc(ffmpeg_cmd, timeout=1800, tag="mode6/step6")
"""
from __future__ import annotations

import logging
import subprocess
import threading
from typing import Sequence

log = logging.getLogger(__name__)


# ─── NVENC session 限流 ──────────────────────────────────────────
# RTX 3060 硬件限制: 同时 3 个 NVENC session. 留 1 余量给 scale34.
# 可通过 app_config 'video.process.nvenc_max_concurrent' 覆盖.
_NVENC_MAX: int | None = None
_NVENC_SEMA: threading.BoundedSemaphore | None = None
_NVENC_LOCK = threading.Lock()


def _get_nvenc_sema() -> threading.BoundedSemaphore:
    """延迟初始化 NVENC 信号量 (避免 import 时触发 cfg_get)."""
    global _NVENC_SEMA, _NVENC_MAX
    if _NVENC_SEMA is None:
        with _NVENC_LOCK:
            if _NVENC_SEMA is None:
                try:
                    from core.app_config import get as cfg_get
                    _NVENC_MAX = int(cfg_get("video.process.nvenc_max_concurrent", 2) or 2)
                except Exception:
                    _NVENC_MAX = 2
                _NVENC_SEMA = threading.BoundedSemaphore(_NVENC_MAX)
                log.info("[subprocess_helper] NVENC semaphore init: max=%d", _NVENC_MAX)
    return _NVENC_SEMA


def run_safe(
    cmd: Sequence[str],
    timeout: int = 300,
    tag: str = "",
    cwd: str | None = None,
    env: dict | None = None,
    stderr_tail_chars: int = 500,
    log_success: bool = False,
) -> tuple[int, str, str]:
    """执行子进程, 失败时自动 log stderr 尾 N 字符.

    Args:
        cmd: 命令 list
        timeout: 秒数, 超时 rc=-1 返回
        tag: 日志 tag (如 "mode6/step6"), 用于区分多个 subprocess
        cwd / env: 透传给 subprocess.Popen
        stderr_tail_chars: 失败时 log stderr 末尾多少字符
        log_success: 成功时也 log (默认不打, 避免日志爆)

    Returns:
        (returncode, stdout, stderr)
        - rc=-1 表示 timeout
        - rc=-2 表示 subprocess 启动异常 (OSError 等)
    """
    tag = tag or "unknown"
    try:
        r = subprocess.run(
            list(cmd),
            capture_output=True,
            timeout=timeout,
            cwd=cwd, env=env,
        )
    except subprocess.TimeoutExpired as e:
        stderr = (e.stderr or b"").decode("utf-8", errors="replace")[-stderr_tail_chars:]
        log.error("[subprocess/%s] ⏱ TIMEOUT after %ds\n%s", tag, timeout, stderr)
        return -1, "", f"timeout_{timeout}s"
    except (OSError, subprocess.SubprocessError) as e:
        log.error("[subprocess/%s] ❌ spawn failed: %s", tag, e)
        return -2, "", str(e)

    rc = r.returncode
    stdout = r.stdout.decode("utf-8", errors="replace")
    stderr = r.stderr.decode("utf-8", errors="replace")

    if rc != 0:
        tail = stderr[-stderr_tail_chars:] if stderr else "(empty stderr)"
        log.error("[subprocess/%s] ❌ rc=%d (timeout=%ds)\n  stderr-tail:\n%s",
                  tag, rc, timeout, tail)
    elif log_success:
        log.info("[subprocess/%s] ✅ ok", tag)

    return rc, stdout, stderr


def run_nvenc(
    cmd: Sequence[str],
    timeout: int = 1800,
    tag: str = "nvenc",
    **kwargs,
) -> tuple[int, str, str]:
    """专门跑 NVENC 的 subprocess, 用 semaphore 限流.

    RTX 3060 最多 3 个 NVENC session. 超过会 "OpenEncodeSessionEx failed: 10 (no room)".
    用 BoundedSemaphore 阻塞等 slot, 避免并发撞墙.
    """
    sema = _get_nvenc_sema()
    with sema:   # 阻塞等 NVENC slot
        return run_safe(cmd, timeout=timeout, tag=tag, **kwargs)


def exists_and_nonempty(path: str, min_bytes: int = 1024) -> bool:
    """验证 subprocess 输出文件存在且非空 (> 1KB).

    用在 subprocess.returncode==0 之后, 防"进程退出但文件损坏" 情况.
    """
    import os
    try:
        return os.path.exists(path) and os.path.getsize(path) >= min_bytes
    except OSError:
        return False


# ─── 自测 ──────────────────────────────────────────────────────

if __name__ == "__main__":
    import sys
    sys.stdout.reconfigure(encoding="utf-8")
    logging.basicConfig(level=logging.INFO,
                        format="[%(asctime)s] %(levelname)s %(name)s %(message)s")

    print("=== Test 1: 成功命令 ===")
    rc, out, err = run_safe(["python", "--version"], tag="python_ver", log_success=True)
    print(f"  rc={rc} out={out.strip()!r}")

    print("\n=== Test 2: 失败命令 (会 log error) ===")
    rc, out, err = run_safe(["python", "-c", "import sys; sys.exit(7)"],
                             tag="exit7_test")
    print(f"  rc={rc}")

    print("\n=== Test 3: 失败 + stderr ===")
    rc, out, err = run_safe(["python", "-c", "raise ValueError('test error')"],
                             tag="raise_test")
    print(f"  rc={rc}  stderr 最后 200 字符: ...{err[-200:]!r}")

    print("\n=== Test 4: timeout ===")
    rc, out, err = run_safe(["python", "-c", "import time; time.sleep(10)"],
                             timeout=1, tag="timeout_test")
    print(f"  rc={rc}  err={err!r}")

    print("\n=== Test 5: NVENC semaphore (虚拟, 不真跑 ffmpeg) ===")
    # 这里只测 semaphore 获取/释放
    sema = _get_nvenc_sema()
    print(f"  NVENC max={_NVENC_MAX}")
    sema.acquire()
    sema.release()
    print(f"  semaphore 正常")
