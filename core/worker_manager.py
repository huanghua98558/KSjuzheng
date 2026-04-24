# -*- coding: utf-8 -*-
"""Worker 守护进程管理器 — FastAPI 启动时挂一个后台 TaskQueue worker.

★ 2026-04-24 v6 A1: DEPRECATED
  ──────────────────────────────────────────────────────────────
  本模块被废弃, 生产使用 `scripts/run_autopilot.py` 直接启动的
  `core.executor.account_executor.Executor`. 保留本文件仅为:

  1. 冷迁移期观测兼容 (dashboard.app 已默认 DISABLE_WORKERS=1)
  2. 旧测试文件不崩

  **禁止**新代码调用 WorkerManager.instance() / .start().
  dashboard /execution/* 已改接 account_executor (见 dashboard/api.py).

  下一版本 (v7) 本文件移入 legacy/ 目录, 最后版本删除.

  真实执行链:
    scripts/run_autopilot.py
      → core.executor.account_executor.Executor (4 workers)
      → _claim_task() + account_locks 表 (v6 A2)
      → core.executor.pipeline.run_publish_pipeline
  ──────────────────────────────────────────────────────────────

单例模式 (deprecated): WorkerManager.instance()

功能 (deprecated, 仅兼容):
  - 启动 / 停止 / 状态查询
  - 暴露 TaskQueue 的 status + circuit_breaker + 最近执行日志
  - 循环日志 (最近 200 条) — 供 /execution/logs 读取 (已改接)
"""
from __future__ import annotations

import warnings

# ★ v6 A1: import 时显示 deprecation 警告 (一次, 不刷屏)
warnings.warn(
    "core.worker_manager is deprecated and will be removed in v7. "
    "Production uses core.executor.account_executor.Executor via "
    "scripts/run_autopilot.py. Use DISABLE_WORKERS=1 env for dashboard.",
    DeprecationWarning,
    stacklevel=2,
)

import logging
import threading
import time
from collections import deque
from typing import Any

from core.db_manager import DBManager
from core.task_queue import TaskQueue
from core.executors import register_all
from core.logger import get_logger

log = get_logger("worker_manager")


# ---------------------------------------------------------------------------
# RingBuffer Handler — 捕捉执行日志供 UI 展示
# ---------------------------------------------------------------------------

class _RingBufferHandler(logging.Handler):
    def __init__(self, capacity: int = 500):
        super().__init__()
        self.buf: deque = deque(maxlen=capacity)
        self.lock = threading.Lock()

    def emit(self, record: logging.LogRecord) -> None:
        try:
            msg = self.format(record)
            with self.lock:
                self.buf.append({
                    "ts": record.created,
                    "level": record.levelname,
                    "logger": record.name,
                    "msg": msg,
                })
        except Exception:
            pass

    def snapshot(self, limit: int = 200, level: str | None = None) -> list[dict]:
        with self.lock:
            items = list(self.buf)
        if level:
            level = level.upper()
            items = [x for x in items if x["level"] == level]
        return items[-limit:]


# ---------------------------------------------------------------------------

