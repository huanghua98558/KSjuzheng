# -*- coding: utf-8 -*-
"""Account Executor — 多账号并发 worker 池.

架构:
  1 个 Executor 进程 + N 个 worker 线程 (N = executor.worker_count)
  每个 worker 独立轮询 task_queue, 领到 task 就跑 pipeline

领任务原子性:
  UPDATE task_queue SET status='running', worker_name=? WHERE id=(
    SELECT id FROM task_queue
    WHERE status='queued' AND (next_retry_at IS NULL OR next_retry_at <= datetime('now'))
    ORDER BY priority DESC, created_at ASC LIMIT 1
  ) AND status='queued'  -- 防止双领

任务类型当前只支持 PUBLISH, pipeline 含 download/process/publish/verify
"""
from __future__ import annotations

import json
import logging
import sqlite3
import threading
import time
import uuid
from typing import Any

from core.app_config import get as cfg_get
from core.executor.pipeline import run_publish_pipeline
from core.notifier import notify

log = logging.getLogger(__name__)


def _connect():
    from core.config import DB_PATH
    c = sqlite3.connect(DB_PATH, timeout=15, check_same_thread=False)
    c.execute("PRAGMA busy_timeout=10000")
    c.row_factory = sqlite3.Row
    return c


def _claim_task(worker_name: str, task_types: list[str]) -> dict | None:
    """原子地领一个 task. 返回 task dict 或 None.

    ★ 2026-04-24 v6 A2 — 改写为 INSERT-based 互斥锁:
      - account_locks 表: account_id 做 PRIMARY KEY, 天然互斥
      - BEGIN IMMEDIATE 拿写锁, 防并发 SELECT/UPDATE race
      - 过期锁自动清 (15 分钟无释放)

    老版本 compare-and-set 在 WAL + 多连接下不原子, 历史有 10 次同账号
    2 个 task 同时 running 的案例. 本版本用 PRIMARY KEY 做硬互斥.

    Returns:
        task dict 或 None (None = 无可领 / 被抢 / 账号已持锁)
    """
    placeholder = ",".join(["?"] * len(task_types))
    max_hold_min = int(cfg_get("executor.max_task_hold_minutes", 15) or 15)

    with _connect() as c:
        try:
            # ★ BEGIN IMMEDIATE 立即拿写锁 — 防并发 SELECT 同时看到 0 locks
            c.execute("BEGIN IMMEDIATE")
        except sqlite3.OperationalError:
            # 其他 worker 占着写锁, 等下轮
            return None

        try:
            # 1. 清过期锁 (死锁自愈: worker 挂掉 15min 后自动解)
            c.execute(
                """DELETE FROM account_locks
                   WHERE expires_at < datetime('now','localtime')"""
            )

            # 2. 挑候选 task (queued + 任意账号未上锁 + 可执行)
            row = c.execute(
                f"""SELECT q.id, q.account_id FROM task_queue q
                    WHERE q.status='queued'
                      AND q.task_type IN ({placeholder})
                      AND (q.next_retry_at IS NULL
                           OR q.next_retry_at <= datetime('now','localtime'))
                      AND NOT EXISTS (
                        SELECT 1 FROM account_locks l
                        WHERE l.account_id = CAST(q.account_id AS INTEGER)
                      )
                    ORDER BY q.priority DESC, q.created_at ASC LIMIT 1""",
                task_types,
            ).fetchone()
            if not row:
                c.rollback()
                return None

            task_id = row["id"]
            aid_raw = row["account_id"]
            try:
                account_id = int(aid_raw)
            except (ValueError, TypeError):
                # account_id 非数字 (如 maintenance 的 task), 跳过锁, 直接 claim
                account_id = None

            # 3. 原子获账号锁 (INSERT OR FAIL — 撞 PRIMARY KEY 直接失败)
            if account_id is not None:
                try:
                    c.execute(
                        """INSERT INTO account_locks
                             (account_id, worker_name, task_id, expires_at,
                              task_type, drama_name)
                           VALUES (?, ?, ?,
                                   datetime('now', ?, 'localtime'),
                                   (SELECT task_type FROM task_queue WHERE id=?),
                                   (SELECT drama_name FROM task_queue WHERE id=?))""",
                        (account_id, worker_name, task_id,
                         f"+{max_hold_min} minutes", task_id, task_id),
                    )
                except sqlite3.IntegrityError:
                    # 被别的 worker 抢了 (PRIMARY KEY 冲突)
                    c.rollback()
                    return None

            # 4. 标 task running (只 queued 能变, TOCTOU 保护)
            cur = c.execute(
                """UPDATE task_queue SET
                     status='running', worker_name=?,
                     started_at=datetime('now','localtime')
                   WHERE id=? AND status='queued'""",
                (worker_name, task_id),
            )
            if cur.rowcount == 0:
                # 被别的 worker 改了 status, rollback 释锁
                c.rollback()
                return None

            c.commit()

            # 5. 返完整 task
            r = c.execute("SELECT * FROM task_queue WHERE id=?", (task_id,)).fetchone()
            return dict(r) if r else None
        except Exception:
            c.rollback()
            raise


