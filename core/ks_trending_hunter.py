# -*- coding: utf-8 -*-
"""爆款雷达 — 扫作者池, 宽容入 hot_photos (前期不预设阈值, 以数据说话).

★ 2026-04-24 v6 Week 2 Day 8+ 核心模块

设计思想 (用户定调):
  "前期数据量少, 以实际测试为准, 后期慢慢定标准"
  → 宽容采集, 不做强筛选, 让 publish_outcome 数据决定后期阈值
  → 所有候选都有机会验证自己

流程:
  1. 从 drama_authors 按 scrape_priority 选一批 (每 2h, 每批 30 人)
  2. 对每作者调 profile/feed (复用 ks_profile_collector 的 cookie 池)
  3. 对每 photo:
     a. 基础过滤 (age > 14 天 / views < 1000 / like_ratio > 30% 明显机刷)
     b. 算派生信号 (vph / like_ratio / age)
     c. 前期不算 follow_opportunity (权重待定, Week 3+ signal_calibrator 定)
     d. UPSERT hot_photos
  4. 副产品:
     - 提 CDN → drama_links (解决 CDN 荒漠)
     - 作者数据 → 更新 drama_authors 统计
     - 新剧 caption → 扩充 drama_authors (如果是新作者推荐)

用法:
  from core.ks_trending_hunter import scan_batch
  r = scan_batch(batch_size=30)
  # → {scanned: N, photos_inserted: M, photos_updated: K, cdns_saved: L}

  # CLI 手动触发:
  python -m core.ks_trending_hunter --batch 30
  python -m core.ks_trending_hunter --author-id 3x45px2jms8czq9   # 单作者
  python -m core.ks_trending_hunter --stats                         # 看 hot_photos 健康
"""
from __future__ import annotations

import json
import logging
import re
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
    c.row_factory = sqlite3.Row
    return c


def _cfg(key: str, default):
    try:
        from core.app_config import get as _g
        return _g(key, default)
    except Exception:
        return default


# ══════════════════════════════════════════════════════════════
# 信号计算 (前期只算基础, 不做复合打分)
# ══════════════════════════════════════════════════════════════
def _compute_signals(photo: dict, now_ms: Optional[int] = None) -> dict:
    """从 photo 算派生信号. 不做 follow_opportunity (初期权重未知).

    Returns:
        {age_hours, views_per_hour, like_ratio, comment_ratio}
    """
    now_ms = now_ms or int(time.time() * 1000)
    publish_ts = photo.get("timestamp") or photo.get("publish_ts") or now_ms
    age_hours = max((now_ms - publish_ts) / 3600000.0, 0.01)

    try:
        views = int(photo.get("viewCount") or photo.get("view_count") or 0)
    except Exception:
        views = 0
    try:
        likes = int(photo.get("likeCount") or photo.get("like_count") or 0)
    except Exception:
        likes = 0
    try:
        comments = int(photo.get("commentCount") or photo.get("comment_count") or 0)
    except Exception:
        comments = 0

    vph = views / age_hours if age_hours > 0 else 0
    like_ratio = likes / max(views, 1)
    comment_ratio = comments / max(views, 1)

    return {
        "age_hours": round(age_hours, 2),
        "views_per_hour": round(vph, 1),
        "like_ratio": round(like_ratio, 5),
        "comment_ratio": round(comment_ratio, 5),
    }


# ══════════════════════════════════════════════════════════════
# 宽容过滤 (初期几乎不过滤)
# ══════════════════════════════════════════════════════════════
def _wide_filter(photo: dict, signals: dict) -> tuple[bool, str]:
    """前期只过滤明显废品. True = 入池."""
    views = int(photo.get("viewCount") or 0)
    age_h = signals["age_hours"]
    like_ratio = signals["like_ratio"]

    min_views = int(_cfg("ai.trending_hunter.wide_filter_min_views", 1000))
    max_age_h = int(_cfg("ai.trending_hunter.wide_filter_max_age_h", 336))
    max_like_ratio = float(_cfg("ai.trending_hunter.wide_filter_max_like_ratio", 0.3))

    if views < min_views:
        return False, f"views_too_low ({views}<{min_views})"
    if age_h > max_age_h:
        return False, f"too_old ({age_h:.0f}h > {max_age_h}h)"
    if like_ratio > max_like_ratio:
        return False, f"likely_fake (like_ratio={like_ratio:.1%})"
    return True, "ok"