class WorkerManager:
    _instance: "WorkerManager | None" = None
    _lock = threading.Lock()

    def __init__(self):
        self._db: DBManager | None = None
        self._queue: TaskQueue | None = None
        self._thread: threading.Thread | None = None
        self._started_at: float = 0.0
        self._registered: list[str] = []
        self._log_buffer = _RingBufferHandler(capacity=500)
        self._log_buffer.setFormatter(
            logging.Formatter("%(asctime)s %(name)s %(message)s",
                              datefmt="%H:%M:%S")
        )

    @classmethod
    def instance(cls) -> "WorkerManager":
        with cls._lock:
            if cls._instance is None:
                cls._instance = cls()
        return cls._instance

    # ------------------------------------------------------------------

    def _start_autopilot_loop(self):
        """启动 ControllerAgent 后台循环 (每 60s 一次)."""
        def _loop():
            from core.agents.controller_agent import ControllerAgent
            ctl_db = DBManager()
            ctl = ControllerAgent(ctl_db)
            while getattr(self, "_autopilot_on", True):
                try:
                    ctl.run_cycle()
                except Exception as e:
                    log.warning("[autopilot cycle error] %s", e)
                # 等 60s 或退出
                for _ in range(60):
                    if not getattr(self, "_autopilot_on", True):
                        return
                    time.sleep(1)
        self._autopilot_on = True
        self._autopilot_thread = threading.Thread(
            target=_loop, name="autopilot", daemon=True,
        )
        self._autopilot_thread.start()

    def autopilot_running(self) -> bool:
        t = getattr(self, "_autopilot_thread", None)
        return bool(t and t.is_alive() and getattr(self, "_autopilot_on", False))

    def stop_autopilot(self):
        self._autopilot_on = False

    # ------------------------------------------------------------------
    # 每日快照线程 (23:50 扫 13 账号 → daily_account_metrics /
    #  work_metrics / content_performance_daily / account_performance_daily /
    #  account_health_snapshots)
    # ------------------------------------------------------------------

    def _start_daily_snapshot_loop(self, hour: int = 23, minute: int = 50):
        """每天 HH:MM 跑一次 snapshot_all_accounts."""
        from datetime import datetime, timedelta

        def _seconds_until_next(h: int, m: int) -> float:
            now = datetime.now()
            target = now.replace(hour=h, minute=m, second=0, microsecond=0)
            if target <= now:
                target += timedelta(days=1)
            return (target - now).total_seconds()

        def _loop():
            from core.cookie_manager import CookieManager
            from core.data_collector import DataCollector
            while getattr(self, "_snapshot_on", True):
                wait_s = _seconds_until_next(hour, minute)
                log.info("[daily_snapshot] next run in %.0fs (%02d:%02d)",
                         wait_s, hour, minute)
                # 分片 sleep 以便能早退出
                elapsed = 0.0
                while elapsed < wait_s:
                    if not getattr(self, "_snapshot_on", True):
                        return
                    time.sleep(5)
                    elapsed += 5
                try:
                    dc_db = DBManager()
                    cm = CookieManager(dc_db)
                    dc = DataCollector(dc_db, cm)
                    stats = dc.snapshot_all_accounts(pages_per_account=2)
                    log.info(
                        "[daily_snapshot] done — %d ok / %d fail / %d works",
                        stats["accounts_processed"],
                        stats["accounts_failed"],
                        stats["total_works_captured"],
                    )
                    self._last_snapshot_at = time.time()
                    self._last_snapshot_stats = stats
                except Exception as e:
                    log.error("[daily_snapshot] error: %s", e)

        self._snapshot_on = True
        self._last_snapshot_at = 0.0
        self._last_snapshot_stats = None
        self._snapshot_hour = hour
        self._snapshot_minute = minute
        self._snapshot_thread = threading.Thread(
            target=_loop, name="daily-snapshot", daemon=True,
        )
        self._snapshot_thread.start()

    def snapshot_running(self) -> bool:
        t = getattr(self, "_snapshot_thread", None)
        return bool(t and t.is_alive() and getattr(self, "_snapshot_on", False))

    def stop_snapshot(self):
        self._snapshot_on = False

    def snapshot_now(self) -> dict[str, Any]:
        """立即跑一次 (不等 23:50). 同步调用, 带真实网络 IO."""
        from core.cookie_manager import CookieManager
        from core.data_collector import DataCollector
        dc_db = DBManager()
        cm = CookieManager(dc_db)
        dc = DataCollector(dc_db, cm)
        stats = dc.snapshot_all_accounts(pages_per_account=2)
        self._last_snapshot_at = time.time()
        self._last_snapshot_stats = stats
        return stats

    def snapshot_status(self) -> dict[str, Any]:
        return {
            "running": self.snapshot_running(),
            "schedule": f"{getattr(self,'_snapshot_hour',23):02d}:{getattr(self,'_snapshot_minute',50):02d} daily",
            "last_run_at": getattr(self, "_last_snapshot_at", 0.0),
            "last_stats": getattr(self, "_last_snapshot_stats", None),
        }

    def start(self, shared_db: "DBManager | None" = None) -> dict[str, Any]:
        """启动 WorkerManager.

        Args:
            shared_db: 可选, 由调用方传入已初始化的 DBManager.
                       避免在 worker thread 里再次 sqlite3.connect() 阻塞 (WAL shm 锁).
                       None = 按旧版在 worker thread 里自己创.
        """
        if self._queue and self._thread and self._thread.is_alive():
            return {"ok": True, "already_running": True,
                    "registered": self._registered}
        try:
            # 把 ring buffer handler 挂到 root logger
            root_logger = logging.getLogger()
            if self._log_buffer not in root_logger.handlers:
                root_logger.addHandler(self._log_buffer)

            # ★ 2026-04-20 修: 支持共享 db 进来, 避免 worker thread 里
            # sqlite3.connect() 在 WAL shm 持锁状态阻塞 10+ 秒.
            ready_evt = threading.Event()

            def _worker_main():
                import sys as _sys, time as _t
                tid = threading.get_ident()
                t_start = _t.time()
                def _p(msg):
                    elapsed = _t.time() - t_start
                    _sys.stderr.write(f"[WM-tid={tid} +{elapsed:.2f}s] {msg}\n")
                    _sys.stderr.flush()
                _p("_worker_main 开始")
                try:
                    if shared_db is not None:
                        _p("使用共享 DBManager (来自主线程)")
                        self._db = shared_db
                    else:
                        _p("创建新 DBManager (thread 内)...")
                        self._db = DBManager()
                        _p("DBManager OK")
                    _p("创建 TaskQueue...")
                    self._queue = TaskQueue(self._db)
                    _p("TaskQueue OK")
                    _p("register_all...")
                    self._registered = register_all(self._queue, self._db)
                    _p(f"{len(self._registered)} executors registered")
                    ready_evt.set()
                    _p("开始 queue.run(daemon=True)...")
                    self._queue.run(daemon=True)
                    _p("queue.run() 返回")
                except Exception as exc:
                    import traceback as _tb
                    _p(f"EXCEPTION: {exc}\n{_tb.format_exc()[:500]}")
                    ready_evt.set()

            self._thread = threading.Thread(
                target=_worker_main, name="tq-worker", daemon=True,
            )
            self._thread.start()
            ready_evt.wait(timeout=10)
            self._started_at = time.time()
            # 启 autopilot 循环 (env DISABLE_AUTOPILOT=1 可禁, 用于排查 db lock)
            import os as _os
            if _os.environ.get("DISABLE_AUTOPILOT", "").strip() in ("1", "true", "yes"):
                log.info("[WorkerManager] autopilot disabled via DISABLE_AUTOPILOT env")
            else:
                try:
                    self._start_autopilot_loop()
                    log.info("[WorkerManager] autopilot loop started")
                except Exception as e:
                    log.warning("[WorkerManager] autopilot start failed: %s", e)
            # 启每日快照 (23:50)
            try:
                self._start_daily_snapshot_loop(hour=23, minute=50)
                log.info("[WorkerManager] daily snapshot loop started (23:50)")
            except Exception as e:
                log.warning("[WorkerManager] daily snapshot start failed: %s", e)
            log.info("[WorkerManager] started — %d executors",
                     len(self._registered))
            return {"ok": True, "already_running": False,
                    "registered": self._registered,
                    "autopilot": self.autopilot_running()}
        except Exception as e:
            log.error("[WorkerManager] start failed: %s", e)
            return {"ok": False, "error": str(e)}

    def stop(self) -> dict[str, Any]:
        if not self._queue:
            return {"ok": False, "reason": "not running"}
        self._queue.stop()
        self._queue = None
        if self._thread:
            self._thread.join(timeout=3)
            self._thread = None
        log.info("[WorkerManager] stopped")
        return {"ok": True}

    def is_running(self) -> bool:
        return bool(self._thread and self._thread.is_alive())

    # ------------------------------------------------------------------

    def status(self) -> dict[str, Any]:
        running = self.is_running()
        if not self._queue or not running:
            return {
                "running": False,
                "registered_types": self._registered,
                "uptime_seconds": 0,
            }
        # 跨线程安全: 新开 connection 查
        try:
            conn = self._new_ro_conn()
            rows = conn.execute(
                "SELECT status, COUNT(*) FROM task_queue GROUP BY status"
            ).fetchall()
            counts = {r[0]: r[1] for r in rows}
            conn.close()
        except Exception:
            counts = {}
        return {
            "running": True,
            "registered_types": self._registered,
            "uptime_seconds": int(time.time() - self._started_at),
            "task_status_counts": counts,
            "total_tasks": sum(counts.values()),
            "circuit_breaker": self._queue._breaker.status()   # noqa: SLF001
                if self._queue else {},
        }

    # 所有读操作用**独立**的 sqlite 连接 (FastAPI 是多线程, 不能共享 _db.conn)
    @staticmethod
    def _new_ro_conn():
        import sqlite3
        from core.config import DB_PATH
        c = sqlite3.connect(DB_PATH, check_same_thread=False)
        return c

    def running_tasks(self) -> list[dict]:
        try:
            conn = self._new_ro_conn()
            rows = conn.execute(
                """SELECT id, task_type, account_id, drama_name,
                          priority, started_at, retry_count, idempotency_key
                   FROM task_queue WHERE status='running'
                   ORDER BY started_at LIMIT 50"""
            ).fetchall()
            conn.close()
            cols = ["id","task_type","account_id","drama_name",
                    "priority","started_at","retry_count","idempotency_key"]
            return [dict(zip(cols, r)) for r in rows]
        except Exception as e:
            log.warning("[WorkerManager] running_tasks: %s", e)
            return []

    def concurrency(self) -> dict[str, dict[str, int]]:
        if not self._queue:
            return {}
        try:
            conn = self._new_ro_conn()
        except Exception:
            return {}
        out: dict[str, dict[str, int]] = {}
        for tt, sem in self._queue._semaphores.items():   # noqa: SLF001
            try:
                running_now = conn.execute(
                    "SELECT COUNT(*) FROM task_queue WHERE task_type=? AND status='running'",
                    (tt,),
                ).fetchone()[0]
            except Exception:
                running_now = 0
            out[tt] = {
                "limit": sem._value + running_now,
                "running": running_now,
                "remaining": sem._value,
            }
        conn.close()
        return out

    def logs(self, limit: int = 200, level: str | None = None) -> list[dict]:
        return self._log_buffer.snapshot(limit=limit, level=level)