def _release_account_lock(account_id: int | str, worker_name: str) -> None:
    """★ 2026-04-24 v6 A2: worker 完成 / 失败 task 后释放账号锁.

    用法: pipeline 的 finally 块里调用.
    即使没释放, 15 分钟后也会被过期清, 但显式释放更快.
    """
    try:
        aid = int(account_id)
    except (ValueError, TypeError):
        return   # 非数字 account (maintenance), 从未加锁
    try:
        with _connect() as c:
            c.execute(
                """DELETE FROM account_locks
                   WHERE account_id=? AND worker_name=?""",
                (aid, worker_name),
            )
            c.commit()
    except Exception as e:
        log.warning("[executor] release lock failed acc=%s: %s", aid, e)


def _schedule_retry(task_id: str, attempt: int) -> None:
    """把失败 task 重排到未来 (指数退避) 或转 dead_letter."""
    max_retries = cfg_get("executor.max_retries", 3)
    base = cfg_get("executor.retry_backoff_base", 30)
    if attempt >= max_retries:
        with _connect() as c:
            c.execute("UPDATE task_queue SET status='dead_letter' WHERE id=?", (task_id,))
            c.commit()
        log.warning("[executor] task %s → dead_letter after %d attempts", task_id, attempt)
        notify(f"任务死信: {task_id}",
               f"已重试 {attempt} 次仍失败",
               level="warning", source="executor",
               extra={"task_id": task_id, "attempts": attempt})
        return

    delay = base * (2 ** (attempt - 1))
    next_at = time.strftime("%Y-%m-%d %H:%M:%S",
                             time.localtime(time.time() + delay))
    with _connect() as c:
        c.execute(
            """UPDATE task_queue SET status='queued', retry_count=?,
                 next_retry_at=? WHERE id=?""",
            (attempt, next_at, task_id),
        )
        c.commit()
    log.info("[executor] task %s scheduled retry #%d at %s (+%ds)",
             task_id, attempt + 1, next_at, delay)


