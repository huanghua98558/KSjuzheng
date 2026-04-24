# -*- coding: utf-8 -*-
"""Account × Drama Blacklist — 80004 业务闭环.

★ 2026-04-24 v6 Week 2 Day 7 核心模块.

背景:
  快手 result=80004 "无作者变现权限" 是业务级拒, 不是协议问题.
  同 (account_id, drama_name) 组合在快手开通萤光作者变现前, 任何重试都
  必拒. 老 watchdog 在 3 次 80004 后冻 account 30 天 — 过激, 可能账号
  签了但**只对某些剧**没变现权限.

  本模块提供 fine-grained cooldown: (account × drama) 72h 冷却,
  planner match_scorer 读这个表直接 skip, 不冻账号.

★ 核心 API:
  add_to_blacklist(account_id, drama_name, reason, cooldown_h=72)
    幂等 upsert. 同组合多次 → 累加 block_count + 刷 last_blocked_at.

  is_blocked(account_id, drama_name) -> (bool, meta)
    O(1) 查询 (索引 UNIQUE). 过期自动返回 False (无需人工清).

  cleanup_expired() -> int
    DELETE WHERE expires_at < now. ControllerAgent 每 1h 调.

  list_active(account_id=None, drama_name=None) -> list[dict]
    Dashboard + CLI 审计用.

  remove(account_id, drama_name) -> bool
    人工解封 (dashboard 按钮).

★ 消费方:
  1. core/publisher.py::publish_video — submit result 80004 → add_to_blacklist(reason='auth_80004')
  2. core/match_scorer.py::_account_drama_penalty — 查询命中 → -999
  3. core/agents/controller_agent.py step 25b — cleanup_expired() 每 1h
  4. dashboard/streamlit_app.py 🔌 熔断监控 页 — list_active

★ 数据示例:
  account_id=5, drama_name='这个保镖是武神', reason='auth_80004',
  first_blocked_at='2026-04-23 16:12', expires_at='2026-04-26 16:12',
  block_count=3
"""
from __future__ import annotations

import json
import logging
import sqlite3
import sys
import time
from typing import Optional

log = logging.getLogger(__name__)


def _connect():
    from core.config import DB_PATH
    c = sqlite3.connect(DB_PATH, timeout=30)
    c.execute("PRAGMA busy_timeout=30000")
    c.execute("PRAGMA journal_mode=WAL")
    c.execute("PRAGMA synchronous=NORMAL")
    c.row_factory = sqlite3.Row
    return c


def _cfg(key: str, default):
    try:
        from core.app_config import get as _g
        return _g(key, default)
    except Exception:
        return default


