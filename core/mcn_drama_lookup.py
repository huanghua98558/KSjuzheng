# -*- coding: utf-8 -*-
"""
MCN 剧库统一 lookup — **主 MCN MySQL 实时, fallback 本地备份**.

用户架构决策 (2026-04-21 KS184 抓包后):
  "我们系统要走服务器. 本地定时拉服务器数据, 作为备份数据源,
   在服务器不可用的时候用本地数据"

本模块实现三个层次:

  get_banner_by_drama(drama_name) → {banner_task_id, series_name, title, ...}
    L1  MCN MySQL  (im.zhongxiangbao.com:3306) — 实时, 权威
    L2  local  drama_banner_tasks              — 备份, 5s 全量同步
    L3  None                                    — 真的找不到

用法 (publisher.py / planner / collector):

    from core.mcn_drama_lookup import get_banner_by_drama
    info = get_banner_by_drama("望夫成龙")
    if info:
        submit_body["bannerTask"]["bannerTaskId"] = info["banner_task_id"]

进程级 5s TTL cache (避免 MCN 单次任务打数千次).
MCN 连接失败自动切 L2, 不阻塞发布.
"""
from __future__ import annotations

import logging
import sqlite3
import threading
import time
from typing import Any, Optional

import pymysql

from core.config import DB_PATH

logger = logging.getLogger(__name__)

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
            connect_timeout=5,
            read_timeout=8,
            write_timeout=8,
        )
    except Exception:
        return dict(
            host="im.zhongxiangbao.com", port=3306,
            user="shortju", password="REPLACE_WITH_MCN_MYSQL_PASSWORD",
            database="shortju", charset="utf8mb4",
            connect_timeout=5, read_timeout=8, write_timeout=8,
        )

MCN_CONFIG = _build_mcn_config()

# 进程级 cache
_CACHE: dict[str, tuple[float, Optional[dict]]] = {}
_CACHE_TTL_SEC = 300   # 5 分钟 TTL (MCN 数据不常变)
_CACHE_LOCK = threading.Lock()


# ★ 2026-04-24 v6 Day 4: 迁移到统一 circuit_breaker
# 老 _MCN_UNHEALTHY_UNTIL / _mark_mcn_(un)healthy 被 get_breaker("mcn_mysql") 代替.
# 3 个老函数保留作向后兼容 (内部桥接到 breaker).

def _mcn_is_healthy() -> bool:
    from core.circuit_breaker import get_breaker
    return get_breaker("mcn_mysql").allow()


def _mark_mcn_unhealthy() -> None:
    from core.circuit_breaker import get_breaker
    get_breaker("mcn_mysql").mark_failure(reason="drama_lookup_query_fail")


def _mark_mcn_healthy() -> None:
    from core.circuit_breaker import get_breaker
    get_breaker("mcn_mysql").mark_success()


