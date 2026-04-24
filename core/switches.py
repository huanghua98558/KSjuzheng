# -*- coding: utf-8 -*-
"""feature_switches — 6 层开关架构 (L1 采集 → L6 自动放大).

提供:
  - is_enabled(code)             读闸
  - require_enabled(code)        断言式读闸
  - set_switch(code, value)      单切
  - get_all()                    全部 (带 layer 元数据)
  - get_by_layer(layer)          单层
  - get_layered_tree()           分层树 (master 下挂 features)
  - bulk_set(codes, value)       批量切换
  - toggle_layer_master(layer)   一键翻转某层总闸
  - cascade_off(layer)           总闸 off 时子开关连动 off
  - recent_changes(limit)        开关改动日志 (来自 system_events)

约定:
  - master 总闸 OFF → 对应层全部 feature 视为 OFF (通过 is_enabled 级联判断)
  - set_switch 任何调用都会 INSERT system_events (event_type='switch_changed')
  - bulk_set 通过 dashboard_bulk_ops 审计表落表
"""
from __future__ import annotations

import json
import sqlite3
from datetime import datetime
from typing import Any, Iterable

from core.config import DB_PATH


class SwitchDisabled(RuntimeError):
    """require_enabled() 失败时抛出."""


# ---------------------------------------------------------------------------
# Connection helper
# ---------------------------------------------------------------------------

def _open() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def _now() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _str_bool(value: bool | str) -> str:
    """Coerce anything truthy to 'true'/'false'."""
    if value is True:
        return "true"
    if value is False:
        return "false"
    return "true" if str(value).strip().lower() in (
        "true", "1", "yes", "on", "enabled"
    ) else "false"


# ---------------------------------------------------------------------------
# Read gate
# ---------------------------------------------------------------------------

def is_enabled_for_group(switch_code: str, group: str | None = None,
                         default: bool = True, cascade: bool = True) -> bool:
    """组感知版本: 如果有 switch_group_overrides 里该组的覆盖则用之."""
    if group:
        try:
            conn = _open()
            row = conn.execute(
                """SELECT override_value FROM switch_group_overrides
                   WHERE group_name=? AND switch_code=?""",
                (group, switch_code),
            ).fetchone()
            conn.close()
            if row:
                return (row["override_value"] or "").strip().lower() in (
                    "true", "1", "yes", "on", "enabled",
                )
        except Exception:
            pass
    return is_enabled(switch_code, default=default, cascade=cascade)


def get_group_overrides(group: str | None = None) -> list[dict]:
    """列出覆盖. group=None 返回全部."""
    try:
        conn = _open()
        if group:
            rows = conn.execute(
                """SELECT id, group_name, switch_code, override_value,
                          updated_by, updated_at
                   FROM switch_group_overrides WHERE group_name=?
                   ORDER BY switch_code""",
                (group,),
            ).fetchall()
        else:
            rows = conn.execute(
                """SELECT id, group_name, switch_code, override_value,
                          updated_by, updated_at
                   FROM switch_group_overrides ORDER BY group_name, switch_code"""
            ).fetchall()
        conn.close()
        return [dict(r) for r in rows]
    except Exception:
        return []


def set_group_override(group: str, switch_code: str, value: bool | str,
                       *, updated_by: str = "dashboard") -> dict:
    str_val = _str_bool(value)
    conn = _open()
    conn.execute(
        """INSERT INTO switch_group_overrides
             (group_name, switch_code, override_value, updated_by)
           VALUES (?, ?, ?, ?)
           ON CONFLICT(group_name, switch_code) DO UPDATE SET
             override_value=excluded.override_value,
             updated_by=excluded.updated_by,
             updated_at=datetime('now','localtime')""",
        (group, switch_code, str_val, updated_by),
    )
    conn.commit()
    conn.close()
    return {"ok": True, "group": group, "code": switch_code, "value": str_val}


def clear_group_override(group: str, switch_code: str) -> dict:
    conn = _open()
    cur = conn.execute(
        "DELETE FROM switch_group_overrides WHERE group_name=? AND switch_code=?",
        (group, switch_code),
    )
    conn.commit()
    conn.close()
    return {"ok": True, "removed": cur.rowcount}


