# -*- coding: utf-8 -*-
"""跨进程文件锁 — 防同视频重复处理浪费资源.

KS184 `run_complete_flow` 里有 `download_lock_file` 和 `process_lock_file`.
Week 3 多 worker 并发时必需 — 两 worker 拿到同一 drama, 不能同时 download.

使用:
    from core.file_lock import FileLock, acquire_lock

    # 上下文管理器 (推荐)
    with FileLock("download", key="drama_xyz_hash", timeout=300) as locked:
        if not locked:
            print("另一个 worker 正在处理, 跳过或等")
            return
        do_download()

    # 原始 API
    lock = acquire_lock("process", "drama_xxx", timeout=1800)
    if lock:
        try:
            do_stuff()
        finally:
            lock.release()

锁文件: `short_drama_videos/.locks/{scope}/{key}.lock`
内容: pid + hostname + ts

过期机制: 锁文件 mtime 超过 `stale_sec` 认为是僵尸锁 (worker 崩了),
         自动抢占.
"""
from __future__ import annotations

import hashlib
import logging
import os
import random
import socket
import time
from pathlib import Path
from typing import Any

log = logging.getLogger(__name__)

LOCK_ROOT = Path(r"D:\ks_automation\short_drama_videos\.locks")


def _key_to_filename(key: str) -> str:
    """任何 key 转成 filesystem-safe 短 hash."""
    return hashlib.md5(key.encode("utf-8")).hexdigest()[:16]


class FileLock:
    """跨进程独占锁.

    Args:
        scope: 逻辑范围 (download / process / publish)
        key: 锁主键 (如 drama_url / task_id)
        timeout: 获取锁超时秒数 (0 = 不等直接返回)
        stale_sec: 多久没更新认为是僵尸锁 (默认 30min)
        poll_interval: 轮询间隔秒
    """

    def __init__(self, scope: str, key: str, timeout: int = 300,
                 stale_sec: int | None = None, poll_interval: float = 1.0):
        # ★ 2026-04-21: stale_sec 默认从 app_config 读, 可线上调
        if stale_sec is None:
            try:
                from core.app_config import get as _cfg_get
                stale_sec = int(_cfg_get(f"file_lock.{scope}.stale_sec",
                                          _cfg_get("file_lock.default_stale_sec", 1800)))
            except Exception:
                stale_sec = 1800
        self.scope = scope
        self.key = key
        self.timeout = timeout
        self.stale_sec = stale_sec
        self.poll_interval = poll_interval
        self.lock_dir = LOCK_ROOT / scope
        self.lock_file = self.lock_dir / f"{_key_to_filename(key)}.lock"
        self._acquired = False

    def _write_lock(self) -> bool:
        """尝试创建锁文件 (原子: 用 O_EXCL).

        Returns: True 拿到, False 已被别人持有.
        """
        self.lock_dir.mkdir(parents=True, exist_ok=True)
        try:
            # O_EXCL 保证原子: 如果已存在就 FileExistsError
            fd = os.open(str(self.lock_file),
                         os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            try:
                content = f"pid={os.getpid()} host={socket.gethostname()} " \
                          f"ts={int(time.time())} key={self.key}"
                os.write(fd, content.encode("utf-8"))
            finally:
                os.close(fd)
            return True
        except FileExistsError:
            return False

    def _is_stale(self) -> bool:
        """锁文件老到视为僵尸."""
        try:
            mtime = self.lock_file.stat().st_mtime
            return (time.time() - mtime) > self.stale_sec
        except FileNotFoundError:
            return True
        except Exception:
            return False

    def _steal_if_stale(self) -> bool:
        """若现存锁过期, 抢占 (删除重建)."""
        if not self._is_stale():
            return False
        try:
            self.lock_file.unlink(missing_ok=True)
            log.warning("[file_lock] stale lock stolen: %s", self.lock_file.name)
        except Exception:
            pass
        return self._write_lock()

    def acquire(self) -> bool:
        """获取锁. 返回 True 拿到, False 超时."""
        deadline = time.time() + self.timeout
        # 首次立刻试一下
        if self._write_lock():
            self._acquired = True
            return True

        if self.timeout <= 0:
            # 不等
            if self._steal_if_stale():
                self._acquired = True
                return True
            return False

        while time.time() < deadline:
            if self._write_lock():
                self._acquired = True
                return True
            if self._steal_if_stale():
                self._acquired = True
                return True
            # 加随机抖动避免 thundering herd
            time.sleep(self.poll_interval + random.uniform(0, 0.3))
        return False

    def release(self) -> None:
        if not self._acquired:
            return
        try:
            self.lock_file.unlink(missing_ok=True)
        except Exception:
            pass
        self._acquired = False

    def __enter__(self) -> bool:
        return self.acquire()

    def __exit__(self, *args) -> None:
        self.release()


def acquire_lock(scope: str, key: str, timeout: int = 300,
                  stale_sec: int = 1800) -> FileLock | None:
    """便捷函数: 拿到锁返回对象 (调用方 .release()), 拿不到返回 None."""
    lock = FileLock(scope, key, timeout=timeout, stale_sec=stale_sec)
    if lock.acquire():
        return lock
    return None


def gc_stale_locks(scope: str | None = None, stale_sec: int = 1800) -> int:
    """清理僵尸锁 (运维用)."""
    cleaned = 0
    scopes = [scope] if scope else [d.name for d in LOCK_ROOT.iterdir()
                                     if LOCK_ROOT.exists() and d.is_dir()]
    for s in scopes:
        d = LOCK_ROOT / s
        if not d.exists():
            continue
        for f in d.glob("*.lock"):
            try:
                if (time.time() - f.stat().st_mtime) > stale_sec:
                    f.unlink()
                    cleaned += 1
            except Exception:
                pass
    return cleaned


if __name__ == "__main__":
    import sys, argparse, json
    sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser()
    ap.add_argument("--gc", action="store_true")
    ap.add_argument("--scope", default=None)
    ap.add_argument("--test", action="store_true", help="测试并发")
    args = ap.parse_args()

    if args.gc:
        n = gc_stale_locks(args.scope)
        print(f"cleaned {n} stale locks")
    elif args.test:
        # 快速功能测试
        import threading
        acquired_count = [0]
        def worker():
            with FileLock("test", "shared_key", timeout=2) as ok:
                if ok:
                    acquired_count[0] += 1
                    time.sleep(0.5)
        threads = [threading.Thread(target=worker) for _ in range(5)]
        for t in threads: t.start()
        for t in threads: t.join()
        print(f"5 threads raced for 1 lock, {acquired_count[0]} 同时拿到 "
              f"(应为 1 或 5, 看 serialization)")
    else:
        ap.print_help()
