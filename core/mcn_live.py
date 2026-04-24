# -*- coding: utf-8 -*-
"""MCN MySQL 实时查询层 (2026-04-21).

和 scripts/sync_mcn_full.py 的区别:
  sync_mcn_full     = 每日 04:00 批量同步 (几张全表), 慢但完整
  mcn_live (此文件) = 按需单条 / 小批量查, 快, 用于 Dashboard / Agent 临时取最新值

设计:
  - 进程内 singleton pymysql 连接 (避免每次新建)
  - 连接健康检查 + 自动重连
  - 读取本地 app_config 覆盖环境变量
  - 纯读库, 不写 MCN (保证安全)

典型用法:
    from core.mcn_live import fetch_member_live, fetch_members_bulk
    m = fetch_member_live(numeric_uid=887329560)
    # → {member_id, nickname, org_id, total_amount, org_task_num, ...}

    bulk = fetch_members_bulk([887329560, 2250138346, 2355714650])
    # → {887329560: {...}, 2250138346: {...}, ...}
"""
from __future__ import annotations

import logging
import os
import threading
import time
from typing import Any

log = logging.getLogger(__name__)

_lock = threading.Lock()
_conn = None  # type: ignore
_conn_created_at = 0.0

# 连接复用 TTL (秒). 超过这个时间重建, 防止 server 主动断
_CONN_TTL = 300


# ---------------------------------------------------------------------------
# Config (优先读环境变量, 同 sync_mcn_full.py)
# ---------------------------------------------------------------------------

def _mcn_mysql_config() -> dict:
    # ★ 2026-04-24 v6 Day 6: 迁到 core/secrets.py (优先 env → .secrets.json → fallback)
    try:
        from core.secrets import get
        return {
            "host": get("KS_MCN_MYSQL_HOST"),
            "port": int(get("KS_MCN_MYSQL_PORT", "3306")),
            "user": get("KS_MCN_MYSQL_USER"),
            "password": get("KS_MCN_MYSQL_PASSWORD"),
            "db": get("KS_MCN_MYSQL_DB"),
            "charset": "utf8mb4",
            "connect_timeout": 10,
            "read_timeout": 30,
        }
    except Exception:
        # fallback (老路径)
        return {
            "host": os.environ.get("MCN_MYSQL_HOST", "im.zhongxiangbao.com"),
            "port": int(os.environ.get("MCN_MYSQL_PORT", "3306")),
            "user": os.environ.get("MCN_MYSQL_USER", "shortju"),
            "password": os.environ.get("MCN_MYSQL_PASSWORD", "REPLACE_WITH_MCN_MYSQL_PASSWORD"),
            "db": os.environ.get("MCN_MYSQL_DB", "shortju"),
            "charset": "utf8mb4",
            "connect_timeout": 10,
            "read_timeout": 30,
        }


# ---------------------------------------------------------------------------
# Connection singleton
# ---------------------------------------------------------------------------

def _get_conn():
    global _conn, _conn_created_at
    import pymysql

    with _lock:
        age = time.time() - _conn_created_at
        if _conn is None or age > _CONN_TTL:
            try:
                if _conn is not None:
                    try: _conn.close()
                    except: pass
            finally:
                _conn = pymysql.connect(**_mcn_mysql_config())
                _conn_created_at = time.time()
                log.debug("[mcn_live] new connection")
            return _conn
        # 健康检查
        try:
            _conn.ping(reconnect=True)
        except Exception:
            _conn = pymysql.connect(**_mcn_mysql_config())
            _conn_created_at = time.time()
        return _conn


def close_conn():
    """手动关掉 singleton (方便测试)."""
    global _conn, _conn_created_at
    with _lock:
        if _conn is not None:
            try: _conn.close()
            except: pass
            _conn = None
            _conn_created_at = 0.0


def is_online(timeout: float = 3.0) -> bool:
    """ping MCN MySQL — Dashboard "实时" 按钮亮灰判依据."""
    import pymysql
    try:
        cfg = _mcn_mysql_config()
        cfg["connect_timeout"] = max(1, int(timeout))
        c = pymysql.connect(**cfg)
        c.close()
        return True
    except Exception as e:
        log.warning("[mcn_live] offline: %s", e)
        return False


# ---------------------------------------------------------------------------
# Member queries (萤光计划主账号身份)
# ---------------------------------------------------------------------------

def fetch_member_live(numeric_uid: int | str) -> dict[str, Any] | None:
    """查单账号最新 MCN 记录 — 权威真昵称 / org / 总收益.

    返回 dict 或 None (账号不在 MCN).
    """
    try:
        uid = int(numeric_uid)
    except (TypeError, ValueError):
        return None
    conn = _get_conn()
    with conn.cursor() as cur:
        cur.execute("""
            SELECT member_id, member_name, org_id, fans_count,
                   total_amount, org_task_num, broker_name,
                   created_at, updated_at
            FROM fluorescent_members
            WHERE member_id=%s
            LIMIT 1
        """, (uid,))
        row = cur.fetchone()
    if not row:
        return None
    conn.commit()
    return {
        "member_id": row[0],
        "nickname": row[1],   # alias kept for backward compat
        "member_name": row[1],
        "org_id": row[2],
        "fans_count": row[3],
        "total_amount": float(row[4]) if row[4] is not None else 0.0,
        "org_task_num": row[5],
        "broker_name": row[6] or "",
        "created_at": str(row[7]) if row[7] else "",
        "updated_at": str(row[8]) if row[8] else "",
    }