def _dispatch_task(task: dict, task_type: str) -> dict:
    """★ Phase 2 P2-2: 分发 task 到对应 handler.

    Returns:
        {ok: bool, retryable: bool, result?: dict, error?: str}
    """
    from core.task_manager import get_handler_for, is_publish_type

    task_id = task["id"]
    handler_path = get_handler_for(task_type)
    if not handler_path:
        log.warning("[dispatcher] unknown task_type=%s, mark failed", task_type)
        with _connect() as c:
            c.execute(
                "UPDATE task_queue SET status='failed', error_message=? WHERE id=?",
                (f"unknown task_type: {task_type}", task_id),
            )
            c.commit()
        return {"ok": False, "retryable": False,
                "error": f"unknown_task_type: {task_type}"}

    # 发布类共用 pipeline
    if is_publish_type(task_type):
        result = run_publish_pipeline(task)
        return {"ok": result.get("ok", False),
                "retryable": True,
                "result": result,
                "error": result.get("error")}

    # 其他 task_type 通过 importlib 动态加载
    try:
        module_path, fn_name = handler_path.rsplit(".", 1)
        import importlib
        mod = importlib.import_module(module_path)
        handler = getattr(mod, fn_name)
        result = handler(task)
        ok = result.get("ok", False) if isinstance(result, dict) else bool(result)
        return {"ok": ok, "retryable": True,
                "result": result if isinstance(result, dict) else {"raw": result}}
    except ModuleNotFoundError as e:
        # 维护类 handler 未实现时降级为 no-op success (P2-9 后补)
        log.warning("[dispatcher] handler not impl yet: %s (%s)", handler_path, e)
        with _connect() as c:
            c.execute(
                """UPDATE task_queue SET status='skipped',
                     error_message=?, finished_at=datetime('now','localtime')
                   WHERE id=?""",
                (f"handler not impl: {handler_path}", task_id),
            )
            c.commit()
        return {"ok": True, "retryable": False,
                "result": {"skipped": "handler_not_impl"}}
    except Exception as e:
        import traceback
        err = traceback.format_exc()[:500]
        log.exception("[dispatcher] %s handler crashed", task_type)
        with _connect() as c:
            c.execute(
                "UPDATE task_queue SET status='failed', error_message=? WHERE id=?",
                (f"{task_type} handler exc: {err}", task_id),
            )
            c.commit()
        return {"ok": False, "retryable": True, "error": err}


def _worker_loop(worker_name: str, stop_event: threading.Event,
                  task_types: list[str]) -> None:
    log.info("[executor] worker %s started", worker_name)
    poll_sec = cfg_get("executor.poll_interval_sec", 5)
    while not stop_event.is_set():
        task = _claim_task(worker_name, task_types)
        if not task:
            time.sleep(poll_sec)
            continue

        task_id = task["id"]
        task_type = task["task_type"]
        task_account_id = task.get("account_id")
        log.info("[worker=%s] claimed task=%s type=%s drama=%s",
                 worker_name, task_id, task_type, task.get("drama_name"))

        try:
            # ★ Phase 2 P2-2: 扩展 dispatcher 认全 task_type (ABCD)
            result = _dispatch_task(task, task_type)
            if not result.get("ok") and result.get("retryable", True):
                # pipeline/handler 内部已写 status=failed, 这里只看要不要重试
                attempt = (task.get("retry_count") or 0) + 1
                _schedule_retry(task_id, attempt)

            # ★ Phase 2 P2-1: batch 进度更新 (如果 task 属于某 batch)
            batch_id = task.get("batch_id")
            if batch_id:
                try:
                    from core.task_manager import mark_task_complete
                    mark_task_complete(batch_id, task_id,
                                        success=result.get("ok", False))
                except Exception as _e:
                    log.debug("[executor] mark_task_complete failed: %s", _e)

            # ★ Week 3 B-2 事件驱动补排: task 跑完, 立即看同账号有没有下一条 pending
            # 不等下一个 scheduler cron 扫 (默认 2h), 让账号 "一条完立即排下一条"
            acc = task.get("account_id")
            if acc:
                try:
                    from core.agents.task_scheduler_agent import trigger_next_for_account
                    res = trigger_next_for_account(acc)
                    if res.get("triggered"):
                        log.info("[worker=%s] event-driven enqueued next for acc=%s: task=%s",
                                 worker_name, acc, res.get("task_id"))
                except Exception as e:
                    log.debug("[worker=%s] trigger_next_for_account failed: %s",
                              worker_name, e)
        except Exception as e:
            import traceback
            err = traceback.format_exc()[:2000]
            log.exception("[worker=%s] task %s crashed", worker_name, task_id)
            with _connect() as c:
                c.execute(
                    """UPDATE task_queue SET status='failed',
                       error_message=?, finished_at=datetime('now','localtime')
                       WHERE id=?""",
                    (f"exception: {err[:500]}", task_id),
                )
                c.commit()
            attempt = (task.get("retry_count") or 0) + 1
            _schedule_retry(task_id, attempt)
            notify(f"Worker 崩溃: {task_id}",
                   f"{e}\n{err[:500]}",
                   level="error", source="executor")
        finally:
            # ★ 2026-04-24 v6 A2: task 结束 (success/fail/crash) 都释放账号锁
            # 即使忘释放, 15 分钟后也会被 _claim_task 的过期清理回收, 但显式更快
            if task_account_id is not None:
                _release_account_lock(task_account_id, worker_name)

    log.info("[executor] worker %s stopped", worker_name)