# ══════════════════════════════════════════════════════════════
# Caption 解析 → drama_name
# ══════════════════════════════════════════════════════════════
_HASHTAG_RE = re.compile(r"#([^#\s]+)")


def _extract_drama_name(caption: str) -> Optional[str]:
    """从 caption 提 #剧名#.

    优先策略:
      1. 最长的 hashtag (大概率是剧名)
      2. 排除通用 tag (快来看短剧 / 热播 / 推荐 / lx)
      3. 若匹配 drama_banner_tasks 则取该剧名
    """
    if not caption:
        return None

    generic_tags = {"快来看短剧", "快嘴唠唠剧", "热播短剧", "短剧推荐", "短剧",
                    "追剧", "推荐", "lx", "看全集", "点击左下角"}
    tags = [t for t in _HASHTAG_RE.findall(caption) if t not in generic_tags
            and len(t) >= 3]
    if not tags:
        return None

    # 按长度 desc 找
    tags.sort(key=len, reverse=True)
    return tags[0]


# ══════════════════════════════════════════════════════════════
# hot_photos upsert
# ══════════════════════════════════════════════════════════════
def _upsert_hot_photo(photo: dict, author: dict, signals: dict,
                         source: str) -> str:
    """UPSERT 一条 hot_photos. 返 action: inserted / updated / skipped."""
    photo_id = str(photo.get("id") or photo.get("photo_id") or "")
    if not photo_id:
        return "no_photo_id"

    caption = (photo.get("caption") or "").strip()
    drama_name = _extract_drama_name(caption)

    # CDN
    cdn_url = photo.get("photoUrl") or ""
    if not cdn_url:
        urls = photo.get("photoUrls") or []
        if urls and isinstance(urls[0], dict):
            cdn_url = urls[0].get("url", "")
    cover_url = photo.get("coverUrl") or ""

    views = int(photo.get("viewCount") or 0)
    likes = int(photo.get("likeCount") or 0)
    comments = int(photo.get("commentCount") or 0)
    real_likes = int(photo.get("realLikeCount") or likes)
    duration_ms = int(photo.get("duration") or 0)
    publish_ts = int(photo.get("timestamp") or 0)

    with _connect() as c:
        existing = c.execute(
            "SELECT id, first_seen_views, resample_count FROM hot_photos WHERE photo_id=?",
            (photo_id,),
        ).fetchone()

        if existing:
            # 更新时间序列 + 最新数据
            c.execute(
                """UPDATE hot_photos SET
                    view_count = ?, like_count = ?, comment_count = ?,
                    real_like_count = ?,
                    age_hours_at_discover = COALESCE(age_hours_at_discover, ?),
                    views_per_hour = ?, like_ratio = ?, comment_ratio = ?,
                    last_seen_at = datetime('now','localtime'),
                    last_seen_views = ?, last_seen_likes = ?,
                    resample_count = resample_count + 1,
                    cdn_url = COALESCE(NULLIF(cdn_url, ''), ?),
                    cover_url = COALESCE(NULLIF(cover_url, ''), ?),
                    caption = ?, drama_name = COALESCE(drama_name, ?)
                WHERE photo_id = ?""",
                (views, likes, comments, real_likes,
                 signals["age_hours"],
                 signals["views_per_hour"], signals["like_ratio"],
                 signals["comment_ratio"],
                 views, likes,
                 cdn_url, cover_url, caption, drama_name,
                 photo_id),
            )
            c.commit()
            return "updated"

        # 新插
        c.execute(
            """INSERT INTO hot_photos
                (photo_id, author_id, author_name, caption, drama_name,
                 view_count, like_count, comment_count, real_like_count,
                 duration_ms, publish_ts,
                 age_hours_at_discover, views_per_hour, like_ratio, comment_ratio,
                 cdn_url, cover_url,
                 first_seen_views, first_seen_likes,
                 last_seen_views, last_seen_likes,
                 source, raw_json)
               VALUES (?, ?, ?, ?, ?,
                       ?, ?, ?, ?, ?, ?,
                       ?, ?, ?, ?,
                       ?, ?, ?, ?, ?, ?, ?, ?)""",
            (photo_id, author.get("id"), author.get("name"), caption, drama_name,
             views, likes, comments, real_likes, duration_ms, publish_ts,
             signals["age_hours"], signals["views_per_hour"],
             signals["like_ratio"], signals["comment_ratio"],
             cdn_url, cover_url,
             views, likes, views, likes,
             source,
             json.dumps({"photo": photo, "author": author}, ensure_ascii=False)[:5000]),
        )
        c.commit()
        return "inserted"


