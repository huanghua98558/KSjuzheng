# -*- coding: utf-8 -*-
"""统一熔断器 — 替代 3 处独立实现.

Week 1 Day 4 落地. v6 阶段 0 实时信号核心.

★ 背景:
  今天审计发现 3 处 MCN-touching 代码各自实现熔断:
    - mcn_drama_lookup.py: 60s timestamp (_MCN_UNHEALTHY_UNTIL)
    - mcn_url_realtime.py: 30s bool flag (_circuit_open)
    - sig_service.py: per-endpoint consecutive_fails (5 次 + 60s)
  3 种 API, 3 种 cooldown, 无统一信号给 planner/burst/watchdog 看 "MCN 是否健康".

★ 设计:
  CircuitBreaker 经典三状态机:
    CLOSED    -- 正常, 所有 call 直通
    OPEN      -- 熔断, 所有 call fast-fail + fallback
    HALF_OPEN -- 冷却时间过了, 允许 1 个 probe call 试探
                 → 成功转 CLOSED, 失败继续 OPEN

  全局注册表 (singleton dict):
    get_breaker("mcn_mysql") → 返回同一个实例, 跨模块共享
    get_breaker("sig3_50002") → per-endpoint 各自独立

  state transition 写 system_events + circuit_breaker_events (可选).

★ 消费方:
  from core.circuit_breaker import get_breaker
  br = get_breaker("mcn_mysql")

  # 手动用 (老代码迁移用):
  if not br.allow():
      return fallback
  try:
      result = do_mcn_call()
      br.mark_success()
  except Exception:
      br.mark_failure()
      raise

  # 或装饰器风格:
  @br.protect(fallback=lambda: [], catch=(Exception,))
  def query_mcn():
      return mcn_client.search(...)

★ MCN mode A/B 信号 (operation_mode 消费):
  from core.circuit_breaker import any_mcn_open, mcn_snapshot
  if any_mcn_open():
      return "B"   # degraded
  return "A"       # healthy
"""
from __future__ import annotations

import json
import logging
import sqlite3
import threading
import time
from enum import Enum

log = logging.getLogger(__name__)


class State(Enum):
    CLOSED = "closed"        # 健康, 所有请求直通
    OPEN = "open"            # 熔断, 拒绝请求
    HALF_OPEN = "half_open"  # 试探中, 允许 1 个 probe


