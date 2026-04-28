"""Cookie 池.

数据源(优先级从高到低):
  1. 自家 CloudCookieAccount 表 (login_status='valid' + 七合一字段齐全)
  2. zhongxiangbao 公开池 (http://im.zhongxiangbao.com:8000/api/cloud-cookies)
     —— 过渡期使用,长期应建自己的 Chrome helper

策略:
  - 进程内 30s 缓存
  - 选 cookie: random.choice(健康池) — 简单分散负载
  - 失败上报: mark_expired(cookie_id, reason) → CloudCookieAccount.login_status='invalid'
  - 自动健康检查: scheduler 每 30 min 跑 visionProfile 探活
"""
from __future__ import annotations

import random
import re
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional

import httpx

from app.core.logging import logger


ZHONGXIANGBAO_URL = "http://im.zhongxiangbao.com:8000/api/cloud-cookies"
CACHE_TTL_S = 30
REQUIRED_FIELDS = (
    "userId=",
    "kuaishou.server.webday7_st=",
    "passToken=",
    "did=web_",
)


@dataclass
class CookieRecord:
    """池中单条 cookie 记录."""
    source: str             # "self" / "zhongxiangbao"
    source_id: int | str    # 在源系统的主键
    uid_short: str          # 快手 short uid (3xxxxx)
    uid_numeric: str        # 快手 numeric userId (从 cookie 提)
    nickname: str           # 昵称
    cookie: str             # 完整 cookie 字符串
    fail_count: int = 0     # 连续失败次数
    last_used_at: float = 0
    last_failed_at: float = 0
    is_invalid: bool = False  # 已被标记失效

    def is_healthy(self, fail_threshold: int = 3) -> bool:
        return not self.is_invalid and self.fail_count < fail_threshold


@dataclass
class _PoolState:
    records: list[CookieRecord] = field(default_factory=list)
    fetched_at: float = 0


_state = _PoolState()
_lock = threading.RLock()


def _has_required(cookie_str: str) -> bool:
    return all(f in cookie_str for f in REQUIRED_FIELDS)


def _extract_numeric(cookie_str: str) -> str | None:
    m = re.search(r"\buserId=(\d+)", cookie_str)
    return m.group(1) if m else None


def _fetch_zhongxiangbao() -> list[CookieRecord]:
    """从 zhongxiangbao 公开池拉所有 logged_in cookie."""
    try:
        with httpx.Client(timeout=10.0) as client:
            resp = client.get(ZHONGXIANGBAO_URL)
        resp.raise_for_status()
        data = resp.json()
        items = data if isinstance(data, list) else data.get("data") or []
    except Exception as ex:
        logger.warning(f"[ks.cookie_pool] zhongxiangbao 拉取失败: {ex}")
        return []

    rs: list[CookieRecord] = []
    for it in items:
        if it.get("login_status") != "logged_in":
            continue
        ck = it.get("cookies") or ""
        if not _has_required(ck):
            continue
        nuid = _extract_numeric(ck)
        if not nuid:
            continue
        rs.append(CookieRecord(
            source="zhongxiangbao",
            source_id=it.get("id"),
            uid_short=it.get("kuaishou_uid") or "",
            uid_numeric=nuid,
            nickname=it.get("account_name") or "",
            cookie=ck,
        ))
    return rs


# --- PATCHED v4 huoshijie schema ---
def _fetch_self_pool(db) -> list[CookieRecord]:
    """从 cloud_cookie_accounts 表拉(huoshijie 实际 schema, cookies 明文 longtext)。

    huoshijie 实际字段(实测):
      id, owner_code, device_serial, account_id (varchar), account_name,
      kuaishou_uid, kuaishou_name, cookies (明文 longtext),
      login_status, login_time, browser_port, success_count, fail_count,
      remark, created_at, updated_at

    没有 organization_id / assigned_user_id / cookie_ciphertext 等 ksjuzheng
    模型期望的字段,直接用原生 SQL 避开 ORM 不匹配。
    """
    if db is None:
        return []
    try:
        from sqlalchemy import text
    except Exception as ex:
        logger.warning(f"[ks.cookie_pool] self_pool import 失败: {ex}")
        return []

    rs: list[CookieRecord] = []
    try:
        result = db.execute(text(
            "SELECT id, owner_code, kuaishou_uid, kuaishou_name, cookies, login_status "
            "FROM cloud_cookie_accounts "
            "WHERE login_status = 'logged_in' "
            "ORDER BY login_time DESC LIMIT 5000"
        ))
        rows = result.fetchall()
    except Exception as ex:
        logger.error(f"[ks.cookie_pool] 查 cloud_cookie_accounts 失败: {ex}")
        return []

    ok_n = 0
    bad_format = 0
    for r in rows:
        cookie = r[4] or ""  # cookies 明文
        if not _has_required(cookie):
            bad_format += 1
            continue
        nuid = _extract_numeric(cookie)
        if not nuid:
            bad_format += 1
            continue
        ok_n += 1
        rs.append(CookieRecord(
            source="self",
            source_id=r[0],
            uid_short=r[2] or "",  # kuaishou_uid
            uid_numeric=nuid,
            nickname=r[3] or "",   # kuaishou_name
            cookie=cookie,
        ))
    logger.info(
        f"[ks.cookie_pool] self_pool: rows={len(rows)} ok={ok_n} "
        f"bad_format={bad_format}"
    )
    return rs