def _save_cdn_to_drama_links(drama_name: str, author_id: str,
                               photo_id: str, cdn_url: str, duration_ms: int) -> bool:
    """CDN 副产品存 drama_links. True = 新增, False = 已有."""
    if not (drama_name and cdn_url):
        return False
    try:
        with _connect() as c:
            exist = c.execute(
                "SELECT id FROM drama_links WHERE drama_name=? AND drama_url=?",
                (drama_name, cdn_url),
            ).fetchone()
            if exist:
                c.execute("""UPDATE drama_links SET
                    updated_at = datetime('now','localtime')
                    WHERE id=?""", (exist[0],))
                return False
            c.execute(
                """INSERT INTO drama_links
                    (drama_name, drama_url, author_id, status, source_file,
                     link_mode, verified_at, created_at, updated_at, remark,
                     duration_sec)
                   VALUES (?, ?, ?, 'active', 'trending_hunter',
                           'web_cdn',
                           datetime('now','localtime'),
                           datetime('now','localtime'),
                           datetime('now','localtime'),
                           ?, ?)""",
                (drama_name, cdn_url, author_id,
                 json.dumps({"photo_id": photo_id, "src": "trending_hunter"}),
                 int((duration_ms or 0) / 1000)),
            )
            c.commit()
            return True
    except Exception as e:
        log.debug("[hunter] save_cdn fail: %s", e)
        return False


def _upsert_author(author_id: str, author_name: str) -> bool:
    """新作者自动入 drama_authors (扩池)."""
    if not author_id:
        return False
    try:
        with _connect() as c:
            exist = c.execute(
                "SELECT id FROM drama_authors WHERE kuaishou_uid=?",
                (author_id,),
            ).fetchone()
            if exist:
                c.execute("""UPDATE drama_authors SET
                    last_scraped_at = datetime('now','localtime'),
                    nickname = COALESCE(NULLIF(?, ''), nickname)
                    WHERE id=?""", (author_name, exist[0]))
                return False
            c.execute(
                """INSERT INTO drama_authors
                    (kuaishou_uid, nickname, source, is_active,
                     scrape_priority, last_scraped_at, created_at, status)
                   VALUES (?, ?, 'trending_hunter', 1, 3,
                           datetime('now','localtime'),
                           datetime('now','localtime'),
                           'active')""",
                (author_id, author_name),
            )
            c.commit()
            return True
    except Exception as e:
        log.debug("[hunter] upsert_author fail: %s", e)
        return False


# ══════════════════════════════════════════════════════════════
# 核心: 扫一批作者
# ══════════════════════════════════════════════════════════════
def _pick_authors_to_scan(batch_size: int = 30) -> list[dict]:
    """从 drama_authors 选 batch_size 个扫. 按 priority 升序 (小优先), 老化时间长的优先."""
    with _connect() as c:
        rows = c.execute(
            """SELECT id, kuaishou_uid, nickname, scrape_priority,
                       last_scraped_at, consecutive_failures
               FROM drama_authors
               WHERE (is_active = 1 OR is_active IS NULL)
                 AND (status IS NULL OR status = 'active')
                 AND kuaishou_uid IS NOT NULL AND kuaishou_uid != ''
                 AND (consecutive_failures IS NULL OR consecutive_failures < 10)
               ORDER BY scrape_priority ASC,
                        COALESCE(last_scraped_at, '2000-01-01') ASC
               LIMIT ?""",
            (batch_size,),
        ).fetchall()
    return [dict(r) for r in rows]