def is_enabled(switch_code: str, default: bool = True,
               cascade: bool = True) -> bool:
    """Return True if switch is ON.

    cascade=True (默认): 如果该开关指向一个 parent_code, 先查 parent 是否 OFF,
        OFF 则无论子值如何都返回 False.  (总闸 kill-switch 语义.)
    """
    try:
        conn = _open()
        row = conn.execute(
            """SELECT switch_value, parent_code FROM feature_switches
               WHERE switch_code = ?""",
            (switch_code,),
        ).fetchone()
        if row is None:
            conn.close()
            return default
        own_on = (row["switch_value"] or "").strip().lower() in (
            "true", "1", "yes", "on", "enabled",
        )
        if cascade and row["parent_code"]:
            # Recurse — but non-cascade for parent itself (parent has its own parent_code)
            # actually easiest: just look up parent's raw value
            prow = conn.execute(
                "SELECT switch_value FROM feature_switches WHERE switch_code = ?",
                (row["parent_code"],),
            ).fetchone()
            if prow is not None:
                parent_on = (prow["switch_value"] or "").strip().lower() in (
                    "true", "1", "yes", "on", "enabled",
                )
                if not parent_on:
                    conn.close()
                    return False
        conn.close()
        return own_on
    except Exception:
        return default


def require_enabled(switch_code: str) -> None:
    if not is_enabled(switch_code):
        raise SwitchDisabled(f"feature switch '{switch_code}' is OFF")


# ---------------------------------------------------------------------------
# Queries
# ---------------------------------------------------------------------------

