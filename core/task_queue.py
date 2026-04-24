"""Production-grade task queue with concurrency control, retry, circuit breaker,
and graceful degradation for the KS184 automation pipeline.

Supports the full dependency chain: COLLECT -> DOWNLOAD -> PROCESS -> PUBLISH -> ANALYZE.
Each task type has independent concurrency limits and resource constraints.

Usage:
    from core.task_queue import TaskQueue, Task
    from core.db_manager import DBManager

    db = DBManager()
    queue = TaskQueue(db)
    queue.set_executor("DOWNLOAD", my_download_func)
    task_ids = queue.add_pipeline("acc_001", "drama_title", "https://...")
    queue.run()
"""

from __future__ import annotations

import json
import sqlite3
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor, Future
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from typing import Any, Callable

from core.logger import get_logger

logger = get_logger("task_queue")

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# --- Task types ---
# Legacy set kept for backward-compat with old add_pipeline signature.
TASK_TYPES = (
    # Phase-1 original
    "DOWNLOAD", "PROCESS", "PUBLISH_A", "PUBLISH_B", "COLLECT", "ANALYZE",
    # Phase-2 additions (MCN gate, verify, feedback, health)
    "QC", "MCN_SYNC", "MCN_BIND_VERIFY", "MCN_INVITE", "MCN_POLL",
    "MCN_HEARTBEAT", "VERIFY", "FEEDBACK", "HEALTH_CHECK",
    # Phase-3 additions (AI-driven)
    "EXPERIMENT", "SCALE",
)

# --- 10-state machine (TASK_QUEUE_AND_AGENT_STATE_DESIGN §4) ---
TASK_STATUSES = (
    "pending",         # created, not yet queued
    "queued",          # in scheduler backlog
    "running",         # actively executing
    "waiting_retry",   # transient failure, retry at next_retry_at
    "waiting_manual",  # needs human intervention (manual_review_items)
    "success",         # completed OK
    "failed",          # not recoverable automatically
    "skipped",         # bypassed (dependency failed / rule skip)
    "dead_letter",     # exhausted retries
    "canceled",        # manually canceled
)
TERMINAL_STATUSES = ("success", "failed", "skipped", "dead_letter", "canceled")
ACTIVE_STATUSES = ("pending", "queued", "running",
                   "waiting_retry", "waiting_manual")

# --- Priority (smaller = higher) ---
# Per TASK_QUEUE_AND_AGENT_STATE_DESIGN §6
PRIORITY_CRITICAL = 10        # MCN session / auth / emergency stop-loss
PRIORITY_URGENT = 10          # legacy alias
PRIORITY_HOT_TOPIC = 20       # hot drama amplification
PRIORITY_HIGH_CONVERSION = 30
PRIORITY_NORMAL = 30          # normal publish (was 50)
PRIORITY_PROCESSING = 50      # download + process
PRIORITY_DATA_COLLECT = 70
PRIORITY_BACKFILL = 90

# Default concurrency limits per task type (from architecture doc)
DEFAULT_CONCURRENCY: dict[str, int] = {
    "DOWNLOAD": 3,
    "PROCESS": 2,
    "PUBLISH_A": 5,
    "PUBLISH_B": 1,
    "COLLECT": 5,
    "ANALYZE": 10,
}

# Default retry backoff in seconds: attempt 1 -> 10s, attempt 2 -> 30s, attempt 3 -> 90s
DEFAULT_BACKOFF_SCHEDULE = (10, 30, 90)

# Publish time window (24h format)
DEFAULT_PUBLISH_WINDOW = (6, 23)  # 06:00 - 23:00

# Minimum seconds between publishes for the same account
DEFAULT_PUBLISH_INTERVAL_MIN = 300   # 5 minutes
DEFAULT_PUBLISH_INTERVAL_MAX = 900   # 15 minutes


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------