def scan_author(author_id: str, author_name: str = "") -> dict:
    """扫单个作者 profile/feed, 返回统计."""
    from core.ks_profile_collector import _call_profile_feed, _generate_kww, _POOL

    stats = {"author_id": author_id, "author_name": author_name,
             "feeds_total": 0, "inserted": 0, "updated": 0,
             "skipped": 0, "cdns_saved": 0, "error": None}

    acc = _POOL.pick()
    if not acc:
        stats["error"] = "no_available_cookie"
        return stats

    kww = _generate_kww()
    log.info("[hunter] scanning author=%s (%s) via acct=%d",
              author_id, author_name, acc["id"])

    try:
        resp = _call_profile_feed(author_id, acc["cookie"], kww, pcursor="")
    except Exception as e:
        stats["error"] = f"http: {str(e)[:100]}"
        _POOL.mark_rate_limited(acc["id"], cooldown_sec=120)
        _mark_author_fail(author_id)
        return stats

    result = resp.get("result")
    if result == 1:
        feeds = resp.get("feeds") or []
        stats["feeds_total"] = len(feeds)
        _POOL.mark_success(acc["id"])
        _mark_author_success(author_id)

        author_dict = {"id": author_id, "name": author_name}

        for f in feeds:
            photo = f.get("photo") or {}
            signals = _compute_signals(photo)
            ok, reason = _wide_filter(photo, signals)
            if not ok:
                stats["skipped"] += 1
                continue

            # 真正作者信息 (快手返的可能更新)
            actual_author = f.get("author") or author_dict
            act = _upsert_hot_photo(photo, actual_author, signals, "profile_feed")
            if act == "inserted":
                stats["inserted"] += 1
            elif act == "updated":
                stats["updated"] += 1

            # 副产品: CDN
            drama_name = _extract_drama_name(photo.get("caption") or "")
            photo_url = (photo.get("photoUrl")
                         or (photo.get("photoUrls") or [{}])[0].get("url", ""))
            if drama_name and photo_url:
                if _save_cdn_to_drama_links(
                    drama_name=drama_name,
                    author_id=author_id,
                    photo_id=str(photo.get("id", "")),
                    cdn_url=photo_url,
                    duration_ms=photo.get("duration", 0),
                ):
                    stats["cdns_saved"] += 1

    elif result == 2:
        _POOL.mark_rate_limited(acc["id"])
        stats["error"] = "rate_limited"
    elif result == 109:
        _POOL.mark_invalid(acc["id"])
        stats["error"] = "cookie_expired"
    else:
        stats["error"] = f"result={result}: {resp.get('error_msg', '')[:60]}"
        _POOL.mark_rate_limited(acc["id"], cooldown_sec=120)

    return stats


def _mark_author_success(author_id: str) -> None:
    try:
        with _connect() as c:
            c.execute(
                """UPDATE drama_authors SET
                    last_success_at = datetime('now','localtime'),
                    consecutive_failures = 0
                   WHERE kuaishou_uid = ?""", (author_id,))
            c.commit()
    except Exception: pass


def _mark_author_fail(author_id: str) -> None:
    try:
        with _connect() as c:
            c.execute(
                """UPDATE drama_authors SET
                    consecutive_failures = COALESCE(consecutive_failures, 0) + 1
                   WHERE kuaishou_uid = ?""", (author_id,))
            c.commit()
    except Exception: pass


def scan_batch(batch_size: Optional[int] = None) -> dict:
    """扫一批作者. agent 每 2h 调一次."""
    batch_size = batch_size or int(_cfg("ai.trending_hunter.max_authors_per_batch", 30))

    authors = _pick_authors_to_scan(batch_size)
    if not authors:
        log.warning("[hunter] 无作者可扫 (全 consecutive_failures>=10 ?)")
        return {"scanned": 0, "photos_inserted": 0, "photos_updated": 0,
                "photos_skipped": 0, "cdns_saved": 0, "authors_ok": 0, "authors_fail": 0}

    totals = {"scanned": 0, "photos_inserted": 0, "photos_updated": 0,
              "photos_skipped": 0, "cdns_saved": 0, "authors_ok": 0,
              "authors_fail": 0, "errors": {}}

    t0 = time.time()
    for a in authors:
        r = scan_author(a["kuaishou_uid"], a.get("nickname", ""))
        totals["scanned"] += 1
        totals["photos_inserted"] += r.get("inserted", 0)
        totals["photos_updated"] += r.get("updated", 0)
        totals["photos_skipped"] += r.get("skipped", 0)
        totals["cdns_saved"] += r.get("cdns_saved", 0)
        if r.get("error"):
            totals["authors_fail"] += 1
            totals["errors"][r["error"]] = totals["errors"].get(r["error"], 0) + 1
        else:
            totals["authors_ok"] += 1
        # 每个作者之间停 0.5s (防限频)
        time.sleep(0.5)

    totals["elapsed_sec"] = round(time.time() - t0, 1)
    log.info("[hunter] batch scan done: %s", totals)
    return totals


