# -*- coding: utf-8 -*-
"""
drama_pool — 按剧名从本地 MCN 镜像里选可用短链.

CLAUDE.md §26 (2026-04-22): 把 MCN `kuaishou_urls` (181 万) + `drama_collections`
(13.5 万) 全量镜像到本地 `mcn_url_pool` + `mcn_drama_collections`.
这就是 KS184 "高转化提取" 的底层剧库, 和它**完全对齐**.

本模块 API:
    pick_share_urls(drama_name, limit=5)         → [url, url, ...]
    pick_share_urls_with_author(drama_name, ...) → [(url, author_uid), ...]
    count_urls_for_drama(drama_name)             → int
    list_available_dramas(min_urls=1, limit=50)  → [(name, url_count), ...]
    dramas_with_commission(limit=50)             → 带分佣权重排序 (高转化等价)

架构:
    L1  mcn_url_pool (local, 181 万) — 主池
    L2  drama_links (local, 455, KS184 已解析 CDN) — 直接可用的直链备份
    L3  on_demand_feed (实时采 via profile API) — 终极 fallback

选链顺序: L2 (有 CDN) → L1 (短链, 需 resolve) → L3 (实时采).
"""
from __future__ import annotations

import logging
import random
import sqlite3
from typing import Optional

from core.config import DB_PATH

log = logging.getLogger(__name__)


def _conn() -> sqlite3.Connection:
    c = sqlite3.connect(DB_PATH, timeout=10)
    c.execute("PRAGMA busy_timeout=10000")
    c.row_factory = sqlite3.Row
    return c


def count_urls_for_drama(drama_name: str) -> dict:
    """返回 {pool: N, drama_links_cdn: N, drama_collections: N} — 该剧可用性概览."""
    c = _conn()
    try:
        r = c.execute(
            "SELECT COUNT(*) FROM mcn_url_pool WHERE name = ?", (drama_name,),
        ).fetchone()
        pool_n = r[0] if r else 0
        r = c.execute(
            """SELECT COUNT(*) FROM drama_links
               WHERE drama_name = ?
                 AND (status IS NULL OR status NOT IN ('dead', 'quarantined'))""",
            (drama_name,),
        ).fetchone()
        dl_n = r[0] if r else 0
        r = c.execute(
            "SELECT COUNT(*) FROM mcn_drama_collections WHERE drama_name = ? AND drama_url != '-'",
            (drama_name,),
        ).fetchone()
        coll_n = r[0] if r else 0
        return {"pool": pool_n, "drama_links": dl_n, "collections": coll_n}
    finally:
        c.close()


def pick_share_urls(drama_name: str, *,
                     limit: int = 5,
                     prefer_cdn: bool = True,
                     exclude_hosts: Optional[list[str]] = None,
                     ) -> list[str]:
    """按 drama_name 选短链/CDN URL, 3 路 fallback.

    Args:
        drama_name: 剧名 (严格等值匹配)
        limit: 返回数量上限
        prefer_cdn: 优先返 drama_links 里的 CDN 直链 (已解析, 跳过限流)
        exclude_hosts: 过滤掉某些 host (如 v.douyin.com 如果只要 kuaishou)

    Returns:
        ['https://www.kuaishou.com/f/XXX', ...] 或空 list.
    """
    urls: list[str] = []
    seen: set[str] = set()
    excludes = tuple(exclude_hosts or [])

    c = _conn()
    try:
        # L2: drama_links (本地已解析的 CDN 直链)
        if prefer_cdn:
            rows = c.execute(
                """SELECT drama_url FROM drama_links
                   WHERE drama_name = ?
                     AND (status IS NULL OR status NOT IN ('dead','quarantined'))
                   ORDER BY COALESCE(last_success_at, last_used_at, updated_at) DESC
                   LIMIT ?""",
                (drama_name, limit * 2),
            ).fetchall()
            for r in rows:
                u = r[0]
                if not u or u in seen: continue
                if excludes and any(h in u for h in excludes): continue
                urls.append(u)
                seen.add(u)
                if len(urls) >= limit: return urls

        # L1: mcn_url_pool (181 万短链主池)
        rows = c.execute(
            "SELECT url FROM mcn_url_pool WHERE name = ? LIMIT ?",
            (drama_name, limit * 5),
        ).fetchall()
        candidates = [r[0] for r in rows if r[0] and r[0] not in seen]
        if excludes:
            candidates = [u for u in candidates if not any(h in u for h in excludes)]
        # 随机洗牌避免总选同几条 (url 被服务端标记)
        random.shuffle(candidates)
        for u in candidates:
            urls.append(u)
            seen.add(u)
            if len(urls) >= limit: return urls

        # L3: mcn_drama_collections (13.5 万采集历史, 有重复)
        rows = c.execute(
            """SELECT drama_url FROM mcn_drama_collections
               WHERE drama_name = ?
                 AND drama_url != '-' AND drama_url IS NOT NULL AND drama_url != ''
               LIMIT ?""",
            (drama_name, limit * 5),
        ).fetchall()
        candidates = [r[0] for r in rows if r[0] and r[0] not in seen]
        if excludes:
            candidates = [u for u in candidates if not any(h in u for h in excludes)]
        random.shuffle(candidates)
        for u in candidates:
            urls.append(u)
            seen.add(u)
            if len(urls) >= limit: return urls
    finally:
        c.close()
    return urls