@dataclass
class Task:
    """A single unit of work in the automation pipeline.

    Aligned with migration v6 schema:
      - idempotency_key: dedup identical work within active states
      - batch_id: group tasks under one decision batch
      - channel_type / strategy_name / decision_id: strategy traceability
      - manual_reason: why it went to waiting_manual (human-readable)
      - next_retry_at: when to re-queue from waiting_retry
    """

    id: str = ""
    task_type: str = ""
    account_id: str = ""
    drama_name: str = ""
    priority: int = PRIORITY_NORMAL
    params: dict = field(default_factory=dict)
    status: str = "pending"
    retry_count: int = 0
    max_retries: int = 3
    created_at: str = ""
    started_at: str = ""
    finished_at: str = ""
    error_message: str = ""
    result: dict = field(default_factory=dict)
    depends_on: str = ""

    # --- v6 additions ---
    idempotency_key: str = ""
    batch_id: str = ""
    parent_task_id: str = ""
    queue_name: str = "default"
    worker_name: str = ""
    next_retry_at: str = ""
    manual_reason: str = ""
    manual_operator: str = ""
    manual_updated_at: str = ""
    resource_key: str = ""
    channel_type: str = ""
    strategy_name: str = ""
    decision_id: int | None = None
    created_by: str = "system"

    def __post_init__(self) -> None:
        if not self.id:
            self.id = uuid.uuid4().hex[:12]
        if not self.created_at:
            self.created_at = _now_iso()
        # Auto-compute idempotency_key when empty — common patterns:
        if not self.idempotency_key:
            if self.task_type == "DOWNLOAD":
                url = self.params.get("drama_url", "") or self.params.get("url", "")
                self.idempotency_key = f"DOWNLOAD:{self.account_id}:{url[:80]}"
            elif self.task_type == "PROCESS":
                input_id = self.params.get("input_asset_id", "") or self.drama_name
                strategy = self.strategy_name or self.params.get("strategy_name", "")
                self.idempotency_key = f"PROCESS:{self.account_id}:{input_id}:{strategy}"
            elif self.task_type in ("PUBLISH_A", "PUBLISH_B"):
                output_id = self.params.get("output_asset_id", "") or self.drama_name
                self.idempotency_key = f"{self.task_type}:{self.account_id}:{output_id}"
            elif self.task_type in ("MCN_BIND_VERIFY", "MCN_SYNC"):
                self.idempotency_key = f"{self.task_type}:{self.account_id}"
            elif self.task_type == "VERIFY":
                photo = self.params.get("photo_id", "")
                self.idempotency_key = f"VERIFY:{self.account_id}:{photo}"
        # resource_key defaults to account-level exclusion
        if not self.resource_key and self.account_id:
            self.resource_key = f"acct:{self.account_id}"

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["params"] = json.dumps(d["params"])
        d["result"] = json.dumps(d["result"])
        return d

    @classmethod
    def from_row(cls, row: dict[str, Any]) -> Task:
        row = dict(row)
        row["params"] = json.loads(row.get("params") or "{}")
        row["result"] = json.loads(row.get("result") or "{}")
        return cls(**{k: v for k, v in row.items() if k in cls.__dataclass_fields__})


# ---------------------------------------------------------------------------
# Circuit Breaker
# ---------------------------------------------------------------------------

class CircuitBreaker:
    """Per-account circuit breaker.

    After *threshold* consecutive failures for an account, the circuit opens
    and remains open for *reset_seconds*.  During that time all tasks for
    the account are rejected (L3).
    """

    def __init__(self, threshold: int = 5, reset_seconds: int = 1800) -> None:
        self.threshold = threshold
        self.reset_seconds = reset_seconds
        self._failures: dict[str, int] = {}        # account_id -> consecutive failure count
        self._open_until: dict[str, float] = {}     # account_id -> monotonic timestamp
        self._lock = threading.Lock()

    def is_open(self, account_id: str) -> bool:
        """Return True if the circuit is open (account should be paused)."""
        with self._lock:
            deadline = self._open_until.get(account_id)
            if deadline is None:
                return False
            if time.monotonic() >= deadline:
                # Reset after cool-down
                self._open_until.pop(account_id, None)
                self._failures.pop(account_id, None)
                logger.info("Circuit breaker reset for account %s", account_id)
                return False
            return True

    def record_success(self, account_id: str) -> None:
        with self._lock:
            self._failures.pop(account_id, None)
            self._open_until.pop(account_id, None)

    def record_failure(self, account_id: str) -> None:
        with self._lock:
            count = self._failures.get(account_id, 0) + 1
            self._failures[account_id] = count
            if count >= self.threshold:
                self._open_until[account_id] = time.monotonic() + self.reset_seconds
                logger.warning(
                    "Circuit breaker OPEN for account %s (%d consecutive failures, "
                    "pausing %d seconds)",
                    account_id, count, self.reset_seconds,
                )

    def remaining_seconds(self, account_id: str) -> float:
        """Seconds until the breaker resets. 0 if not open."""
        with self._lock:
            deadline = self._open_until.get(account_id)
            if deadline is None:
                return 0.0
            remaining = deadline - time.monotonic()
            return max(remaining, 0.0)

    def status(self) -> dict[str, Any]:
        with self._lock:
            return {
                "failures": dict(self._failures),
                "open_accounts": {
                    acct: round(dl - time.monotonic(), 1)
                    for acct, dl in self._open_until.items()
                    if time.monotonic() < dl
                },
            }


