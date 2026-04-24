# -*- coding: utf-8 -*-
"""
★ 2026-04-22 §27: 实时 MCN 服务器 URL 拉取 (每次发布实时查, 不依赖本地缓存).

用户架构决策 (铁令):
  "完整流程是要系统每次发布都是实时服务器获取链接并开始下载.
   我们本地的数据库作为长期备份的存在."

对齐 KS184 源码 SQL (captain 走 fangzhou/zhongxiangbao fallback, captain 不是 collector):
  SELECT name, url FROM wait_collect_videos
    WHERE name = %s [AND username = %s]
    ORDER BY RAND() LIMIT 1

本模块双路查询:
  1. wait_collect_videos (21.9k, 53.5% CDN 直链) — 高转化池, KS184 真正主路
  2. kuaishou_urls (1.8M) — 短链池, 备用
都是 MCN 服务器实时查, 不经本地缓存.

本地 DB (drama_links / mcn_url_pool / mcn_wait_collect_videos) 只在 MCN 断线时兜底.

性能:
  - 单查询 ~20ms (LAN), 可接受
  - 连接缓存 + 5s TTL 避免建连风暴
  - 连续失败 30s 熔断, 自动 fallback 本地

配置:
  ai.url_source.realtime_enabled          = true   # 总开关
  ai.url_source.realtime_prefer_cdn       = true   # CDN 优先 (wait_collect)
  ai.url_source.realtime_wait_collect_limit = 10
  ai.url_source.realtime_kuaishou_urls_limit = 20
  ai.url_source.circuit_break_sec        = 30     # 连续失败熔断秒
  ai.url_source.query_timeout_ms          = 2000  # 单查超时
"""
from __future__ import annotations

import logging
import threading
import time
from typing import Optional

import pymysql

from core.db_manager import DBManager

log = logging.getLogger(__name__)


# ★ 2026-04-24 v6 Day 6: 迁 core/secrets
def _build_mcn_config():
    try:
        from core.secrets import get
        return dict(
            host=get("KS_MCN_MYSQL_HOST"),
            port=int(get("KS_MCN_MYSQL_PORT", "3306")),
            user=get("KS_MCN_MYSQL_USER"),
            password=get("KS_MCN_MYSQL_PASSWORD"),
            database=get("KS_MCN_MYSQL_DB"),
            charset="utf8mb4",
            connect_timeout=5, read_timeout=10,
            autocommit=True,
        )
    except Exception:
        return dict(
            host="im.zhongxiangbao.com", port=3306,
            user="shortju", password="REPLACE_WITH_MCN_MYSQL_PASSWORD",
            database="shortju", charset="utf8mb4",
            connect_timeout=5, read_timeout=10,
            autocommit=True,
        )

MCN_CONFIG = _build_mcn_config()


# ───────── 熔断状态 ─────────
# ★ 2026-04-24 v6 Day 4: 迁移到统一 core/circuit_breaker
# 老 _last_fail_at / _circuit_open 由 get_breaker("mcn_url_realtime") 取代.
# 保持同名函数 (_check_circuit / _mark_fail / _mark_ok) 为向后兼容.
_CIRCUIT_LOCK = threading.RLock()   # 兼容老代码的 lock 引用 (无实际功能)


def _cfg(key: str, default):
    try:
        dbm = DBManager()
        v = dbm.get_app_config(key)
        if v is None:
            return default
        if isinstance(default, bool):
            return str(v).lower() in ("1", "true", "yes")
        if isinstance(default, int):
            return int(v)
        if isinstance(default, float):
            return float(v)
        return v
    except Exception:
        return default


def _check_circuit() -> bool:
    """True = 熔断中 (不要试). 代理到 circuit_breaker.allow() (反向)."""
    from core.circuit_breaker import get_breaker
    return not get_breaker("mcn_url_realtime").allow()


def _mark_fail():
    from core.circuit_breaker import get_breaker
    get_breaker("mcn_url_realtime").mark_failure(reason="realtime_query_fail")


def _mark_ok():
    from core.circuit_breaker import get_breaker
    get_breaker("mcn_url_realtime").mark_success()


# 为老的 health_check 保留兼容 getter (module-level function, 不是 property)
def _get_circuit_state() -> dict:
    from core.circuit_breaker import get_breaker
    snap = get_breaker("mcn_url_realtime").snapshot()
    return {
        "circuit_open": snap["state"] == "open",
        "last_fail_at": snap["last_failure"],
    }