class Executor:
    """进程级单例. 启动 N 个 worker.

    ★ 2026-04-24 v6 Day 3: n_workers 默认从 operation_mode 读 (按当前档位).
      startup=2, growth=4, volume=8, matrix=12, scale=16.
      显式传 n_workers 参数 > cfg 显式设 > operation_mode 推荐值.

    ★ 2026-04-24 v6 Day 5-B: 三池预算 (burst / steady / maintenance).
      Executor 不再起 N 个共享 worker, 而是按 task_pools.allocate_workers()
      分到 3 池, 每池 worker 只消费自己 pool 的 task_type.
      避免 maintenance 塞住 steady, burst 独立 quota.
    """

    def __init__(self, n_workers: int | None = None,
                 task_types: list[str] | None = None,
                 use_pools: bool = True):
        """
        Args:
            n_workers:  总 worker (默认从 operation_mode 读)
            task_types: 指定 task_type 集 (legacy flat queue 模式). 若传, 强制
                        use_pools=False, 所有 worker 共享这组 type.
            use_pools:  True (默认) → 按 task_pools 分 3 池
                        False → legacy flat queue (与 v6 之前兼容)
        """
        if n_workers is None:
            cfg_n = cfg_get("executor.worker_count", None)
            if cfg_n is not None:
                n_workers = int(cfg_n)
            else:
                try:
                    from core.operation_mode import worker_count as _op_wc, current_mode
                    n_workers = int(_op_wc())
                    log.info("[executor] using operation_mode recommended n_workers=%d (mode=%s)",
                             n_workers, current_mode())
                except Exception as _e:
                    log.warning("[executor] operation_mode 不可用, fallback n_workers=2: %s", _e)
                    n_workers = 2
        self.n_workers = int(n_workers)

        # 如果用户传 task_types → flat queue 模式 (向后兼容)
        if task_types is not None:
            self.use_pools = False
            self.task_types = task_types
        else:
            self.use_pools = use_pools
            self.task_types = ["PUBLISH", "PUBLISH_DRAMA"]   # flat fallback

        self.stop_event = threading.Event()
        self.threads: list[threading.Thread] = []

    def start(self) -> None:
        if self.use_pools:
            self._start_pool_mode()
        else:
            self._start_flat_mode()

    def _start_pool_mode(self) -> None:
        """三池模式: 按 task_pools 分配 worker, 每池独立.

        日志 tag: worker-{pool}-{idx}  方便 dashboard 分池看进度.
        """
        try:
            from core.task_pools import allocate_workers, get_pool_task_types
            from core.operation_mode import should_burst, current_mode
            burst_en = should_burst()
            mode = current_mode()
        except Exception as _e:
            log.warning("[executor] 三池 runtime 解析失败, fallback flat: %s", _e)
            self._start_flat_mode()
            return

        alloc = allocate_workers(
            total=self.n_workers, burst_enabled=burst_en, mode=mode,
        )
        log.info("[executor] pool allocation: burst=%d steady=%d maint=%d "
                 "(total=%d, mode=%s, burst_en=%s, strategy=%s)",
                 alloc.burst, alloc.steady, alloc.maintenance,
                 alloc.total, mode, burst_en, alloc.strategy)

        pool_counts = {
            "burst": alloc.burst,
            "steady": alloc.steady,
            "maintenance": alloc.maintenance,
        }
        for pool_name, n in pool_counts.items():
            if n <= 0:
                continue
            task_types = get_pool_task_types(pool_name)
            if not task_types:
                log.warning("[executor] pool=%s 无 task_types, 跳过", pool_name)
                continue
            for i in range(n):
                name = f"worker-{pool_name}-{i+1}-{uuid.uuid4().hex[:4]}"
                t = threading.Thread(target=_worker_loop,
                                      args=(name, self.stop_event, task_types),
                                      name=name, daemon=True)
                t.start()
                self.threads.append(t)
                log.info("[executor]   → %s listening %s", name, task_types)

        if not self.threads:
            log.error("[executor] 三池全 0 worker! fallback flat")
            self._start_flat_mode()

    def _start_flat_mode(self) -> None:
        """Legacy: 所有 worker 共享同一 task_types 列表."""
        log.info("[executor] FLAT mode: %d workers for types=%s",
                 self.n_workers, self.task_types)
        for i in range(self.n_workers):
            name = f"worker-flat-{i+1}-{uuid.uuid4().hex[:4]}"
            t = threading.Thread(target=_worker_loop,
                                 args=(name, self.stop_event, self.task_types),
                                 name=name, daemon=True)
            t.start()
            self.threads.append(t)

    def stop(self, timeout: float = 10.0) -> None:
        log.info("[executor] stopping %d workers...", len(self.threads))
        self.stop_event.set()
        for t in self.threads:
            t.join(timeout=timeout)
        log.info("[executor] stopped.")