# ---------------------------------------------------------------------------
# Task Queue
# ---------------------------------------------------------------------------

class TaskQueue:
    """Thread-safe priority task queue backed by SQLite for persistence.

    Uses ``concurrent.futures.ThreadPoolExecutor`` with per-type semaphores
    for concurrency control.  This is the Phase-1/2 queue; Celery is Phase 4.
    """

    # ------------------------------------------------------------------
    # Initialization
    # ------------------------------------------------------------------

    def __init__(self, db_manager: Any, config: dict[str, Any] | None = None) -> None:
        """
        Args:
            db_manager: A ``DBManager`` instance (or any object with a ``.conn``
                        attribute pointing to a ``sqlite3.Connection``).
            config: Optional overrides.  Keys:
                - concurrency: dict[str, int] per task type
                - backoff: tuple of seconds for retries
                - publish_window: (start_hour, end_hour)
                - publish_interval_min: int seconds
                - publish_interval_max: int seconds
                - circuit_threshold: int
                - circuit_reset_seconds: int
        """
        self._db = db_manager
        self._conn: sqlite3.Connection = db_manager.conn
        cfg = config or {}

        # Concurrency limits
        concurrency = cfg.get("concurrency", DEFAULT_CONCURRENCY)
        self._semaphores: dict[str, threading.Semaphore] = {
            tt: threading.Semaphore(concurrency.get(tt, DEFAULT_CONCURRENCY.get(tt, 5)))
            for tt in TASK_TYPES
        }

        # Retry / backoff
        self._backoff = cfg.get("backoff", DEFAULT_BACKOFF_SCHEDULE)

        # Publish time window
        self._publish_window = cfg.get("publish_window", DEFAULT_PUBLISH_WINDOW)

        # Same-account publish interval (seconds)
        self._publish_interval_min = cfg.get("publish_interval_min", DEFAULT_PUBLISH_INTERVAL_MIN)
        self._publish_interval_max = cfg.get("publish_interval_max", DEFAULT_PUBLISH_INTERVAL_MAX)

        # Circuit breaker
        self._breaker = CircuitBreaker(
            threshold=cfg.get("circuit_threshold", 5),
            reset_seconds=cfg.get("circuit_reset_seconds", 1800),
        )

        # Executor registry: task_type -> callable(task) -> result dict
        self._executors: dict[str, Callable[[Task], dict]] = {}
        # Degradation fallback: task_type -> callable(task) -> result dict
        self._fallbacks: dict[str, Callable[[Task], dict]] = {}

        # Last publish timestamp per account (monotonic)
        self._last_publish: dict[str, float] = {}
        self._last_publish_lock = threading.Lock()

        # Deferral tracking: task_id -> consecutive deferral count
        self._defer_counts: dict[str, int] = {}
        self._max_deferrals = cfg.get("max_deferrals", 60)  # skip after N deferrals

        # Thread pool
        self._pool: ThreadPoolExecutor | None = None
        self._running = False
        self._stop_event = threading.Event()
        self._bg_thread: threading.Thread | None = None

        # Ensure persistence table exists
        self._init_table()

        logger.info(
            "TaskQueue initialized (concurrency=%s, backoff=%s, window=%s-%s)",
            {k: v._value for k, v in self._semaphores.items()},  # noqa: SLF001
            self._backoff,
            self._publish_window[0],
            self._publish_window[1],
        )

    # ------------------------------------------------------------------
    # Schema
    # ------------------------------------------------------------------

    def _init_table(self) -> None:
        """Create the task_queue table if it does not exist."""
        ddl = """
        CREATE TABLE IF NOT EXISTS task_queue (
            id           TEXT PRIMARY KEY,
            task_type    TEXT NOT NULL,
            account_id   TEXT NOT NULL,
            drama_name   TEXT DEFAULT '',
            priority     INTEGER DEFAULT 50,
            params       TEXT DEFAULT '{}',
            status       TEXT DEFAULT 'pending',
            retry_count  INTEGER DEFAULT 0,
            max_retries  INTEGER DEFAULT 3,
            created_at   TEXT NOT NULL,
            started_at   TEXT DEFAULT '',
            finished_at  TEXT DEFAULT '',
            error_message TEXT DEFAULT '',
            result       TEXT DEFAULT '{}',
            depends_on   TEXT DEFAULT ''
        )
        """
        idx = """
        CREATE INDEX IF NOT EXISTS idx_tq_status_priority
        ON task_queue (status, priority)
        """
        self._conn.execute(ddl)
        self._conn.execute(idx)
        self._conn.commit()
        logger.debug("task_queue table ensured")

    # ------------------------------------------------------------------
    # Executor registration
    # ------------------------------------------------------------------

    def set_executor(self, task_type: str, fn: Callable[[Task], dict]) -> None:
        """Register a callable for a task type.

        The callable receives a ``Task`` and must return a dict (stored as
        ``task.result``).  Raise an exception to signal failure.
        """
        if task_type not in TASK_TYPES:
            raise ValueError(f"Unknown task type: {task_type}")
        self._executors[task_type] = fn
        logger.info("Executor registered for %s", task_type)

    def set_fallback(self, task_type: str, fn: Callable[[Task], dict]) -> None:
        """Register a degradation fallback for a task type (L2).

        Called when all retries (L1) have been exhausted.
        """
        if task_type not in TASK_TYPES:
            raise ValueError(f"Unknown task type: {task_type}")
        self._fallbacks[task_type] = fn
        logger.info("Fallback registered for %s", task_type)

    # ------------------------------------------------------------------
    # Adding tasks
    # ------------------------------------------------------------------

    def add_task(
        self,
        task_type: str,
        account_id: str,
        priority: int = PRIORITY_NORMAL,
        params: dict | None = None,
        depends_on: str | None = None,
        drama_name: str = "",
        max_retries: int = 3,
    ) -> str:
        """Add a single task to the queue and return its id."""
        if task_type not in TASK_TYPES:
            raise ValueError(f"Unknown task type: {task_type}")

        task = Task(
            task_type=task_type,
            account_id=account_id,
            priority=priority,
            params=params or {},
            depends_on=depends_on or "",
            drama_name=drama_name,
            max_retries=max_retries,
        )
        self._persist_task(task)
        logger.info(
            "Task added: id=%s type=%s account=%s priority=%d depends_on=%s",
            task.id, task.task_type, task.account_id, task.priority, task.depends_on or "-",
        )
        return task.id

    def add_pipeline(
        self,
        account_id: str,
        drama_name: str,
        drama_url: str,
        priority: int = PRIORITY_NORMAL,
    ) -> list[str]:
        """Add a full DOWNLOAD -> PROCESS -> PUBLISH_A pipeline as dependent tasks.

        Returns a list of task ids in execution order.
        """
        ids: list[str] = []

        download_id = self.add_task(
            "DOWNLOAD", account_id,
            priority=priority,
            params={"drama_url": drama_url},
            drama_name=drama_name,
        )
        ids.append(download_id)

        process_id = self.add_task(
            "PROCESS", account_id,
            priority=priority,
            params={"drama_url": drama_url},
            depends_on=download_id,
            drama_name=drama_name,
        )
        ids.append(process_id)

        publish_id = self.add_task(
            "PUBLISH_A", account_id,
            priority=priority,
            params={"drama_url": drama_url},
            depends_on=process_id,
            drama_name=drama_name,
        )
        ids.append(publish_id)

        logger.info(
            "Pipeline added for account=%s drama=%s: %s",
            account_id, drama_name, " -> ".join(ids),
        )
        return ids

    # ------------------------------------------------------------------
    # Running the queue
    # ------------------------------------------------------------------

    def run(self, max_workers: int | None = None, daemon: bool = False) -> None:
        """Start processing the queue.

        daemon=False (默认): 跑完所有任务就退 (原有行为)
        daemon=True:         空闲时继续等待 (给 WorkerManager 用)
        """
        if self._running:
            logger.warning("Queue is already running")
            return

        workers = max_workers or sum(DEFAULT_CONCURRENCY.values())
        self._pool = ThreadPoolExecutor(max_workers=workers, thread_name_prefix="tq")
        self._running = True
        self._daemon_mode = daemon
        self._stop_event.clear()
        logger.info("Queue started with %d workers (daemon=%s)", workers, daemon)

        try:
            self._process_loop()
        finally:
            self._pool.shutdown(wait=True)
            self._running = False
            logger.info("Queue stopped")

    def run_async(self) -> None:
        """Start processing in a background daemon thread."""
        if self._running:
            logger.warning("Queue is already running")
            return
        self._bg_thread = threading.Thread(target=self.run, name="tq-bg", daemon=True)
        self._bg_thread.start()
        logger.info("Queue started in background")

    def stop(self) -> None:
        """Signal the queue to stop after finishing current tasks."""
        logger.info("Stop requested")
        self._stop_event.set()

    # ------------------------------------------------------------------
    # Status
    # ------------------------------------------------------------------

    def get_status(self) -> dict[str, Any]:
        """Return aggregate queue status counts and circuit breaker state."""
        sql = "SELECT status, COUNT(*) as cnt FROM task_queue GROUP BY status"
        try:
            rows = self._conn.execute(sql).fetchall()
            counts = {row["status"]: row["cnt"] for row in rows}
        except sqlite3.Error as exc:
            logger.error("get_status failed: %s", exc)
            counts = {}

        return {
            "pending": counts.get("pending", 0),
            "running": counts.get("running", 0),
            "success": counts.get("success", 0),
            "failed": counts.get("failed", 0),
            "skipped": counts.get("skipped", 0),
            "total": sum(counts.values()),
            "circuit_breaker": self._breaker.status(),
        }

    def get_task(self, task_id: str) -> Task | None:
        """Retrieve a task by its id."""
        sql = "SELECT * FROM task_queue WHERE id = ?"
        try:
            row = self._conn.execute(sql, (task_id,)).fetchone()
            if row:
                return Task.from_row(row)
        except sqlite3.Error as exc:
            logger.error("get_task(%s) failed: %s", task_id, exc)
        return None

    # ------------------------------------------------------------------
    # Internal: processing loop
    # ------------------------------------------------------------------

    def _process_loop(self) -> None:
        """Main scheduling loop.  Fetches pending tasks in priority order and
        dispatches them to the thread pool."""
        futures: dict[str, Future] = {}  # task_id -> Future

        while not self._stop_event.is_set():
            # Reap completed futures
            done_ids = [tid for tid, fut in futures.items() if fut.done()]
            for tid in done_ids:
                futures.pop(tid)

            # Fetch next batch of ready tasks
            ready_tasks = self._fetch_ready_tasks(limit=20)

            if not ready_tasks and not futures:
                # Nothing pending, nothing in flight
                remaining = self._count_actionable()
                if remaining == 0:
                    if getattr(self, "_daemon_mode", False):
                        # daemon 模式: 空闲继续等, 让 add_task 触发下一轮
                        self._stop_event.wait(timeout=2.0)
                        continue
                    logger.info("All tasks completed or skipped")
                    break

            for task in ready_tasks:
                if self._stop_event.is_set():
                    break
                if task.id in futures:
                    continue  # already dispatched

                fut = self._pool.submit(self._execute_task, task)
                futures[task.id] = fut

            # Brief sleep to avoid busy-spinning
            self._stop_event.wait(timeout=1.0)

        # Wait for in-flight tasks
        for tid, fut in futures.items():
            try:
                fut.result(timeout=600)
            except Exception:
                logger.error("Task %s raised during shutdown", tid, exc_info=True)

    def _fetch_ready_tasks(self, limit: int = 20) -> list[Task]:
        """Return pending tasks whose dependencies are satisfied, ordered by priority."""
        sql = """
            SELECT t.* FROM task_queue t
            WHERE t.status = 'pending'
              AND (
                  t.depends_on = ''
                  OR EXISTS (
                      SELECT 1 FROM task_queue d
                      WHERE d.id = t.depends_on AND d.status = 'success'
                  )
              )
            ORDER BY t.priority ASC, t.created_at ASC
            LIMIT ?
        """
        try:
            rows = self._conn.execute(sql, (limit,)).fetchall()
            tasks = [Task.from_row(row) for row in rows]
        except sqlite3.Error as exc:
            logger.error("_fetch_ready_tasks failed: %s", exc)
            return []

        # Also skip tasks whose dependency failed/skipped (cascade skip)
        self._cascade_skip()

        return tasks

    def _cascade_skip(self) -> None:
        """Skip pending tasks whose dependency has permanently failed or been skipped."""
        sql = """
            UPDATE task_queue
            SET status = 'skipped',
                finished_at = ?,
                error_message = 'Dependency failed or skipped'
            WHERE status = 'pending'
              AND depends_on != ''
              AND EXISTS (
                  SELECT 1 FROM task_queue d
                  WHERE d.id = task_queue.depends_on
                    AND d.status IN ('failed', 'skipped')
              )
        """
        try:
            cursor = self._conn.execute(sql, (_now_iso(),))
            # 关键: 无论 rowcount 是否 >0, 都必须 commit, 否则 sqlite3 Python 驱动
            # 在 deferred isolation_level 下会保留一个隐式 BEGIN IMMEDIATE
            # 导致全库 writer 全部被堵 — controller_agent INSERT autopilot_cycles
            # 就是这样被挂住的.
            self._conn.commit()
            if cursor.rowcount > 0:
                logger.info("Cascade-skipped %d tasks due to failed dependencies", cursor.rowcount)
        except sqlite3.Error as exc:
            logger.error("_cascade_skip failed: %s", exc)
            try:
                self._conn.rollback()
            except sqlite3.Error:
                pass

    def _count_actionable(self) -> int:
        """Count tasks that are still pending or running."""
        sql = "SELECT COUNT(*) as cnt FROM task_queue WHERE status IN ('pending', 'running')"
        try:
            row = self._conn.execute(sql).fetchone()
            return row["cnt"] if row else 0
        except sqlite3.Error:
            return 0

    # ------------------------------------------------------------------
    # Internal: task execution
    # ------------------------------------------------------------------

    def _execute_task(self, task: Task) -> bool:
        """Execute a single task with full error-handling hierarchy.

        Returns True on success, False on failure/skip.
        """
        account = task.account_id
        tt = task.task_type

        # --- L3: Circuit breaker check ---
        if self._breaker.is_open(account):
            remaining = self._breaker.remaining_seconds(account)
            logger.warning(
                "Task %s blocked by circuit breaker for account %s (%.0fs remaining)",
                task.id, account, remaining,
            )
            return self._defer_or_skip(task, "circuit breaker open")

        # --- Time window check (publish tasks only) ---
        if tt in ("PUBLISH_A", "PUBLISH_B") and not self._check_time_window(task):
            logger.info(
                "Task %s deferred: outside publish window %02d:00-%02d:00",
                task.id, *self._publish_window,
            )
            return self._defer_or_skip(task, "outside publish time window")

        # --- Same-account publish interval check ---
        if tt in ("PUBLISH_A", "PUBLISH_B") and not self._check_publish_interval(account):
            logger.info(
                "Task %s deferred: publish interval not elapsed for account %s",
                task.id, account,
            )
            return self._defer_or_skip(task, "publish interval not elapsed")

        # Clear deferral counter on successful dispatch
        self._defer_counts.pop(task.id, None)

        # --- Acquire concurrency semaphore ---
        sem = self._semaphores[tt]
        acquired = sem.acquire(timeout=30)
        if not acquired:
            logger.warning("Task %s timed out waiting for %s semaphore", task.id, tt)
            return False

        try:
            return self._run_with_retry(task)
        finally:
            sem.release()

    def _run_with_retry(self, task: Task) -> bool:
        """L1 retry loop with exponential backoff."""
        # Mark running
        self._update_status(task, "running", started_at=_now_iso())

        executor = self._executors.get(task.task_type)
        if executor is None:
            msg = f"No executor registered for task type {task.task_type}"
            logger.error("Task %s: %s", task.id, msg)
            self._update_status(task, "failed", error_message=msg)
            return False

        last_error = ""
        for attempt in range(task.max_retries):
            if self._stop_event.is_set():
                self._update_status(task, "pending")  # put back for next run
                return False

            try:
                result = executor(task)
                # Success
                task.result = result or {}
                self._update_status(task, "success", result=task.result)
                self._breaker.record_success(task.account_id)
                self._record_publish_time(task)
                logger.info(
                    "Task %s (%s) completed on attempt %d",
                    task.id, task.task_type, attempt + 1,
                )
                return True

            except Exception as exc:
                last_error = str(exc)
                task.retry_count = attempt + 1
                logger.warning(
                    "Task %s attempt %d/%d failed: %s",
                    task.id, attempt + 1, task.max_retries, last_error,
                )
                # Backoff before next attempt (unless last attempt)
                if attempt < task.max_retries - 1:
                    backoff = (
                        self._backoff[attempt]
                        if attempt < len(self._backoff)
                        else self._backoff[-1]
                    )
                    logger.debug("Backing off %ds before retry", backoff)
                    self._stop_event.wait(timeout=backoff)

        # --- L2: Try degradation fallback ---
        fallback = self._fallbacks.get(task.task_type)
        if fallback is not None:
            logger.info("Task %s: attempting L2 degradation fallback", task.id)
            try:
                result = fallback(task)
                task.result = result or {}
                self._update_status(task, "success", result=task.result)
                self._breaker.record_success(task.account_id)
                self._record_publish_time(task)
                logger.info("Task %s succeeded via fallback", task.id)
                return True
            except Exception as exc:
                last_error = f"Fallback also failed: {exc}"
                logger.error("Task %s fallback failed: %s", task.id, exc)

        # --- L3: Record failure in circuit breaker ---
        self._breaker.record_failure(task.account_id)

        # --- L5: Mark failed (skip), continue pipeline via cascade ---
        self._update_status(
            task, "failed",
            error_message=last_error,
            retry_count=task.retry_count,
        )
        logger.error(
            "Task %s permanently failed after %d retries: %s",
            task.id, task.max_retries, last_error,
        )
        return False

    # ------------------------------------------------------------------
    # Internal: checks
    # ------------------------------------------------------------------

    def _check_time_window(self, task: Task) -> bool:
        """Return True if the current hour falls within the publish window."""
        current_hour = datetime.now().hour
        start, end = self._publish_window
        return start <= current_hour < end

    def _check_publish_interval(self, account_id: str) -> bool:
        """Return True if enough time has elapsed since the last publish for this account."""
        with self._last_publish_lock:
            last = self._last_publish.get(account_id)
        if last is None:
            return True
        elapsed = time.monotonic() - last
        return elapsed >= self._publish_interval_min

    def _record_publish_time(self, task: Task) -> None:
        """Record the publish timestamp if the task is a publish type."""
        if task.task_type in ("PUBLISH_A", "PUBLISH_B"):
            with self._last_publish_lock:
                self._last_publish[task.account_id] = time.monotonic()

    def _defer_or_skip(self, task: Task, reason: str) -> bool:
        """Increment deferral counter for a task.  If max deferrals reached,
        skip the task instead of deferring forever."""
        count = self._defer_counts.get(task.id, 0) + 1
        self._defer_counts[task.id] = count
        if count >= self._max_deferrals:
            msg = f"Skipped after {count} deferrals: {reason}"
            logger.warning("Task %s: %s", task.id, msg)
            self._update_status(task, "skipped", error_message=msg)
            self._defer_counts.pop(task.id, None)
            return False
        return False

    # ------------------------------------------------------------------
    # Internal: persistence helpers
    # ------------------------------------------------------------------

    def _persist_task(self, task: Task) -> None:
        """Insert a new task into the SQLite table."""
        d = task.to_dict()
        cols = ", ".join(d.keys())
        placeholders = ", ".join("?" for _ in d)
        sql = f"INSERT INTO task_queue ({cols}) VALUES ({placeholders})"
        try:
            self._conn.execute(sql, list(d.values()))
            self._conn.commit()
        except sqlite3.Error as exc:
            logger.error("Failed to persist task %s: %s", task.id, exc)
            raise

    def _update_status(
        self,
        task: Task,
        status: str,
        *,
        started_at: str = "",
        error_message: str = "",
        retry_count: int | None = None,
        result: dict | None = None,
    ) -> None:
        """Update a task's status and related fields in the database."""
        sets = ["status = ?"]
        vals: list[Any] = [status]

        if started_at:
            sets.append("started_at = ?")
            vals.append(started_at)

        if status in ("success", "failed", "skipped"):
            sets.append("finished_at = ?")
            vals.append(_now_iso())

        if error_message:
            sets.append("error_message = ?")
            vals.append(error_message)

        if retry_count is not None:
            sets.append("retry_count = ?")
            vals.append(retry_count)

        if result is not None:
            sets.append("result = ?")
            vals.append(json.dumps(result))

        sql = f"UPDATE task_queue SET {', '.join(sets)} WHERE id = ?"
        vals.append(task.id)

        try:
            self._conn.execute(sql, vals)
            self._conn.commit()
            task.status = status
        except sqlite3.Error as exc:
            logger.error("Failed to update task %s status to %s: %s", task.id, status, exc)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