def get_all() -> list[dict[str, Any]]:
    conn = _open()
    rows = conn.execute(
        """SELECT switch_code, switch_name, switch_value, switch_scope,
                  description, updated_by, updated_at,
                  layer, layer_name, category, sort_order,
                  parent_code, risk_level
           FROM feature_switches
           ORDER BY layer, sort_order, switch_code"""
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_by_layer(layer: int) -> list[dict[str, Any]]:
    conn = _open()
    rows = conn.execute(
        """SELECT * FROM feature_switches WHERE layer = ?
           ORDER BY sort_order, switch_code""",
        (layer,),
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_layered_tree() -> list[dict[str, Any]]:
    """返回 6 层分层树.
    [
      { "layer": 1, "layer_name": "L1 采集",
        "master": {...}, "features": [...],
        "on_count": n, "off_count": m, "total": t },
      ...
    ]
    """
    all_rows = get_all()
    by_layer: dict[int, list[dict]] = {}
    for r in all_rows:
        lyr = r.get("layer") or 0
        if lyr == 0:
            continue
        by_layer.setdefault(lyr, []).append(r)

    tree = []
    for lyr in sorted(by_layer.keys()):
        rows = by_layer[lyr]
        master = next((r for r in rows if r.get("category") == "master"), None)
        features = [r for r in rows if r.get("category") != "master"]
        on_count = sum(1 for r in rows if r["switch_value"] == "true")
        off_count = sum(1 for r in rows if r["switch_value"] != "true")
        tree.append({
            "layer": lyr,
            "layer_name": rows[0].get("layer_name") or f"L{lyr}",
            "master": master,
            "features": features,
            "on_count": on_count,
            "off_count": off_count,
            "total": len(rows),
            "effective_on": bool(master and master["switch_value"] == "true"),
        })
    return tree


# ---------------------------------------------------------------------------
# Write — with audit logging
# ---------------------------------------------------------------------------

def _log_event(conn: sqlite3.Connection, switch_code: str,
               old_value: str, new_value: str, updated_by: str) -> None:
    try:
        conn.execute(
            """INSERT INTO system_events
                 (event_type, event_level, source_module, entity_type, entity_id,
                  payload, created_at)
               VALUES ('switch_changed', 'info', 'switches', 'feature_switch', ?,
                       ?, datetime('now','localtime'))""",
            (switch_code,
             json.dumps({"old": old_value, "new": new_value,
                         "updated_by": updated_by}, ensure_ascii=False)),
        )
    except Exception:
        pass  # system_events 可能临时不可用, 不阻塞


def set_switch(switch_code: str, value: bool | str, *,
               updated_by: str = "system") -> bool:
    """Flip a switch. Returns True if a row was updated/inserted."""
    str_val = _str_bool(value)
    conn = _open()
    existing = conn.execute(
        "SELECT switch_value FROM feature_switches WHERE switch_code = ?",
        (switch_code,),
    ).fetchone()
    old_val = existing["switch_value"] if existing else "(missing)"
    if existing:
        conn.execute(
            """UPDATE feature_switches SET
                 switch_value = ?, updated_by = ?,
                 updated_at = datetime('now','localtime')
               WHERE switch_code = ?""",
            (str_val, updated_by, switch_code),
        )
    else:
        conn.execute(
            """INSERT INTO feature_switches
                 (switch_code, switch_name, switch_scope, switch_value,
                  description, updated_by, layer, layer_name, category,
                  sort_order, parent_code, risk_level)
               VALUES (?, ?, 'global', ?, '(auto-created)', ?,
                       0, '', 'feature', 999, '', 'low')""",
            (switch_code, switch_code, str_val, updated_by),
        )
    _log_event(conn, switch_code, old_val, str_val, updated_by)
    conn.commit()
    conn.close()
    return True


def bulk_set(codes: Iterable[str], value: bool | str, *,
             updated_by: str = "dashboard",
             note: str = "") -> dict[str, Any]:
    """Batch toggle. Writes to dashboard_bulk_ops for audit."""
    codes = list(codes)
    str_val = _str_bool(value)
    conn = _open()
    affected = 0
    changed_codes = []
    for code in codes:
        existing = conn.execute(
            "SELECT switch_value FROM feature_switches WHERE switch_code=?",
            (code,),
        ).fetchone()
        if existing is None:
            continue
        old_val = existing["switch_value"]
        if old_val != str_val:
            conn.execute(
                """UPDATE feature_switches SET
                     switch_value=?, updated_by=?,
                     updated_at=datetime('now','localtime')
                   WHERE switch_code=?""",
                (str_val, updated_by, code),
            )
            _log_event(conn, code, old_val, str_val, updated_by)
            affected += 1
            changed_codes.append(code)
    conn.execute(
        """INSERT INTO dashboard_bulk_ops
             (op_code, target_type, target_ids_json, params_json,
              affected_count, operator, note)
           VALUES ('toggle_switches', 'switch', ?, ?, ?, ?, ?)""",
        (json.dumps(codes, ensure_ascii=False),
         json.dumps({"value": str_val}, ensure_ascii=False),
         affected, updated_by, note),
    )
    conn.commit()
    conn.close()
    return {"affected": affected, "changed": changed_codes, "total_asked": len(codes)}


def toggle_layer_master(layer: int, value: bool | str, *,
                        updated_by: str = "dashboard") -> dict[str, Any]:
    """一键翻转某层的 master 总闸."""
    conn = _open()
    master = conn.execute(
        """SELECT switch_code FROM feature_switches
           WHERE layer=? AND category='master' LIMIT 1""",
        (layer,),
    ).fetchone()
    conn.close()
    if not master:
        return {"affected": 0, "error": f"layer {layer} has no master switch"}
    set_switch(master["switch_code"], value, updated_by=updated_by)
    return {"affected": 1, "master_code": master["switch_code"],
            "new_value": _str_bool(value)}


def cascade_off(layer: int, *, updated_by: str = "dashboard") -> dict[str, Any]:
    """层级紧急关闭: 总闸 + 全部子项都 OFF."""
    conn = _open()
    codes = [r[0] for r in conn.execute(
        "SELECT switch_code FROM feature_switches WHERE layer=?",
        (layer,),
    ).fetchall()]
    conn.close()
    res = bulk_set(codes, False, updated_by=updated_by,
                   note=f"cascade_off layer={layer}")
    return res


def recent_changes(limit: int = 30) -> list[dict[str, Any]]:
    """开关最近改动."""
    conn = _open()
    rows = conn.execute(
        """SELECT id, entity_id AS switch_code, payload, created_at
           FROM system_events
           WHERE event_type='switch_changed'
           ORDER BY id DESC LIMIT ?""",
        (limit,),
    ).fetchall()
    out = []
    for r in rows:
        try:
            p = json.loads(r["payload"] or "{}")
        except Exception:
            p = {}
        out.append({
            "id": r["id"],
            "switch_code": r["switch_code"],
            "old": p.get("old"),
            "new": p.get("new"),
            "updated_by": p.get("updated_by"),
            "created_at": r["created_at"],
        })
    conn.close()
    return out