# ══════════════════════════════════════════════════════════════════════
# 顶层统计 API — 替代 WorkerManager (给 dashboard / api.py 调)
# 2026-04-24 v6 Day 5-C: WorkerManager 下线, 统计改读 task_queue + operation_mode
# ══════════════════════════════════════════════════════════════════════
def executor_status() -> dict:
    """返当前 Executor + queue 状态 (给 dashboard /execution/status 调)."""
    try:
        from core.operation_mode import current_mode, get_policy
        from core.task_pools import describe_allocation, POOL_MAP
        mode = current_mode()
        policy = get_policy()
        pool_desc = describe_allocation()
    except Exception as _e:
        mode = "unknown"
        policy = None
        pool_desc = {}

    # task_queue 活动度
    with _connect() as c:
        cnts = dict(
            c.execute(
                """SELECT status, COUNT(*) n FROM task_queue
                   WHERE created_at > datetime('now','-1 day','localtime')
                   GROUP BY status"""
            ).fetchall()
        )
        running_24h = int(cnts.get("running", 0))
        queued_24h = int(cnts.get("queued", 0))

        # 真正 running 的 (全时段)
        running_total = c.execute(
            "SELECT COUNT(*) FROM task_queue WHERE status='running'"
        ).fetchone()[0] or 0

        # 账号锁
        locks = c.execute(
            "SELECT COUNT(*) FROM account_locks"
        ).fetchone()[0] or 0

    return {
        "mode": mode,
        "worker_allocation": pool_desc.get("allocation", {}),
        "burst_enabled": pool_desc.get("burst_enabled", False),
        "queued_last_24h": queued_24h,
        "running_last_24h": running_24h,
        "running_total": running_total,
        "account_locks_held": locks,
        "running_by_type": cnts,
        "policy_summary": {
            "mode": policy.mode,
            "worker_count": policy.worker_count,
            "burst_enabled": policy.burst_enabled,
            "max_daily_items": policy.max_daily_items,
        } if policy else None,
    }