# ──────────────────────────────────────────────────────────────────────
# 公共 API
# ──────────────────────────────────────────────────────────────────────
def add_to_blacklist(
    account_id: int | str,
    drama_name: str,
    reason: str = "auth_80004",
    source: str = "publisher",
    cooldown_hours: int | None = None,
    metadata: dict | None = None,
) -> dict:
    """加入 blacklist (幂等 upsert).

    Args:
        account_id: device_accounts.id (int)
        drama_name: 剧名
        reason: 'auth_80004' / 'repeat_fail_3' / 'manual' / 其他
        source: 'publisher' / 'watchdog' / 'dashboard' / 'cli'
        cooldown_hours: None → 按 reason 自动选
                         auth_80004 → 72h (config: cooldown_hours)
                         repeat_fail → 12h (config: repeat_fail_cooldown_hours)
        metadata: 任意附加 json (写 metadata_json 字段)

    Returns:
        {'action': 'inserted' | 'updated', 'block_count': N, 'expires_at': ...}
    """
    if not _cfg("ai.blacklist.account_drama.enabled", True):
        return {"action": "disabled"}

    try:
        aid = int(account_id)
    except (ValueError, TypeError):
        log.warning("[adb] invalid account_id: %r", account_id)
        return {"action": "invalid_account_id"}

    if not drama_name or not reason:
        return {"action": "invalid_args"}

    # 冷却时长
    if cooldown_hours is None:
        if reason.startswith("auth_80004"):
            cooldown_hours = int(_cfg("ai.blacklist.account_drama.cooldown_hours", 72))
        elif reason.startswith("repeat_fail"):
            cooldown_hours = int(_cfg("ai.blacklist.account_drama.repeat_fail_cooldown_hours", 12))
        else:
            cooldown_hours = int(_cfg("ai.blacklist.account_drama.cooldown_hours", 72))

    meta_json = json.dumps(metadata or {}, ensure_ascii=False)

    with _connect() as c:
        # 先查是否已有
        row = c.execute(
            """SELECT id, block_count FROM account_drama_blacklist
               WHERE account_id=? AND drama_name=?""",
            (aid, drama_name),
        ).fetchone()

        if row:
            # upsert: 刷 last + 累加 count + 延长 expires
            new_count = (row["block_count"] or 0) + 1
            c.execute(
                f"""UPDATE account_drama_blacklist SET
                      last_blocked_at = datetime('now','localtime'),
                      block_count     = ?,
                      expires_at      = datetime('now', '+{cooldown_hours} hours', 'localtime'),
                      reason          = ?,
                      source          = ?,
                      metadata_json   = ?
                    WHERE id=?""",
                (new_count, reason, source, meta_json, row["id"]),
            )
            c.commit()
            log.info("[adb] updated: acct=%d drama=%s reason=%s count=%d cd=%dh",
                      aid, drama_name, reason, new_count, cooldown_hours)
            return {
                "action": "updated", "block_count": new_count,
                "cooldown_hours": cooldown_hours,
            }
        else:
            c.execute(
                f"""INSERT INTO account_drama_blacklist
                      (account_id, drama_name, reason, source,
                       first_blocked_at, last_blocked_at,
                       block_count, expires_at, metadata_json)
                    VALUES (?, ?, ?, ?,
                            datetime('now','localtime'),
                            datetime('now','localtime'),
                            1,
                            datetime('now', '+{cooldown_hours} hours', 'localtime'),
                            ?)""",
                (aid, drama_name, reason, source, meta_json),
            )
            c.commit()
            log.info("[adb] inserted: acct=%d drama=%s reason=%s cd=%dh",
                      aid, drama_name, reason, cooldown_hours)
            return {
                "action": "inserted", "block_count": 1,
                "cooldown_hours": cooldown_hours,
            }


def is_blocked(account_id: int | str, drama_name: str) -> tuple[bool, dict]:
    """检查 (account, drama) 当前是否 blocked.

    Returns:
        (bool, meta_dict). blocked=False 时 meta={}.
    """
    if not _cfg("ai.blacklist.account_drama.enabled", True):
        return (False, {})

    try:
        aid = int(account_id)
    except (ValueError, TypeError):
        return (False, {})

    with _connect() as c:
        row = c.execute(
            """SELECT reason, block_count, first_blocked_at, last_blocked_at,
                      expires_at, source,
                      CASE WHEN expires_at > datetime('now','localtime')
                           THEN 1 ELSE 0 END AS active
               FROM account_drama_blacklist
               WHERE account_id=? AND drama_name=?""",
            (aid, drama_name),
        ).fetchone()
    if not row:
        return (False, {})
    if not row["active"]:
        return (False, dict(row))  # 过期 (meta 仍返, 用于审计)
    return (True, dict(row))


def cleanup_expired() -> int:
    """DELETE 过期条目. 返删了多少行.

    ControllerAgent step 25b 每 1h 调. 也可 CLI 手工跑.
    """
    with _connect() as c:
        cur = c.execute(
            """DELETE FROM account_drama_blacklist
               WHERE expires_at <= datetime('now','localtime')"""
        )
        n = cur.rowcount or 0
        c.commit()
    if n > 0:
        log.info("[adb] cleanup: deleted %d expired entries", n)
    return n