class CircuitBreaker:
    """单资源熔断器.

    参数:
        name:            资源名 (比如 "mcn_mysql" / "sig3_50002")
        fail_threshold:  连续失败 N 次后跳 OPEN (默认 3)
        cooldown_sec:    OPEN 后 M 秒自动进 HALF_OPEN (默认 60)
        half_open_max:   HALF_OPEN 同时允许的 probe 数 (默认 1)

    线程安全 (threading.Lock).
    """

    def __init__(self, name: str, fail_threshold: int = 3,
                  cooldown_sec: float = 60.0, half_open_max: int = 1):
        self.name = name
        self.fail_threshold = fail_threshold
        self.cooldown_sec = cooldown_sec
        self.half_open_max = half_open_max

        self._lock = threading.Lock()
        self._state = State.CLOSED
        self._consecutive_fails = 0
        self._opened_at: float = 0.0   # 进入 OPEN 的时间戳
        self._half_open_probes = 0     # 当前正在 probe 的数量
        self._last_success: float = time.time()
        self._last_failure: float = 0.0
        self._total_failures = 0
        self._total_successes = 0
        self._transition_count = 0     # 总共切换了多少次 state

    # ──────────────────────────────────────────────────────
    # 基础 API
    # ──────────────────────────────────────────────────────
    def allow(self) -> bool:
        """是否放行请求. 包含状态机转移逻辑.

        CLOSED → True
        OPEN → 若冷却时间过, 转 HALF_OPEN + True; 否则 False
        HALF_OPEN → 若 probe 未满, True; 否则 False
        """
        with self._lock:
            now = time.time()
            if self._state is State.CLOSED:
                return True

            if self._state is State.OPEN:
                # 到冷却时间 → 试探
                if now - self._opened_at >= self.cooldown_sec:
                    self._state = State.HALF_OPEN
                    self._half_open_probes = 1
                    self._transition_count += 1
                    self._notify_transition(State.OPEN, State.HALF_OPEN,
                                             reason=f"cooldown_{self.cooldown_sec}s_elapsed")
                    return True
                return False

            # HALF_OPEN
            if self._half_open_probes < self.half_open_max:
                self._half_open_probes += 1
                return True
            return False

    def mark_success(self) -> None:
        """call 成功 — 可能关闭熔断."""
        with self._lock:
            old_state = self._state
            self._total_successes += 1
            self._last_success = time.time()
            self._consecutive_fails = 0

            if self._state is State.HALF_OPEN:
                # 试探成功 → 关闭
                self._state = State.CLOSED
                self._half_open_probes = 0
                self._transition_count += 1
                self._notify_transition(State.HALF_OPEN, State.CLOSED,
                                         reason="probe_success")
            elif self._state is State.OPEN:
                # 异常情况: 怎么 OPEN 下还能 mark_success? 理论上 allow() 挡了.
                # 但防御式: 仍重置到 CLOSED
                self._state = State.CLOSED
                self._transition_count += 1
                self._notify_transition(State.OPEN, State.CLOSED,
                                         reason="defensive_reset")
            # CLOSED → 保持

    def mark_failure(self, reason: str = "") -> None:
        """call 失败 — 可能打开熔断."""
        with self._lock:
            self._total_failures += 1
            self._consecutive_fails += 1
            self._last_failure = time.time()

            if self._state is State.HALF_OPEN:
                # 试探失败 → 立即 OPEN
                self._state = State.OPEN
                self._opened_at = time.time()
                self._half_open_probes = 0
                self._transition_count += 1
                self._notify_transition(State.HALF_OPEN, State.OPEN,
                                         reason=f"probe_fail: {reason[:80]}")
            elif self._state is State.CLOSED:
                # 检测阈值
                if self._consecutive_fails >= self.fail_threshold:
                    self._state = State.OPEN
                    self._opened_at = time.time()
                    self._transition_count += 1
                    self._notify_transition(State.CLOSED, State.OPEN,
                                             reason=f"fail_threshold_{self.fail_threshold}: {reason[:80]}")

    # ──────────────────────────────────────────────────────
    # 查询
    # ──────────────────────────────────────────────────────
    @property
    def state(self) -> State:
        return self._state

    def is_open(self) -> bool:
        return self._state is State.OPEN

    def is_closed(self) -> bool:
        return self._state is State.CLOSED

    def snapshot(self) -> dict:
        """返回当前状态快照 (给 dashboard / operation_mode 用)."""
        return {
            "name": self.name,
            "state": self._state.value,
            "consecutive_fails": self._consecutive_fails,
            "total_failures": self._total_failures,
            "total_successes": self._total_successes,
            "transition_count": self._transition_count,
            "last_success": self._last_success,
            "last_failure": self._last_failure,
            "opened_at": self._opened_at if self._state is not State.CLOSED else None,
            "seconds_until_half_open": max(
                0.0, self.cooldown_sec - (time.time() - self._opened_at)
            ) if self._state is State.OPEN else 0.0,
            "fail_threshold": self.fail_threshold,
            "cooldown_sec": self.cooldown_sec,
        }

    # ──────────────────────────────────────────────────────
    # 装饰器风格 (可选)
    # ──────────────────────────────────────────────────────
    def protect(self, fallback=None, catch: tuple = (Exception,),
                  raise_when_open: bool = False):
        """装饰器: 自动 allow/mark. 失败时返 fallback 或 raise.

        Args:
            fallback: 熔断打开时的 fallback (可调用或直接值)
            catch: 捕获什么类别的 exception → mark_failure
            raise_when_open: True 时熔断打开抛 CircuitBreakerOpenError
        """
        def decorator(fn):
            def wrapper(*args, **kwargs):
                if not self.allow():
                    if raise_when_open:
                        raise CircuitBreakerOpenError(self.name)
                    if callable(fallback):
                        return fallback(*args, **kwargs)
                    return fallback
                try:
                    result = fn(*args, **kwargs)
                    self.mark_success()
                    return result
                except catch as e:
                    self.mark_failure(reason=str(e)[:120])
                    raise
            wrapper.__wrapped__ = fn
            return wrapper
        return decorator

    # ──────────────────────────────────────────────────────
    # 内部: state 转移通知
    # ──────────────────────────────────────────────────────
    def _notify_transition(self, old: State, new: State, reason: str) -> None:
        """写 log + system_events + (可选) circuit_breaker_events."""
        level = logging.WARNING if new is State.OPEN else logging.INFO
        log.log(level, "[circuit:%s] %s → %s (%s)",
                self.name, old.value, new.value, reason)
        try:
            _log_to_db(self.name, old.value, new.value, reason, self.snapshot())
        except Exception:
            pass   # 日志失败不影响主流程