def refresh(db=None, *, include_zhongxiangbao: bool = False) -> int:
    """刷新池缓存. 返回池大小.

    自家池 (CloudCookieAccount) 优先; zhongxiangbao 默认关 (服务器在 HK 走不通).
    db 不传时自动开短生命周期 session.
    """
    own_session = False
    if db is None:
        try:
            db = _ensure_db_session()
            own_session = True
        except Exception as ex:
            logger.warning(f"[ks.cookie_pool] 无法开 session: {ex}")
            db = None

    try:
        with _lock:
            records: list[CookieRecord] = []
            # 1. 自家池(主)
            if db is not None:
                records.extend(_fetch_self_pool(db))
            # 2. zhongxiangbao(可选 — 网络可达时打开)
            if include_zhongxiangbao:
                records.extend(_fetch_zhongxiangbao())
            # 去重 (同 uid_short 优先 self)
            seen: set[str] = set()
            dedup: list[CookieRecord] = []
            for r in records:
                if r.uid_short in seen:
                    continue
                seen.add(r.uid_short)
                dedup.append(r)
            _state.records = dedup
            _state.fetched_at = time.time()
            logger.info(f"[ks.cookie_pool] 刷新, total={len(dedup)} (raw={len(records)})")
            return len(dedup)
    finally:
        if own_session and db is not None:
            try:
                db.close()
            except Exception:
                pass


def _ensure_db_session():
    """需要 db 但调用方没传时, 自己建一个 session (短生命周期)."""
    from app.core.db import get_session_factory
    Session = get_session_factory()
    return Session()


def get_records(db=None, force_refresh: bool = False) -> list[CookieRecord]:
    """获取当前池(按需刷新). 不传 db 时自动开 session."""
    with _lock:
        if force_refresh or time.time() - _state.fetched_at > CACHE_TTL_S:
            if db is None:
                with _ensure_db_session() as s:
                    refresh(s)
            else:
                refresh(db)
        return list(_state.records)


def pick(db=None) -> CookieRecord | None:
    """随机挑一条健康 cookie. 没健康的返 None.

    优先策略: login_status='valid' 的优先, 其次 unknown, 最后 fail_count<3.
    """
    rs = [r for r in get_records(db) if r.is_healthy()]
    if not rs:
        return None
    return random.choice(rs)


# --- PATCHED v4 mark_db ---
def mark_db_status(source_id: int | str, status: str) -> None:
    """同步标记 cloud_cookie_accounts.login_status (huoshijie 实际表).

    status 在 huoshijie 实际语义: 'logged_in' / 'logout' / 'expired' / 'invalid'
    我们传 'invalid' / 'expired' 也兼容
    """
    if not isinstance(source_id, int):
        return
    try:
        from sqlalchemy import text
        with _ensure_db_session() as s:
            s.execute(text(
                "UPDATE cloud_cookie_accounts SET login_status = :st WHERE id = :i"
            ), {"st": status, "i": source_id})
            s.commit()
    except Exception as ex:
        logger.warning(f"[ks.cookie_pool] mark_db_status 失败 id={source_id}: {ex}")


def mark_failed(cookie_record: CookieRecord, *, fatal: bool = False, reason: str = ""):
    """记一次失败. fatal=True 直接标 invalid + DB 同步."""
    with _lock:
        cookie_record.fail_count += 1
        cookie_record.last_failed_at = time.time()
        if fatal:
            cookie_record.is_invalid = True
            logger.warning(
                f"[ks.cookie_pool] cookie 失效 fatal: src={cookie_record.source} "
                f"id={cookie_record.source_id} uid={cookie_record.uid_short} "
                f"({cookie_record.nickname}) reason={reason}"
            )
            if cookie_record.source == "self":
                mark_db_status(cookie_record.source_id, "expired")


def mark_success(cookie_record: CookieRecord):
    """记一次成功 — 重置 fail_count + DB last_success_at."""
    with _lock:
        cookie_record.fail_count = 0
        cookie_record.last_used_at = time.time()
    # --- PATCHED v4 mark_success ---
    # huoshijie 实际表: login_time(没 last_success_at). 仅更新 login_time + 修正 status
    if cookie_record.source == "self" and isinstance(cookie_record.source_id, int):
        try:
            from sqlalchemy import text
            from datetime import datetime, timezone
            with _ensure_db_session() as s:
                s.execute(text(
                    "UPDATE cloud_cookie_accounts SET login_time = :t, "
                    "login_status = CASE WHEN login_status IN ('unknown','expired') "
                    "THEN 'logged_in' ELSE login_status END "
                    "WHERE id = :i"
                ), {"t": datetime.now(timezone.utc), "i": cookie_record.source_id})
                s.commit()
        except Exception as ex:
            logger.debug(f"[ks.cookie_pool] mark_success db sync 失败: {ex}")


def stats() -> dict:
    """池状态汇总."""
    with _lock:
        rs = _state.records
        healthy = [r for r in rs if r.is_healthy()]
        invalid = [r for r in rs if r.is_invalid]
        return {
            "total": len(rs),
            "healthy": len(healthy),
            "invalid": len(invalid),
            "fetched_at": datetime.fromtimestamp(_state.fetched_at, tz=timezone.utc).isoformat() if _state.fetched_at else None,
            "sample_uids": [r.uid_short for r in rs[:5]],
        }