def pick_share_urls_with_author(drama_name: str, limit: int = 5,
                                  ) -> list[tuple[str, str, str]]:
    """按 drama_name 选短链, 带作者信息. Returns [(url, uid, nickname), ...]."""
    c = _conn()
    try:
        rows = c.execute(
            """SELECT url, uid, nickname FROM mcn_url_pool
               WHERE name = ? LIMIT ?""",
            (drama_name, limit * 3),
        ).fetchall()
        out = []
        seen = set()
        for r in rows:
            if r[0] in seen: continue
            seen.add(r[0])
            out.append((r[0], r[1] or "", r[2] or ""))
            if len(out) >= limit: break
        random.shuffle(out)
        return out
    finally:
        c.close()


def list_available_dramas(min_urls: int = 5, limit: int = 50,
                           plan_mode: Optional[str] = None) -> list[tuple[str, int]]:
    """列可用剧名 (按 url 池里条数排序).

    Args:
        min_urls: 至少有 min_urls 条候选的剧才返回
        limit: 返回数量
        plan_mode: 'firefly' | 'spark' | None (None 查 mcn_url_pool; 指定则查 drama_collections)
    """
    c = _conn()
    try:
        if plan_mode:
            rows = c.execute(
                """SELECT drama_name, COUNT(*) c FROM mcn_drama_collections
                   WHERE plan_mode = ? AND drama_name != '' AND drama_name IS NOT NULL
                     AND drama_url != '-'
                   GROUP BY drama_name
                   HAVING c >= ?
                   ORDER BY c DESC LIMIT ?""",
                (plan_mode, min_urls, limit),
            ).fetchall()
        else:
            rows = c.execute(
                """SELECT name, COUNT(*) c FROM mcn_url_pool
                   WHERE name != '' AND name IS NOT NULL
                   GROUP BY name
                   HAVING c >= ?
                   ORDER BY c DESC LIMIT ?""",
                (min_urls, limit),
            ).fetchall()
        return [(r[0], r[1]) for r in rows]
    finally:
        c.close()


def dramas_with_commission(limit: int = 50, min_urls: int = 3) -> list[dict]:
    """返回 **有分佣的 drama + 有池子 URL** 的剧列表 (KS184 高转化提取等价).

    逻辑: drama_banner_tasks (本地 MCN 剧库镜像, 134k)
          INNER JOIN mcn_url_pool (按 drama_name 有 >= min_urls 条)
          按 commission_rate DESC 排序.

    Returns [{drama_name, banner_task_id, commission_rate, url_count}, ...].
    """
    c = _conn()
    try:
        # 本地 drama_banner_tasks 没 business_type 列 (纯 MCN 镜像, 过滤在 sync 时已做),
        # 但有 promotion_type — 过滤掉 promotion_type=7 (效果计费 0 分佣)
        rows = c.execute(
            """SELECT * FROM (
                   SELECT d.drama_name, d.banner_task_id, d.commission_rate,
                          (SELECT COUNT(*) FROM mcn_url_pool p WHERE p.name = d.drama_name) AS url_count
                   FROM drama_banner_tasks d
                   WHERE d.drama_name IS NOT NULL AND d.drama_name != ''
                     AND (d.promotion_type IS NULL OR d.promotion_type = 0)
                     AND (d.commission_rate IS NULL OR d.commission_rate > 0)
               ) sub
               WHERE url_count >= ?
               ORDER BY commission_rate DESC, url_count DESC
               LIMIT ?""",
            (min_urls, limit),
        ).fetchall()
        return [
            {
                "drama_name": r[0], "banner_task_id": r[1],
                "commission_rate": r[2], "url_count": r[3],
            }
            for r in rows
        ]
    finally:
        c.close()