def _query_mcn(drama_name: str) -> Optional[dict]:
    """L1: MCN MySQL live query. None if miss / connect fail.

    ORDER: 优先选**真实产生过分佣**的 biz_id (fluorescent_income 里有记录),
           次按 biz_id ASC 取最早稳定条目 (同名多条时).
    铁证: 车厢里的秘密 biz=455258 (3 条收益) vs 471799 (0 收益) —
          KS184 选 455258, 证明"曾赚钱"优先于"最新创建".
    """
    if not _mcn_is_healthy():
        return None
    try:
        conn = pymysql.connect(**MCN_CONFIG)
        try:
            with conn.cursor(pymysql.cursors.DictCursor) as c:
                # CLAUDE.md §2 铁证: promotion_type=None=老萤光分佣主力,
                #                    promotion_type=7=新 CPS 效果计费未激活 commission=0
                # KS184 7-Layer Frida (2026-04-21 §23): 12/12 submit 选的全是
                #   business_type=0, promotion_type=None/0, commission=70, platform=2 的老任务
                sql = """
                    SELECT
                        sdi.biz_id AS banner_task_id,
                        sdi.title,
                        JSON_UNQUOTE(JSON_EXTRACT(sdi.raw_data,'$.seriesName')) AS series_name,
                        sdi.commission_rate,
                        sdi.promotion_type,
                        sdi.view_status,
                        sdi.start_time,
                        sdi.end_time,
                        sdi.serial_id,
                        JSON_UNQUOTE(JSON_EXTRACT(sdi.raw_data,'$.coverImg'))   AS cover_img,
                        sdi.business_type,
                        sdi.platform,
                        (SELECT COUNT(*) FROM fluorescent_income fi
                           WHERE fi.task_id = sdi.biz_id) AS income_cnt,
                        (SELECT MAX(fi.created_at) FROM fluorescent_income fi
                           WHERE fi.task_id = sdi.biz_id) AS last_income_at
                    FROM spark_drama_info sdi
                    WHERE (
                            JSON_UNQUOTE(JSON_EXTRACT(sdi.raw_data,'$.seriesName')) = %s
                         OR sdi.title = %s
                          )
                      -- 硬过滤: 排除新 CPS 效果计费 (promotion_type=7 / business_type=2)
                      -- 不要求 commission>0 (MCN 老条目 commission 常为 0 但实际可投)
                      AND (sdi.business_type = 0 OR sdi.business_type IS NULL)
                      AND (sdi.promotion_type IS NULL OR sdi.promotion_type = 0)
                    ORDER BY
                        -- 1. seriesName 精确匹配优先 (比 title 回退更可靠)
                        CASE WHEN JSON_UNQUOTE(JSON_EXTRACT(sdi.raw_data,'$.seriesName')) = %s THEN 0 ELSE 1 END,
                        -- 2. 取最早/最稳定主条目 (同剧多条时: 旧 biz 经过测试, 投稿接受率更高)
                        sdi.biz_id ASC
                    LIMIT 1
                """
                c.execute(sql, (drama_name, drama_name, drama_name))
                row = c.fetchone()
                _mark_mcn_healthy()
                if row:
                    return {
                        "banner_task_id": str(row["banner_task_id"]),
                        "drama_name": row.get("series_name") or row.get("title") or drama_name,
                        "series_name": row.get("series_name"),
                        "task_title": row.get("title"),
                        "commission_rate": row.get("commission_rate"),
                        "promotion_type": row.get("promotion_type"),
                        "view_status": row.get("view_status"),
                        "start_time": row.get("start_time"),
                        "end_time": row.get("end_time"),
                        "serial_id": row.get("serial_id"),
                        "cover_img": row.get("cover_img"),
                        "income_cnt": int(row.get("income_cnt") or 0),
                        "last_income_at": str(row["last_income_at"]) if row.get("last_income_at") else None,
                        "_source": "mcn_mysql",
                    }
                return None
        finally:
            conn.close()
    except Exception as e:
        logger.warning("[mcn_drama_lookup] MCN unhealthy → fallback local: %r", e)
        _mark_mcn_unhealthy()
        return None


def _query_local(drama_name: str) -> Optional[dict]:
    """L2: local drama_banner_tasks backup."""
    try:
        c = sqlite3.connect(DB_PATH, timeout=10)
        try:
            c.execute("PRAGMA busy_timeout=10000")
            c.row_factory = sqlite3.Row
            # 优先 series_name 完全匹配, 再 drama_name, 最后 task_title
            cur = c.execute(
                """
                SELECT banner_task_id, drama_name, series_name, task_title,
                       commission_rate, promotion_type, view_status,
                       start_time, end_time, serial_id, cover_img
                FROM drama_banner_tasks
                WHERE series_name = ?
                   OR drama_name  = ?
                   OR task_title  = ?
                ORDER BY
                    CASE WHEN series_name = ? THEN 0
                         WHEN drama_name  = ? THEN 1
                         ELSE 2 END,
                    COALESCE(view_status, -1) DESC,
                    CAST(banner_task_id AS INTEGER) DESC
                LIMIT 1
                """,
                (drama_name, drama_name, drama_name, drama_name, drama_name),
            )
            r = cur.fetchone()
            if r:
                d = dict(r)
                d["_source"] = "local_backup"
                return d
            return None
        finally:
            c.close()
    except Exception as e:
        logger.error("[mcn_drama_lookup] local lookup failed: %r", e)
        return None