def list_active(account_id: int | None = None,
                  drama_name: str | None = None,
                  limit: int = 100) -> list[dict]:
    """查当前 active (未过期) 条目."""
    sql = [
        """SELECT id, account_id, drama_name, reason, source,
                  first_blocked_at, last_blocked_at, block_count, expires_at,
                  metadata_json
           FROM account_drama_blacklist
           WHERE expires_at > datetime('now','localtime')"""
    ]
    args = []
    if account_id is not None:
        sql.append(" AND account_id=?"); args.append(int(account_id))
    if drama_name:
        sql.append(" AND drama_name=?"); args.append(drama_name)
    sql.append(" ORDER BY last_blocked_at DESC LIMIT ?")
    args.append(limit)

    with _connect() as c:
        rows = c.execute("".join(sql), args).fetchall()
    return [dict(r) for r in rows]


def stats() -> dict:
    """全局统计 (dashboard 用)."""
    with _connect() as c:
        total = c.execute("SELECT COUNT(*) FROM account_drama_blacklist").fetchone()[0]
        active = c.execute(
            """SELECT COUNT(*) FROM account_drama_blacklist
               WHERE expires_at > datetime('now','localtime')"""
        ).fetchone()[0]
        by_reason = dict(c.execute(
            """SELECT reason, COUNT(*) FROM account_drama_blacklist
               WHERE expires_at > datetime('now','localtime')
               GROUP BY reason"""
        ).fetchall())
        top_acct = [dict(r) for r in c.execute(
            """SELECT account_id, COUNT(*) n FROM account_drama_blacklist
               WHERE expires_at > datetime('now','localtime')
               GROUP BY account_id ORDER BY n DESC LIMIT 5"""
        ).fetchall()]
    return {
        "total": total, "active": active, "expired": total - active,
        "by_reason": by_reason, "top_accounts": top_acct,
    }


def remove(account_id: int | str, drama_name: str, reason: str = "manual") -> bool:
    """手工解封. True 若删成功."""
    try:
        aid = int(account_id)
    except (ValueError, TypeError):
        return False
    with _connect() as c:
        cur = c.execute(
            "DELETE FROM account_drama_blacklist WHERE account_id=? AND drama_name=?",
            (aid, drama_name),
        )
        n = cur.rowcount
        c.commit()
    if n:
        log.info("[adb] manually removed: acct=%d drama=%s reason=%s",
                  aid, drama_name, reason)
    return n > 0


# ──────────────────────────────────────────────────────────────────────
# CLI
# ──────────────────────────────────────────────────────────────────────
def main():
    import argparse
    try: sys.stdout.reconfigure(encoding="utf-8")
    except Exception: pass

    ap = argparse.ArgumentParser(description="account_drama_blacklist CLI")
    ap.add_argument("action", choices=["stats", "list", "add", "check",
                                         "cleanup", "remove"])
    ap.add_argument("--account-id", type=int)
    ap.add_argument("--drama", type=str)
    ap.add_argument("--reason", default="manual")
    ap.add_argument("--limit", type=int, default=20)
    args = ap.parse_args()

    if args.action == "stats":
        import json
        print(json.dumps(stats(), indent=2, ensure_ascii=False))

    elif args.action == "list":
        rows = list_active(args.account_id, args.drama, args.limit)
        print(f"Active: {len(rows)}")
        for r in rows:
            print(f"  acct={r['account_id']:<4} drama={r['drama_name']:<25} "
                  f"reason={r['reason']:<15} block#{r['block_count']:<2} "
                  f"expires={r['expires_at']}")

    elif args.action == "check":
        if not (args.account_id and args.drama):
            print("需要 --account-id 和 --drama"); return 1
        ok, meta = is_blocked(args.account_id, args.drama)
        print(f"blocked={ok}")
        if meta: print(f"meta: {meta}")

    elif args.action == "add":
        if not (args.account_id and args.drama):
            print("需要 --account-id 和 --drama"); return 1
        r = add_to_blacklist(args.account_id, args.drama,
                              reason=args.reason, source="cli")
        print(r)

    elif args.action == "cleanup":
        n = cleanup_expired()
        print(f"deleted {n} expired entries")

    elif args.action == "remove":
        if not (args.account_id and args.drama):
            print("需要 --account-id 和 --drama"); return 1
        r = remove(args.account_id, args.drama)
        print(f"removed: {r}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