class CircuitBreakerOpenError(Exception):
    """熔断打开时抛 (若 protect(raise_when_open=True))."""
    def __init__(self, name: str):
        super().__init__(f"circuit breaker '{name}' is OPEN")
        self.name = name


# ──────────────────────────────────────────────────────
# Registry — singleton per name
# ──────────────────────────────────────────────────────
_REGISTRY: dict[str, CircuitBreaker] = {}
_REG_LOCK = threading.Lock()


def get_breaker(name: str, fail_threshold: int | None = None,
                  cooldown_sec: float | None = None) -> CircuitBreaker:
    """拿 (或建) 一个熔断器.

    首次调用会从 app_config 读:
      - circuit.{name}.fail_threshold  (默认 3)
      - circuit.{name}.cooldown_sec    (默认 60)
    参数显式传则覆盖 config.
    """
    with _REG_LOCK:
        if name in _REGISTRY:
            # 已有 — 用户若传新参数, 不改 (避免意外)
            return _REGISTRY[name]

        # 读 config
        ft = fail_threshold
        cd = cooldown_sec
        if ft is None or cd is None:
            try:
                from core.app_config import get as _cg
                if ft is None:
                    ft = int(_cg(f"circuit.{name}.fail_threshold", 3) or 3)
                if cd is None:
                    cd = float(_cg(f"circuit.{name}.cooldown_sec", 60) or 60)
            except Exception:
                ft = ft or 3
                cd = cd or 60.0

        br = CircuitBreaker(name, fail_threshold=int(ft), cooldown_sec=float(cd))
        _REGISTRY[name] = br
        return br


def list_all() -> dict[str, CircuitBreaker]:
    """所有已创建的 breaker (dashboard 用)."""
    with _REG_LOCK:
        return dict(_REGISTRY)


def snapshot_all() -> list[dict]:
    with _REG_LOCK:
        return [br.snapshot() for br in _REGISTRY.values()]


# ──────────────────────────────────────────────────────
# MCN mode A/B 信号 (给 operation_mode / planner 消费)
# ──────────────────────────────────────────────────────
# MCN-touching breakers 前缀 — 这些任一 open → MCN mode = B
_MCN_BREAKER_PREFIXES = ("mcn_", "sig3_")


def any_mcn_open() -> bool:
    """有任何 MCN-touching breaker 打开了吗? (快速判断 mode A/B)"""
    with _REG_LOCK:
        for name, br in _REGISTRY.items():
            if name.startswith(_MCN_BREAKER_PREFIXES) and br.is_open():
                return True
        return False


def mcn_snapshot() -> dict:
    """所有 MCN breaker 状态 — 给 dashboard 用."""
    out = {"mode": "A", "breakers": []}
    with _REG_LOCK:
        for name, br in _REGISTRY.items():
            if not name.startswith(_MCN_BREAKER_PREFIXES):
                continue
            snap = br.snapshot()
            out["breakers"].append(snap)
            if snap["state"] == "open":
                out["mode"] = "B"
    return out


# ──────────────────────────────────────────────────────
# DB 记录
# ──────────────────────────────────────────────────────
def _log_to_db(name: str, old: str, new: str, reason: str, snap: dict) -> None:
    """写 circuit_breaker_events + system_events (migrate_v42 建表)."""
    try:
        from core.config import DB_PATH
        with sqlite3.connect(DB_PATH, timeout=5) as c:
            c.execute("PRAGMA busy_timeout=5000")
            # circuit_breaker_events — 专用表
            c.execute(
                """INSERT INTO circuit_breaker_events
                     (breaker_name, old_state, new_state, reason, snapshot_json, occurred_at)
                   VALUES (?, ?, ?, ?, ?, datetime('now','localtime'))""",
                (name, old, new, reason[:200],
                 json.dumps(snap, default=str, ensure_ascii=False)),
            )
            # system_events — SSE 广播 (schema: event_type/event_level/source_module/payload)
            try:
                c.execute(
                    """INSERT INTO system_events
                         (event_type, event_level, source_module, entity_type, entity_id, payload, created_at)
                       VALUES ('circuit_breaker_transition', ?, 'circuit_breaker',
                               'breaker', ?, ?, datetime('now','localtime'))""",
                    (
                        "warning" if new == "open" else "info",
                        name,
                        json.dumps({"breaker": name, "old": old, "new": new, "reason": reason},
                                    ensure_ascii=False),
                    ),
                )
            except sqlite3.OperationalError:
                pass
            c.commit()
    except Exception:
        pass   # 日志是 best-effort