def fetch_members_bulk(numeric_uids: list[int | str]) -> dict[int, dict[str, Any]]:
    """批量查 — 一次 SQL 拿 N 个账号. 用于 Dashboard 列表页."""
    uids: list[int] = []
    for u in numeric_uids:
        try: uids.append(int(u))
        except: pass
    if not uids:
        return {}

    conn = _get_conn()
    placeholders = ",".join(["%s"] * len(uids))
    sql = f"""
        SELECT member_id, member_name, org_id, fans_count,
               total_amount, org_task_num, broker_name,
               created_at, updated_at
        FROM fluorescent_members
        WHERE member_id IN ({placeholders})
    """
    with conn.cursor() as cur:
        cur.execute(sql, uids)
        rows = cur.fetchall()
    conn.commit()

    out: dict[int, dict[str, Any]] = {}
    for r in rows:
        out[int(r[0])] = {
            "member_id": r[0],
            "nickname": r[1],      # alias kept for backward compat
            "member_name": r[1],
            "org_id": r[2],
            "fans_count": r[3],
            "total_amount": float(r[4]) if r[4] is not None else 0.0,
            "org_task_num": r[5],
            "broker_name": r[6] or "",
            "created_at": str(r[7]) if r[7] else "",
            "updated_at": str(r[8]) if r[8] else "",
        }
    return out


# ---------------------------------------------------------------------------
# Income queries (实时收益)
# ---------------------------------------------------------------------------

def fetch_member_income_summary(
    numeric_uid: int | str,
    days: int = 7,
) -> dict[str, Any]:
    """查账号近 N 天 fluorescent_income 汇总 — 比本地 snapshot 更实时."""
    try:
        uid = int(numeric_uid)
    except (TypeError, ValueError):
        return {}
    conn = _get_conn()
    with conn.cursor() as cur:
        cur.execute("""
            SELECT COUNT(*) AS tasks,
                   COALESCE(SUM(income), 0) AS total_income,
                   COUNT(DISTINCT task_id) AS unique_tasks,
                   MAX(updated_at) AS last_ts
            FROM fluorescent_income
            WHERE member_id=%s
              AND updated_at >= DATE_SUB(NOW(), INTERVAL %s DAY)
        """, (uid, int(days)))
        row = cur.fetchone()
    conn.commit()
    if not row:
        return {}
    return {
        "member_id": uid,
        "window_days": days,
        "task_events": int(row[0] or 0),
        "total_income": float(row[1] or 0.0),
        "unique_tasks": int(row[2] or 0),
        "last_event_at": str(row[3]) if row[3] else "",
    }


# ---------------------------------------------------------------------------
# Org queries (机构级别)
# ---------------------------------------------------------------------------

def fetch_org_summary(org_id: int = 10) -> dict[str, Any]:
    """查机构 (默认 org=10 火视界短剧) 总体数据."""
    conn = _get_conn()
    with conn.cursor() as cur:
        cur.execute("""
            SELECT COUNT(*) AS member_count,
                   COALESCE(SUM(total_amount), 0) AS total_income,
                   COALESCE(SUM(org_task_num), 0) AS total_tasks,
                   COUNT(CASE WHEN org_task_num > 0 THEN 1 END) AS active_members
            FROM fluorescent_members
            WHERE org_id=%s
        """, (int(org_id),))
        row = cur.fetchone()
    conn.commit()
    if not row:
        return {}
    return {
        "org_id": org_id,
        "member_count": int(row[0] or 0),
        "total_income": float(row[1] or 0.0),
        "total_tasks": int(row[2] or 0),
        "active_members": int(row[3] or 0),
    }


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import argparse, json, sys
    sys.stdout.reconfigure(encoding="utf-8")
    logging.basicConfig(level=logging.INFO, format="[%(asctime)s] %(message)s")

    ap = argparse.ArgumentParser(description="MCN live query utility")
    ap.add_argument("--uid", type=int, help="numeric_uid 单账号查询")
    ap.add_argument("--uids", type=str, help="逗号分隔批量查询")
    ap.add_argument("--income", action="store_true", help="附带收益汇总")
    ap.add_argument("--org", type=int, help="机构汇总 (默认 10)")
    ap.add_argument("--ping", action="store_true", help="测试 MCN 在线")
    args = ap.parse_args()

    if args.ping:
        print(json.dumps({"online": is_online()}, indent=2))
    elif args.uid:
        m = fetch_member_live(args.uid)
        print(json.dumps(m, ensure_ascii=False, indent=2, default=str))
        if args.income:
            inc = fetch_member_income_summary(args.uid, days=7)
            print(json.dumps(inc, ensure_ascii=False, indent=2))
    elif args.uids:
        uids = [int(u.strip()) for u in args.uids.split(",") if u.strip()]
        bulk = fetch_members_bulk(uids)
        print(json.dumps(bulk, ensure_ascii=False, indent=2, default=str))
    elif args.org is not None:
        print(json.dumps(fetch_org_summary(args.org), ensure_ascii=False, indent=2))
    else:
        ap.print_help()