def executor_concurrency() -> dict:
    """按 task_type 统计当前 running 并发 (dashboard /execution 用)."""
    with _connect() as c:
        rows = c.execute(
            """SELECT task_type, COUNT(*) n FROM task_queue
               WHERE status='running' GROUP BY task_type"""
        ).fetchall()
    return {"concurrency": {r[0]: {"running": r[1]} for r in rows}}


def executor_running_tasks(limit: int = 50) -> list[dict]:
    """当前 running task list."""
    with _connect() as c:
        rows = c.execute(
            """SELECT id, task_type, account_id, drama_name,
                      started_at, worker_name, process_recipe
               FROM task_queue WHERE status='running'
               ORDER BY started_at DESC LIMIT ?""",
            (limit,),
        ).fetchall()
    return [dict(r) for r in rows]


def executor_logs(limit: int = 200, level: str | None = None) -> list[dict]:
    """返回近期日志. 没专用 log 表 → 返 task_queue 失败摘要 代替."""
    with _connect() as c:
        q = """SELECT id, task_type, status, error_message, finished_at
               FROM task_queue
               WHERE status IN ('failed', 'dead_letter')
               ORDER BY finished_at DESC LIMIT ?"""
        rows = c.execute(q, (limit,)).fetchall()
    return [
        {
            "task_id": r[0],
            "task_type": r[1],
            "status": r[2],
            "error": (r[3] or "")[:200],
            "at": r[4],
            "level": "error",
        }
        for r in rows
        if (level is None or level == "error")
    ]