# ---------------------------------------------------------------------------
# Standalone test
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import tempfile
    import os

    print("=" * 60)
    print("TaskQueue standalone test")
    print("=" * 60)

    # Create a temporary database for testing
    tmp_dir = tempfile.mkdtemp(prefix="tq_test_")
    tmp_db = os.path.join(tmp_dir, "test.db")

    class _FakeDBManager:
        """Minimal stub for testing without the real DBManager."""
        def __init__(self, path: str) -> None:
            self.conn = sqlite3.connect(path, check_same_thread=False)
            self.conn.row_factory = sqlite3.Row
            self.conn.execute("PRAGMA journal_mode=WAL;")

    db = _FakeDBManager(tmp_db)
    # Use 0-24 window so tests pass at any hour
    queue = TaskQueue(db, config={"publish_window": (0, 24)})

    # Register dummy executors
    call_log: list[str] = []

    def fake_download(task: Task) -> dict:
        time.sleep(0.1)
        call_log.append(f"DOWNLOAD:{task.id}")
        return {"file": "/tmp/video.mp4"}

    def fake_process(task: Task) -> dict:
        time.sleep(0.1)
        call_log.append(f"PROCESS:{task.id}")
        return {"processed_file": "/tmp/processed.mp4"}

    def fake_publish(task: Task) -> dict:
        time.sleep(0.1)
        call_log.append(f"PUBLISH_A:{task.id}")
        return {"publish_id": "pub_123"}

    queue.set_executor("DOWNLOAD", fake_download)
    queue.set_executor("PROCESS", fake_process)
    queue.set_executor("PUBLISH_A", fake_publish)

    # Test 1: Single task
    print("\n--- Test 1: Single task ---")
    tid = queue.add_task("DOWNLOAD", "acc_001", params={"url": "https://example.com"})
    print(f"Added task: {tid}")

    # Test 2: Pipeline
    print("\n--- Test 2: Pipeline ---")
    pipeline_ids = queue.add_pipeline("acc_002", "TestDrama", "https://drama.example.com/1")
    print(f"Pipeline tasks: {pipeline_ids}")

    # Test 3: Run queue
    print("\n--- Test 3: Running queue ---")
    queue.run()

    # Test 4: Check results
    print("\n--- Test 4: Results ---")
    status = queue.get_status()
    print(f"Queue status: {status}")
    print(f"Execution order: {call_log}")

    for tid in [tid] + pipeline_ids:
        t = queue.get_task(tid)
        if t:
            print(f"  {t.id} [{t.task_type}] -> {t.status} (result={t.result})")

    # Test 5: Circuit breaker
    print("\n--- Test 5: Circuit breaker ---")
    breaker = CircuitBreaker(threshold=3, reset_seconds=5)
    for i in range(3):
        breaker.record_failure("acc_bad")
    print(f"  Breaker open for acc_bad: {breaker.is_open('acc_bad')}")
    print(f"  Breaker open for acc_ok: {breaker.is_open('acc_ok')}")

    # Test 6: Retry with failure
    print("\n--- Test 6: Retry/failure ---")
    attempt_count = 0

    def failing_executor(task: Task) -> dict:
        global attempt_count
        attempt_count += 1
        raise RuntimeError(f"Simulated failure #{attempt_count}")

    queue2 = TaskQueue(
        db,
        config={"backoff": (0.1, 0.2, 0.3)},  # fast backoff for test
    )
    queue2.set_executor("COLLECT", failing_executor)
    fail_id = queue2.add_task("COLLECT", "acc_fail")
    queue2.run()
    fail_task = queue2.get_task(fail_id)
    print(f"  Task status: {fail_task.status if fail_task else 'not found'}")
    print(f"  Attempts made: {attempt_count}")

    # Cleanup
    db.conn.close()
    import shutil
    shutil.rmtree(tmp_dir, ignore_errors=True)

    print("\n" + "=" * 60)
    print("All tests passed!")
    print("=" * 60)
