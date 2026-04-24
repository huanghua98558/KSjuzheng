# -*- coding: utf-8 -*-
"""配置中心 — system_config 表的 CRUD 封装 + 类型转换 + 审计.

用法:
    from core.config_center import cfg

    val = cfg.get('rule', 'daily_publish_limit', default=10)
    cfg.set('rule', 'daily_publish_limit', 15, updated_by='dashboard')

    # 批量读一个分类
    all_llm = cfg.get_category('llm')

所有 write 操作自动写 system_events (event_type=config_changed).
"""
from __future__ import annotations

import json
import sqlite3
from typing import Any, Optional

from core.config import DB_PATH


def _open() -> sqlite3.Connection:
    c = sqlite3.connect(DB_PATH)
    c.row_factory = sqlite3.Row
    return c


# ---------------------------------------------------------------------------
# 类型解析 / 序列化
# ---------------------------------------------------------------------------

def _parse(raw: str, typ: str) -> Any:
    if raw is None:
        return None
    try:
        if typ == "int":
            return int(raw)
        if typ == "float":
            return float(raw)
        if typ == "bool":
            return raw.strip().lower() in ("true", "1", "yes", "on")
        if typ in ("list", "dict"):
            return json.loads(raw or "null")
        return raw   # str
    except Exception:
        return raw


def _serialize(value: Any, typ: str) -> str:
    if typ == "bool":
        return "true" if bool(value) else "false"
    if typ in ("list", "dict"):
        return json.dumps(value, ensure_ascii=False)
    return str(value)


# ---------------------------------------------------------------------------
# ConfigCenter
# ---------------------------------------------------------------------------