def enqueue_publish_task(
    account_id: int,
    drama_name: str,
    banner_task_id: str | None = None,
    priority: int = 50,
    batch_id: str = "",
    params: dict | None = None,
    # ★ Phase 2 P2-5/6: 扩展支持 PUBLISH_BURST / PUBLISH_EXPERIMENT / 等
    task_type: str = "PUBLISH",
    task_source: str = "planner",  # planner / burst / experiment / maintenance
    source_metadata: dict | None = None,
    experiment_group: str | None = None,
    # ★ 2026-04-24 v6 A1: 默认填 idempotency_key + resource_key
    idempotency_key: str | None = None,
    resource_key: str | None = None,
) -> str:
    """往 task_queue 塞一个 PUBLISH 任务 (或变体), 返回 task id.

    Phase 2 扩展:
      - task_type: PUBLISH (默认) / PUBLISH_BURST (priority=99) / PUBLISH_EXPERIMENT
      - task_source: 标来源 (for dashboard 分类)
      - experiment_group: A/B/C (实验分组)
    """
    # task_id prefix 对齐来源
    prefix = {"burst": "brst", "experiment": "exp", "maintenance": "mnt"}.get(
        task_source, "pub"
    )
    task_id = f"{prefix}_{int(time.time()*1000)}_{uuid.uuid4().hex[:6]}"
    payload = params or {}
    if banner_task_id:
        payload["banner_task_id"] = banner_task_id

    # ★ 2026-04-22 §28_E: 把 process_recipe 同步写入专用列 (不只 params JSON)
    # 让 dashboard / report 能直接 SELECT process_recipe FROM task_queue
    # 不用每次 json.loads(params). 原因: 今日报告显示 "recipe=(none) 13 dead_letter"
    # 实际 params JSON 里有 recipe, 只是列为 NULL. 修显示 bug.
    process_recipe_col = None
    if isinstance(payload, dict):
        process_recipe_col = payload.get("process_recipe")

    # ★ 2026-04-24 v6 A1: idempotency_key / resource_key 默认填充
    # idempotency_key: (account, drama, date, task_type), SHA256 截 32 字符
    # 防止 burst / scheduler / healing 各自独立 enqueue 同账号同剧同日的任务
    # 下一步 migrate 会加 UNIQUE INDEX, 目前先填字段, 保证未来幂等
    if idempotency_key is None:
        import hashlib as _h
        today = time.strftime("%Y-%m-%d")
        seed = f"{account_id}:{drama_name}:{today}:{task_type}"
        idempotency_key = _h.sha256(seed.encode("utf-8")).hexdigest()[:32]

    # resource_key: 账号粒度 (用于账号级并发控制, 配合 account_locks 表使用)
    if resource_key is None:
        resource_key = f"account:{account_id}"

    with _connect() as c:
        try:
            c.execute(
                """INSERT INTO task_queue
                     (id, task_type, account_id, drama_name, priority, params,
                      status, retry_count, max_retries, created_at,
                      banner_task_id, batch_id, created_by, queue_name, channel_type,
                      task_source, experiment_group, source_metadata_json,
                      process_recipe, idempotency_key, resource_key)
                   VALUES (?, ?, ?, ?, ?, ?, 'queued', 0, ?,
                           datetime('now','localtime'), ?, ?, ?, 'default', 'api',
                           ?, ?, ?, ?, ?, ?)""",
                (task_id, task_type, str(account_id), drama_name, priority,
                 json.dumps(payload, ensure_ascii=False),
                 cfg_get("executor.max_retries", 3),
                 banner_task_id or "", batch_id, task_source,
                 task_source,
                 experiment_group,
                 json.dumps(source_metadata or {}, ensure_ascii=False),
                 process_recipe_col, idempotency_key, resource_key),
            )
            c.commit()
        except sqlite3.IntegrityError as e:
            # ★ 2026-04-24 v6 A1: idempotency_key UNIQUE 撞了
            # 说明同 (account, drama, date, type) 已有 task, 幂等返回已有 id
            if "idempotency_key" not in str(e):
                raise   # 其他 IntegrityError 正常抛 (如 PK 冲突)
            existing = c.execute(
                "SELECT id, status FROM task_queue WHERE idempotency_key=?",
                (idempotency_key,),
            ).fetchone()
            if existing:
                log.info("[executor] enqueue dedup: same idempotency_key → returning existing task=%s status=%s (skipped %s)",
                         existing[0], existing[1], task_id)
                return existing[0]
            raise   # 极端情况, 索引撞了但没行, 抛回
    log.info("[executor] enqueued task=%s type=%s source=%s account=%s drama=%s recipe=%s",
             task_id, task_type, task_source, account_id, drama_name,
             process_recipe_col or "(none)")
    return task_id


def queue_stats() -> dict:
    """看队列状态 (CLI / dashboard 用)."""
    with _connect() as c:
        rows = c.execute(
            "SELECT status, COUNT(*) FROM task_queue GROUP BY status"
        ).fetchall()
    return {r[0]: r[1] for r in rows}


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--start", action="store_true",
                    help="启动 executor (前台跑)")
    ap.add_argument("--workers", type=int, default=None)
    ap.add_argument("--stats", action="store_true")
    ap.add_argument("--enqueue", action="store_true",
                    help="enqueue 1 个测试 task")
    ap.add_argument("--account", type=int, default=3)
    ap.add_argument("--drama", default="陆总今天要离婚")
    args = ap.parse_args()

    import logging as _lg
    _lg.basicConfig(level=_lg.INFO, format="[%(asctime)s] %(levelname)s %(name)s %(message)s")

    if args.stats:
        print(queue_stats())
    elif args.enqueue:
        tid = enqueue_publish_task(args.account, args.drama)
        print(f"enqueued: {tid}")
    elif args.start:
        ex = Executor(n_workers=args.workers)
        ex.start()
        try:
            while True:
                time.sleep(30)
                print(f"[{time.strftime('%H:%M:%S')}] queue: {queue_stats()}")
        except KeyboardInterrupt:
            ex.stop()
    else:
        ap.print_help()
