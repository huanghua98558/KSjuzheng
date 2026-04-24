# -*- coding: utf-8 -*-
"""统一配置读取层.

所有模块 (sync / selector / downloader / processor / executor) 都从这里读.
底层是 SQLite `app_config` 表 (见 migrate_v18.py).

设计原则:
  1. 读操作**带 1 秒 TTL cache** — 避免同一 worker 高频读 SQLite 死锁.
  2. 类型转换: 按 app_config_meta.value_type 自动转 int/bool/json.
  3. 写操作: 更新 value + updated_at, 广播 invalidate cache.
  4. 提供 `ConfigGroup` helper, 一次拿一组相关配置 (e.g. selector.*).
"""
from __future__ import annotations

import json
import logging
import sqlite3
import threading
import time
from typing import Any

log = logging.getLogger(__name__)


class AppConfig:
    """SQLite-backed config store with short TTL cache."""

    _instance: "AppConfig | None" = None
    _lock = threading.Lock()

    def __new__(cls, *args, **kwargs):
        # singleton
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
        return cls._instance

    def __init__(self, db_path: str | None = None, ttl_sec: float = 1.0,
                  meta_ttl_sec: float = 60.0):
        if getattr(self, "_inited", False):
            return
        from core.config import DB_PATH
        self.db_path = db_path or DB_PATH
        self.ttl_sec = ttl_sec
        # ★ 2026-04-22 §28_A: meta_cache 必须带 TTL, 否则 autopilot 长运行时 config 改了无法实时生效.
        # 今日 bug: 早上改 ai.scheduler.batch_interval_hours=0.1 但 autopilot 用老 vt=int
        # 导致 get() 返 str '0.1', str*3600 变字符串重复, 条件永不成立.
        self.meta_ttl_sec = meta_ttl_sec
        self._cache: dict[str, tuple[float, Any]] = {}  # key -> (ts, value)
        self._meta_cache: dict[str, dict] | None = None
        self._meta_loaded_at: float = 0.0
        self._inited = True

    def _connect(self) -> sqlite3.Connection:
        c = sqlite3.connect(self.db_path, timeout=10, check_same_thread=False)
        c.execute("PRAGMA busy_timeout=10000")
        return c

    def _load_meta(self) -> dict[str, dict]:
        """Load app_config_meta (key -> {value_type, default, comment}).

        ★ 2026-04-22 §28_A: 加 60s TTL, 支持 live config 生效.
        Meta 不频繁变 (一般 migration 级), 60s 足够.
        手动强刷可调 invalidate().
        """
        now = time.time()
        if self._meta_cache is not None and (now - self._meta_loaded_at) < self.meta_ttl_sec:
            return self._meta_cache
        out: dict[str, dict] = {}
        try:
            with self._connect() as c:
                rows = c.execute(
                    "SELECT config_key, value_type, default_value, comment FROM app_config_meta"
                ).fetchall()
                for k, vt, dv, cm in rows:
                    out[k] = {"value_type": vt, "default": dv, "comment": cm}
        except sqlite3.OperationalError:
            pass  # meta 表不存在, fall back 到字符串
        self._meta_cache = out
        self._meta_loaded_at = now
        return out

    def _coerce(self, key: str, raw: str | None) -> Any:
        """Convert raw str -> typed value per meta.value_type.

        ★ 2026-04-20 bug fix: 当 meta 缺失时 (未知 vt=str), 额外检测
        常见原语 'true/false' 返回 bool, 'null' 返回 None,
        否则返回 raw str. 避免 `bool('false')=True` 的 Python 陷阱.
        """
        if raw is None:
            return None
        meta = self._load_meta().get(key, {})
        vt = meta.get("value_type", "str")
        try:
            if vt == "int":
                return int(raw)
            if vt == "float":
                return float(raw)
            if vt == "bool":
                return raw.lower() in ("true", "1", "yes", "on")
            if vt == "json":
                return json.loads(raw)
            # str 或未知 — fallback 自动识别 bool/null 字面量
            lr = raw.strip().lower()
            if lr in ("true", "false"):
                return lr == "true"
            if lr == "null":
                return None
            return raw
        except (ValueError, json.JSONDecodeError) as e:
            log.warning("[AppConfig] coerce %s (vt=%s): %s — raw=%r", key, vt, e, raw)
            return raw

    def get(self, key: str, default: Any = None) -> Any:
        """读单个配置项."""
        now = time.time()
        cached = self._cache.get(key)
        if cached and (now - cached[0]) < self.ttl_sec:
            return cached[1]

        try:
            with self._connect() as c:
                row = c.execute(
                    "SELECT config_value FROM app_config WHERE config_key=?",
                    (key,),
                ).fetchone()
        except sqlite3.OperationalError as e:
            log.warning("[AppConfig] get %s failed: %s", key, e)
            return default

        if not row:
            # fall back 到 meta default — 只缓存有 meta 的 (避免不同 default 参数污染 cache)
            meta_default = self._load_meta().get(key, {}).get("default")
            if meta_default is not None:
                value = self._coerce(key, meta_default)
                self._cache[key] = (now, value)
                return value
            # 纯不存在的 key, 不缓存, 每次调用都返回当前传入的 default
            return default

        value = self._coerce(key, row[0])
        self._cache[key] = (now, value)
        return value

    def set(self, key: str, value: Any) -> None:
        """写单个配置项. 自动转 str 存, 清 cache."""
        if isinstance(value, bool):
            raw = "true" if value else "false"
        elif isinstance(value, (dict, list)):
            raw = json.dumps(value, ensure_ascii=False)
        else:
            raw = str(value)

        with self._connect() as c:
            c.execute(
                """INSERT INTO app_config (config_key, config_value, updated_at)
                   VALUES (?, ?, datetime('now','localtime'))
                   ON CONFLICT(config_key) DO UPDATE SET
                     config_value=excluded.config_value,
                     updated_at=datetime('now','localtime')""",
                (key, raw),
            )
            c.commit()
        self._cache.pop(key, None)
        log.info("[AppConfig] set %s = %r", key, value)

    def get_group(self, prefix: str) -> dict[str, Any]:
        """读所有以 prefix 开头的配置, 返回去除前缀的 dict."""
        with self._connect() as c:
            rows = c.execute(
                "SELECT config_key, config_value FROM app_config WHERE config_key LIKE ?",
                (prefix + "%",),
            ).fetchall()
        return {
            k[len(prefix):]: self._coerce(k, v)
            for k, v in rows
        }

    def invalidate(self) -> None:
        """手动清 cache — dashboard 改完值之后调."""
        self._cache.clear()
        self._meta_cache = None
        self._meta_loaded_at = 0.0

    def all(self) -> dict[str, Any]:
        """拉全部配置."""
        with self._connect() as c:
            rows = c.execute(
                "SELECT config_key, config_value FROM app_config ORDER BY config_key"
            ).fetchall()
        return {k: self._coerce(k, v) for k, v in rows}


# 模块级便捷函数
_cfg: AppConfig | None = None


def cfg() -> AppConfig:
    global _cfg
    if _cfg is None:
        _cfg = AppConfig()
    return _cfg


def get(key: str, default: Any = None) -> Any:
    return cfg().get(key, default)


def set_(key: str, value: Any) -> None:
    cfg().set(key, value)


def get_group(prefix: str) -> dict[str, Any]:
    return cfg().get_group(prefix)