# ══════════════════════════════════════════════════════════════
# 统计 + CLI
# ══════════════════════════════════════════════════════════════
def stats() -> dict:
    """hot_photos + drama_authors 健康."""
    with _connect() as c:
        total_photos = c.execute("SELECT COUNT(*) FROM hot_photos").fetchone()[0]
        recent_24h = c.execute(
            """SELECT COUNT(*) FROM hot_photos
               WHERE first_seen_at > datetime('now','-24 hours','localtime')"""
        ).fetchone()[0]
        unique_dramas = c.execute(
            "SELECT COUNT(DISTINCT drama_name) FROM hot_photos WHERE drama_name IS NOT NULL"
        ).fetchone()[0]
        unique_authors = c.execute(
            "SELECT COUNT(DISTINCT author_id) FROM hot_photos WHERE author_id IS NOT NULL"
        ).fetchone()[0]

        n_authors = c.execute("SELECT COUNT(*) FROM drama_authors WHERE (is_active=1 OR is_active IS NULL)").fetchone()[0]
        n_authors_fail = c.execute("SELECT COUNT(*) FROM drama_authors WHERE consecutive_failures >= 10").fetchone()[0]

        # 按 age 分布
        age_dist = dict(c.execute("""
            SELECT CASE
                WHEN age_hours_at_discover < 6 THEN '<6h'
                WHEN age_hours_at_discover < 24 THEN '6-24h'
                WHEN age_hours_at_discover < 72 THEN '24-72h'
                WHEN age_hours_at_discover < 168 THEN '3-7d'
                ELSE '>7d'
            END AS bucket, COUNT(*) FROM hot_photos GROUP BY bucket
        """).fetchall())

        # TOP vph 5 条
        top_vph = [dict(r) for r in c.execute("""
            SELECT photo_id, drama_name, author_name, views_per_hour, view_count,
                   age_hours_at_discover
            FROM hot_photos WHERE views_per_hour > 0
            ORDER BY views_per_hour DESC LIMIT 5
        """).fetchall()]

    return {
        "hot_photos_total": total_photos,
        "hot_photos_last_24h": recent_24h,
        "unique_dramas": unique_dramas,
        "unique_authors": unique_authors,
        "age_distribution": age_dist,
        "top5_vph": top_vph,
        "drama_authors_total": n_authors,
        "drama_authors_blocked": n_authors_fail,
    }


def main():
    import argparse
    ap = argparse.ArgumentParser(description="KS trending hunter — 爆款雷达")
    ap.add_argument("--batch", type=int, default=None, help="扫一批 (默认 30)")
    ap.add_argument("--author-id", help="扫单作者")
    ap.add_argument("--stats", action="store_true", help="看 hot_photos 统计")
    args = ap.parse_args()

    logging.basicConfig(level=logging.INFO,
                         format="%(asctime)s [%(levelname)s] %(message)s",
                         datefmt="%H:%M:%S")
    try: sys.stdout.reconfigure(encoding="utf-8")
    except Exception: pass

    if args.stats:
        import json as _j
        print(_j.dumps(stats(), indent=2, ensure_ascii=False))
        return

    if args.author_id:
        r = scan_author(args.author_id)
        print(json.dumps(r, indent=2, ensure_ascii=False))
        return

    r = scan_batch(batch_size=args.batch)
    print(f"\n=== 批次扫描结果 ===")
    for k, v in r.items():
        print(f"  {k}: {v}")


if __name__ == "__main__":
    main()