class ConfigCenter:
    """单例式配置读写接口.

    get() 首次调用会做一次 lazy cache (30s TTL), 避免每次读都去查库.
    set() 会清除 cache.
    """

    _instance: Optional["ConfigCenter"] = None
    _cache: dict[str, Any] = {}
    _cache_ts: float = 0.0
    _CACHE_TTL = 30.0

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    # ------------------------------------------------------------------
    # 读
    # ------------------------------------------------------------------

    def _load_all(self) -> dict[str, Any]:
        import time
        if self._cache and (time.time() - self._cache_ts) < self._CACHE_TTL:
            return self._cache
        try:
            conn = _open()
            rows = conn.execute(
                """SELECT category, config_key, config_value, value_type
                   FROM system_config"""
            ).fetchall()
            conn.close()
        except Exception:
            return {}
        result: dict[str, Any] = {}
        for r in rows:
            result[f"{r['category']}.{r['config_key']}"] = _parse(
                r["config_value"], r["value_type"])
        self._cache = result
        self._cache_ts = time.time()
        return result

    def get(self, category: str, key: str, default: Any = None) -> Any:
        """单个配置值. 找不到返回 default."""
        return self._load_all().get(f"{category}.{key}", default)

    def get_category(self, category: str) -> list[dict]:
        """某分类下全部配置 (含元数据, 用于前端展示)."""
        try:
            conn = _open()
            rows = conn.execute(
                """SELECT id, category, config_key, config_value, value_type,
                          description, is_readonly, is_sensitive,
                          updated_by, updated_at, created_at
                   FROM system_config
                   WHERE category = ?
                   ORDER BY id""",
                (category,),
            ).fetchall()
            conn.close()
        except Exception:
            return []
        out = []
        for r in rows:
            d = dict(r)
            d["value"] = _parse(d["config_value"], d["value_type"])
            if d["is_sensitive"]:
                # 敏感数据只显示前 4 位 + 星号
                raw = d["config_value"] or ""
                d["value"] = (raw[:4] + "****" + raw[-4:]) if len(raw) > 8 else "****"
                d["config_value"] = d["value"]
            out.append(d)
        return out

    def list_all(self) -> dict[str, list[dict]]:
        """全部分类 → 列表映射."""
        try:
            conn = _open()
            cats = [r[0] for r in conn.execute(
                "SELECT DISTINCT category FROM system_config ORDER BY category"
            ).fetchall()]
            conn.close()
        except Exception:
            return {}
        return {cat: self.get_category(cat) for cat in cats}

    # ------------------------------------------------------------------
    # 写
    # ------------------------------------------------------------------

    def set(self, category: str, key: str, value: Any, *,
            updated_by: str = "system") -> dict:
        conn = _open()
        existing = conn.execute(
            """SELECT id, config_value, value_type, is_readonly
               FROM system_config
               WHERE category=? AND config_key=?""",
            (category, key),
        ).fetchone()
        if existing is None:
            conn.close()
            return {"ok": False, "error": "key_not_found",
                    "message": f"{category}.{key} 不存在"}
        if existing["is_readonly"]:
            conn.close()
            return {"ok": False, "error": "readonly",
                    "message": f"{category}.{key} 是只读配置"}

        typ = existing["value_type"]
        try:
            new_value = _serialize(value, typ)
        except Exception as e:
            conn.close()
            return {"ok": False, "error": "serialize_failed",
                    "message": str(e)}

        old_value = existing["config_value"]
        conn.execute(
            """UPDATE system_config SET
                 config_value=?, updated_by=?,
                 updated_at=datetime('now','localtime')
               WHERE id=?""",
            (new_value, updated_by, existing["id"]),
        )
        # 审计
        try:
            conn.execute(
                """INSERT INTO system_events
                     (event_type, event_level, source_module,
                      entity_type, entity_id, payload, created_at)
                   VALUES ('config_changed', 'info', 'config_center',
                           'system_config', ?, ?, datetime('now','localtime'))""",
                (f"{category}.{key}",
                 json.dumps({"category": category, "key": key,
                             "old": old_value, "new": new_value,
                             "updated_by": updated_by}, ensure_ascii=False)),
            )
        except Exception:
            pass
        conn.commit()
        conn.close()

        # 清缓存
        self._cache = {}
        return {"ok": True, "category": category, "key": key,
                "old_value": _parse(old_value, typ),
                "new_value": _parse(new_value, typ)}

    def bulk_set(self, items: list[dict], *,
                 updated_by: str = "dashboard") -> dict:
        """items = [{category, key, value}]"""
        ok_count = 0
        errors = []
        for item in items:
            r = self.set(item["category"], item["key"], item["value"],
                         updated_by=updated_by)
            if r.get("ok"):
                ok_count += 1
            else:
                errors.append({"item": item, "error": r.get("message")})
        return {"ok_count": ok_count, "total": len(items), "errors": errors}

    def reset_to_default(self, category: str, key: str) -> dict:
        """从 migrate_v10 的 SEED 读初始值重置."""
        try:
            from scripts.migrate_v10 import SEED
        except ImportError:
            return {"ok": False, "error": "SEED not importable"}
        for cat, k, val, typ, desc, readonly in SEED:
            if cat == category and k == key:
                return self.set(cat, k, val, updated_by="reset")
        return {"ok": False, "error": "not in SEED"}

    # ------------------------------------------------------------------
    # 最近改动 (审计)
    # ------------------------------------------------------------------

    def recent_changes(self, limit: int = 50) -> list[dict]:
        try:
            conn = _open()
            rows = conn.execute(
                """SELECT id, entity_id, payload, created_at
                   FROM system_events
                   WHERE event_type='config_changed'
                   ORDER BY id DESC LIMIT ?""",
                (limit,),
            ).fetchall()
            conn.close()
        except Exception:
            return []
        out = []
        for r in rows:
            try:
                p = json.loads(r["payload"] or "{}")
            except Exception:
                p = {}
            out.append({
                "id": r["id"],
                "config_key": r["entity_id"],
                "category": p.get("category"),
                "key": p.get("key"),
                "old": p.get("old"),
                "new": p.get("new"),
                "updated_by": p.get("updated_by"),
                "created_at": r["created_at"],
            })
        return out


# 全局单例
cfg = ConfigCenter()