# ───────── 公开 API ─────────
def fetch_urls_realtime(drama_name: str, username_preferred: Optional[str] = None) -> list[dict]:
    """★ 实时从 MCN 服务器拉 drama 的所有 URL.

    Args:
        drama_name: 剧名 (精确匹配 name 字段)
        username_preferred: captain username (若 KS184 有对应采集者). 一般 None 即可 —
            captain 'huanghua888' 不是 collector, KS184 会自动 fallback 不限 username.

    Returns:
        list of dict: [{'url': 'https://...', 'source': 'wait_collect'|'kuaishou_urls',
                         'is_cdn': bool, 'cover_url': str|None}]
        按 CDN 优先排序 (CDN 直链 > 短链).
        空 list = MCN 未命中或熔断.

    典型耗时:
        20-50ms (LAN), 熔断时 0ms 直返.
    """
    if not _cfg("ai.url_source.realtime_enabled", True):
        return []

    if _check_circuit():
        log.debug("[mcn_url_realtime] circuit open, skip (drama=%s)", drama_name)
        return []

    urls: list[dict] = []
    t0 = time.time()

    conn = None
    try:
        conn = pymysql.connect(**MCN_CONFIG)
        cur = conn.cursor(pymysql.cursors.DictCursor)

        # ── 路 1: wait_collect_videos (53% CDN 直链, KS184 高转化池) ──
        wc_limit = _cfg("ai.url_source.realtime_wait_collect_limit", 10)

        # KS184 原 SQL: 先试 username_preferred, 再 fallback 全局
        if username_preferred:
            cur.execute(
                """SELECT url, username, cover_url FROM wait_collect_videos
                   WHERE name = %s AND username = %s
                   ORDER BY RAND() LIMIT %s""",
                (drama_name, username_preferred, wc_limit),
            )
            wc_rows = cur.fetchall()
            if not wc_rows:  # KS184 fallback: 不限 username
                cur.execute(
                    """SELECT url, username, cover_url FROM wait_collect_videos
                       WHERE name = %s ORDER BY RAND() LIMIT %s""",
                    (drama_name, wc_limit),
                )
                wc_rows = cur.fetchall()
        else:
            cur.execute(
                """SELECT url, username, cover_url FROM wait_collect_videos
                   WHERE name = %s ORDER BY RAND() LIMIT %s""",
                (drama_name, wc_limit),
            )
            wc_rows = cur.fetchall()

        for r in wc_rows:
            u = r["url"]
            is_cdn = any(m in u for m in (".mp4", "djvod", "oskwai", "kwaicdn", ".m3u8", "ndcimgs"))
            urls.append({
                "url": u,
                "source": "wait_collect",
                "is_cdn": is_cdn,
                "cover_url": r.get("cover_url"),
            })

        # ── 路 2: kuaishou_urls (1.8M 短链池, 量大但全短链) ──
        ku_limit = _cfg("ai.url_source.realtime_kuaishou_urls_limit", 20)
        if len(urls) < ku_limit:
            cur.execute(
                """SELECT url FROM kuaishou_urls WHERE name = %s ORDER BY RAND() LIMIT %s""",
                (drama_name, ku_limit - len(urls)),
            )
            for r in cur.fetchall():
                u = r["url"]
                is_cdn = any(m in u for m in (".mp4", "djvod", "oskwai", "kwaicdn", ".m3u8", "ndcimgs"))
                urls.append({
                    "url": u,
                    "source": "kuaishou_urls",
                    "is_cdn": is_cdn,
                    "cover_url": None,
                })

        cur.close()

        # CDN 优先 (排到前面), 短链在后
        if _cfg("ai.url_source.realtime_prefer_cdn", True):
            urls.sort(key=lambda x: (0 if x["is_cdn"] else 1))

        _mark_ok()
        elapsed = (time.time() - t0) * 1000
        cdn_n = sum(1 for u in urls if u["is_cdn"])
        log.info("[mcn_url_realtime] drama=%r → %d urls (%d CDN) in %.0fms",
                  drama_name, len(urls), cdn_n, elapsed)
        return urls

    except Exception as e:
        elapsed = (time.time() - t0) * 1000
        _mark_fail()
        log.warning("[mcn_url_realtime] FAIL drama=%r after %.0fms: %s", drama_name, elapsed, e)
        return []

    finally:
        if conn:
            try: conn.close()
            except Exception: pass


def fetch_urls_simple(drama_name: str) -> list[str]:
    """简化版: 只返 url 字符串列表 (向后兼容)."""
    return [r["url"] for r in fetch_urls_realtime(drama_name)]


def health_check() -> dict:
    """健康检测 (用于 Dashboard + watchdog)."""
    t0 = time.time()
    try:
        conn = pymysql.connect(**MCN_CONFIG)
        cur = conn.cursor()
        cur.execute("SELECT 1")
        cur.fetchone()
        cur.close()
        conn.close()
        cs = _get_circuit_state()
        return {
            "ok": True,
            "latency_ms": (time.time() - t0) * 1000,
            **cs,
        }
    except Exception as e:
        cs = _get_circuit_state()
        return {
            "ok": False,
            "error": str(e),
            "latency_ms": (time.time() - t0) * 1000,
            **cs,
        }


if __name__ == "__main__":
    # CLI smoke test
    import sys, json
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    try: sys.stdout.reconfigure(encoding="utf-8")
    except Exception: pass

    print("=== MCN Realtime URL Fetcher CLI ===")
    print(json.dumps(health_check(), ensure_ascii=False, indent=2))
    print()

    tests = sys.argv[1:] or ["冤家路窄偏遇你", "一世王妃倾天下", "红豆生南国"]
    for name in tests:
        urls = fetch_urls_realtime(name)
        print(f"[{name}] {len(urls)} urls:")
        for u in urls[:5]:
            host = u["url"].split("/")[2] if "://" in u["url"] else u["url"][:40]
            print(f"  {'[CDN]' if u['is_cdn'] else '[SHR]'} {u['source']:<15} {host}")
        print()