def health_check() -> dict:
    """Pool 健康状态 (用于 Dashboard / ControllerAgent 监控)."""
    c = _conn()
    try:
        r = c.execute("SELECT COUNT(*) FROM mcn_url_pool").fetchone()
        pool_n = r[0]
        r = c.execute("SELECT COUNT(DISTINCT name) FROM mcn_url_pool WHERE name != ''").fetchone()
        unique_dramas = r[0]
        r = c.execute("SELECT COUNT(*) FROM mcn_drama_collections").fetchone()
        coll_n = r[0]
        r = c.execute("SELECT MAX(synced_at) FROM mcn_url_pool").fetchone()
        last_sync = r[0]
        # 交集度: 有多少 drama_banner_tasks 的剧在 url_pool 里有 URL
        r = c.execute("""
            SELECT COUNT(DISTINCT d.drama_name)
            FROM drama_banner_tasks d
            WHERE EXISTS (SELECT 1 FROM mcn_url_pool p WHERE p.name = d.drama_name)
        """).fetchone()
        intersect_n = r[0]
        r = c.execute("SELECT COUNT(DISTINCT drama_name) FROM drama_banner_tasks").fetchone()
        banner_unique = r[0]
        return {
            "mcn_url_pool_total": pool_n,
            "unique_dramas_in_pool": unique_dramas,
            "mcn_drama_collections_total": coll_n,
            "last_sync_at": last_sync,
            "banner_tasks_unique": banner_unique,
            "banner_with_url_intersect": intersect_n,
            "intersect_rate_pct": round(100 * intersect_n / banner_unique, 2) if banner_unique else 0,
        }
    finally:
        c.close()


if __name__ == "__main__":
    import argparse, json, sys
    try: sys.stdout.reconfigure(encoding="utf-8")
    except Exception: pass

    ap = argparse.ArgumentParser()
    ap.add_argument("--drama", type=str, help="查某剧可用链接")
    ap.add_argument("--limit", type=int, default=5)
    ap.add_argument("--top", action="store_true", help="列 TOP drama with commission")
    ap.add_argument("--health", action="store_true")
    args = ap.parse_args()

    if args.health:
        print(json.dumps(health_check(), ensure_ascii=False, indent=2))
    elif args.drama:
        print(f"=== {args.drama} ===")
        print(f"counts: {json.dumps(count_urls_for_drama(args.drama), ensure_ascii=False)}")
        print("picked URLs:")
        for u in pick_share_urls(args.drama, limit=args.limit):
            print(f"  {u}")
        print("with author:")
        for u, uid, nick in pick_share_urls_with_author(args.drama, limit=args.limit):
            print(f"  {u}  [uid={uid} nick={nick}]")
    elif args.top:
        print("=== TOP drama (with banner + pool URLs) ===")
        for d in dramas_with_commission(limit=20):
            print(f"  commission={d['commission_rate']:>5.1f}%  urls={d['url_count']:>4d}  "
                   f"bid={d['banner_task_id']}  {d['drama_name']}")
    else:
        # 默认 health + top 10
        h = health_check()
        print("=== Pool Health ===")
        for k, v in h.items(): print(f"  {k}: {v}")
        print()
        print("=== TOP 10 (commission × url_count) ===")
        for d in dramas_with_commission(limit=10):
            print(f"  c={d['commission_rate']:>5.1f}%  urls={d['url_count']:>4d}  "
                   f"bid={d['banner_task_id']}  {d['drama_name']}")