def get_banner_by_drama(drama_name: str, *, skip_cache: bool = False) -> Optional[dict]:
    """Main API: L1 MCN live → L2 local backup → None.

    Returns dict with keys: banner_task_id, drama_name, series_name, task_title,
    commission_rate, promotion_type, view_status, start_time, end_time, serial_id,
    cover_img, _source ('mcn_mysql' | 'local_backup').
    """
    if not drama_name:
        return None
    drama_name = drama_name.strip()
    if not drama_name:
        return None

    # Cache (TTL)
    if not skip_cache:
        with _CACHE_LOCK:
            ent = _CACHE.get(drama_name)
            if ent and (time.time() - ent[0]) < _CACHE_TTL_SEC:
                return ent[1]

    # L1: MCN MySQL
    r = _query_mcn(drama_name)
    if r is None:
        # L2: local
        r = _query_local(drama_name)
    with _CACHE_LOCK:
        _CACHE[drama_name] = (time.time(), r)
    return r


def get_banner_task_id(drama_name: str) -> Optional[str]:
    """Shortcut — only banner_task_id, None if not found."""
    info = get_banner_by_drama(drama_name)
    return info["banner_task_id"] if info else None


def invalidate_cache() -> None:
    """Clear process cache (e.g. after sync_spark_drama_full runs)."""
    with _CACHE_LOCK:
        _CACHE.clear()


def health_check() -> dict:
    """Small probe for monitoring page."""
    t0 = time.time()
    mcn_ok = False
    mcn_rows = 0
    try:
        conn = pymysql.connect(**MCN_CONFIG)
        try:
            with conn.cursor() as c:
                c.execute("SELECT COUNT(*) FROM spark_drama_info WHERE biz_id IS NOT NULL")
                mcn_rows = c.fetchone()[0]
                mcn_ok = True
                _mark_mcn_healthy()
        finally:
            conn.close()
    except Exception as e:
        logger.warning("[mcn_drama_lookup.health_check] MCN: %r", e)
        _mark_mcn_unhealthy()

    local_rows = 0
    try:
        c = sqlite3.connect(DB_PATH, timeout=5)
        try:
            local_rows = c.execute("SELECT COUNT(*) FROM drama_banner_tasks").fetchone()[0]
        finally:
            c.close()
    except Exception as e:
        logger.error("[mcn_drama_lookup.health_check] local: %r", e)

    return {
        "mcn_mysql_ok": mcn_ok,
        "mcn_rows": mcn_rows,
        "local_rows": local_rows,
        "elapsed_sec": round(time.time() - t0, 3),
        "cache_size": len(_CACHE),
    }


if __name__ == "__main__":
    import argparse
    import json as _j
    import sys as _sys

    try:
        _sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

    ap = argparse.ArgumentParser()
    ap.add_argument("drama", nargs="?", default=None)
    ap.add_argument("--health", action="store_true")
    args = ap.parse_args()

    if args.health:
        print(_j.dumps(health_check(), ensure_ascii=False, indent=2))
    elif args.drama:
        r = get_banner_by_drama(args.drama)
        print(_j.dumps(r, ensure_ascii=False, indent=2, default=str))
    else:
        # Regress 12 known banners
        tests = [
            "望夫成龙", "黄金瞳我家萌宝五岁半", "拳王之父子双龙",
            "迫嫁局中局", "心动陷阱", "长嫂如母恩重如山",
            "你的背叛似海浪", "盲心大逃脱", "摊牌了我就是大小姐1",
            "我的存款不翼而飞", "车厢里的秘密",
            "根本不存在的剧AAA",
        ]
        for d in tests:
            r = get_banner_by_drama(d)
            if r:
                print(f"  OK  {d:22s}  {r['banner_task_id']:8s}  ({r['_source']})")
            else:
                print(f"  MISS {d}")
