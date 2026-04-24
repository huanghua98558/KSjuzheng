# -*- coding: utf-8 -*-
"""剧视频下载器 — 多 URL 重试 + MP4 完整性验证 + 失败通知.

关键能力:
  1. 一个 drama_name 可能有多个 drama_url, 按 use_count ASC 排序逐个试
  2. 每个 URL 最多重试 N 次 (默认 2, 指数退避)
  3. 下载完 ffprobe 验证视频可读 (今天 9连素材 header 损坏坑过)
  4. 全 URL 挂了 → notifier.error 通知
  5. download_cache 表记录 (drama_url, file_path, file_size)
  6. 坏 URL 标记 drama_links.status='broken', 下次跳过

使用:
    from core.downloader import download_drama
    result = download_drama("陆总今天要离婚")
    # → {ok: True, file_path: "...", drama_url: "...", n_urls_tried: 1}
    # → {ok: False, error: "all_urls_failed", n_urls_tried: 3}
"""
from __future__ import annotations

import hashlib
import logging
import os
import re
import secrets
import sqlite3
import subprocess
import time
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import requests

from core.app_config import get as cfg_get
from core.notifier import notify

log = logging.getLogger(__name__)


def _connect():
    from core.config import DB_PATH
    c = sqlite3.connect(DB_PATH, timeout=30)
    c.execute("PRAGMA busy_timeout=30000")
    c.execute("PRAGMA journal_mode=WAL")
    c.execute("PRAGMA synchronous=NORMAL")
    c.row_factory = sqlite3.Row
    return c


def _get_ffmpeg_exe() -> str:
    """拿 ffmpeg 路径 — 优先用 KS184 的 (已验证可用)."""
    ks184_ffmpeg = r"C:\Program Files\kuaishou2\KS184.7z\KS184\tools\ffmpeg\bin\ffmpeg.exe"
    if os.path.isfile(ks184_ffmpeg):
        return ks184_ffmpeg
    try:
        from core.config import FFMPEG_EXE
        return FFMPEG_EXE
    except Exception:
        return "ffmpeg"


def verify_mp4(path: str | Path) -> tuple[bool, str]:
    """用 ffmpeg probe 验证视频文件可读. 返回 (ok, 信息).

    今天踩过的坑: D:\\9连素材\\*_processed.mp4 header 损坏
    ffmpeg 报 "stream 0, contradictionary STSC and STCO"
    所以必须在上传前验证.
    """
    path = str(path)
    if not os.path.isfile(path):
        return False, "file_not_exists"
    size = os.path.getsize(path)
    if size < 1024:
        return False, f"too_small_{size}B"

    ffmpeg = _get_ffmpeg_exe()
    try:
        r = subprocess.run(
            [ffmpeg, "-v", "error", "-i", path, "-t", "0.1", "-f", "null", "-"],
            capture_output=True, text=True, timeout=15,
            encoding="utf-8", errors="replace",
        )
        err = (r.stderr or "").strip()
        if r.returncode != 0 or any(k in err for k in
                                    ("Error", "Invalid", "contradictionary",
                                     "corrupt", "unspecified")):
            first_err = err.split("\n")[0][:200] if err else "unknown"
            return False, f"invalid: {first_err}"

        # 取 duration (secondary)
        r2 = subprocess.run(
            [ffmpeg, "-i", path, "-t", "0.1", "-f", "null", "-"],
            capture_output=True, text=True, timeout=10,
            encoding="utf-8", errors="replace",
        )
        m = re.search(r"Duration:\s*(\d+:\d+:\d+\.\d+)", r2.stderr or "")
        dur = m.group(1) if m else "unknown"
        return True, f"ok size={size//1024}KB dur={dur}"
    except subprocess.TimeoutExpired:
        return False, "ffprobe_timeout"
    except Exception as e:
        return False, f"probe_error: {e}"


def _url_use_count(conn: sqlite3.Connection, url: str) -> int:
    r = conn.execute(
        "SELECT use_count FROM drama_links WHERE drama_url=?", (url,)
    ).fetchone()
    return (r["use_count"] or 0) if r else 0


def _cover_url_for(conn: sqlite3.Connection, drama_url: str) -> str | None:
    """从 drama_links.remark 里提 cover_url (collector_on_demand 存的)."""
    r = conn.execute(
        "SELECT remark FROM drama_links WHERE drama_url=?", (drama_url,)
    ).fetchone()
    if not r or not r["remark"]:
        return None
    try:
        import json
        meta = json.loads(r["remark"])
        return meta.get("cover_url") or None
    except Exception:
        return None


def _candidate_urls(conn: sqlite3.Connection, drama_name: str) -> list[str]:
    """取这个 drama 的所有 URL, 按 use_count ASC (少用的先试) + status != broken.

    ★ 2026-04-22 §27 架构重排 (用户铁令):
       "完整流程是要系统每次发布都是实时服务器获取链接并开始下载.
        我们本地的数据库作为长期备份的存在."

    新优先级:
      Layer 1  MCN wait_collect_videos 实时查 (KS184 高转化池, 53% CDN 直链)  ← 主路
      Layer 2  MCN kuaishou_urls 实时查 (1.8M 短链池, 同上实时)                ← 主路
      Layer 3  本地 drama_links (历史累积 CDN, 仍有效的)                        ← 备份
      Layer 4  本地 mcn_url_pool (上次同步的 kuaishou_urls 镜像)                 ← 备份

    MCN 熔断 / 空返 → 自动 fallback 到 Layer 3+4 (维持旧行为).

    ★ 2026-04-20 step① v29: 返回前自动 refresh 过期 URL (age > 6h).
    ★ 2026-04-21 Top 3: 排除 quarantined_at 拉黑 URL (连续 5+ 失败).
    ★ 2026-04-22 §26: drama_links 耗尽时自动从 mcn_url_pool (181万) 补充.
    """
    realtime_first = cfg_get("ai.url_source.realtime_enabled", True)
    realtime_urls: list[str] = []

    # ── Layer 1+2: MCN 实时双源 (主路) ──
    if realtime_first:
        try:
            from core.mcn_url_realtime import fetch_urls_realtime
            rt_rows = fetch_urls_realtime(drama_name)
            # rt_rows 已按 CDN 优先排序
            realtime_urls = [r["url"] for r in rt_rows]
            if realtime_urls:
                log.info("[downloader] drama=%r MCN realtime: %d urls (%d CDN) ★ 主路",
                          drama_name,
                          len(realtime_urls),
                          sum(1 for r in rt_rows if r["is_cdn"]))
        except Exception as e:
            log.warning("[downloader] MCN realtime failed (fallback to local): %s", e)

    # 刷新本地 stale URL
    try:
        _refresh_stale_urls(conn, drama_name)
    except Exception as e:
        log.debug("[downloader] refresh_stale_urls failed (non-fatal): %s", e)

    # ── Layer 3: 本地 drama_links (备份, 排除 broken/blocked/quarantined) ──
    quarantine_days = int(cfg_get("ai.url_health.quarantine_days", 7))
    rows = conn.execute(
        f"""SELECT drama_url, use_count, status
           FROM drama_links
           WHERE drama_name = ?
             AND (status IS NULL OR status NOT IN ('broken', 'blocked'))
             AND drama_url IS NOT NULL AND drama_url != ''
             AND (quarantined_at IS NULL
                  OR (julianday('now') - julianday(quarantined_at)) > {quarantine_days})
           ORDER BY COALESCE(use_count, 0) ASC""",
        (drama_name,),
    ).fetchall()
    local_urls = [r["drama_url"] for r in rows]

    # ── Layer 4: mcn_url_pool 本地备份 (仅主路+Layer3 不够时) ──
    if cfg_get("ai.url_health.pool_fallback_enabled", True):
        pool_top = int(cfg_get("ai.url_health.pool_fallback_top_n", 10))
        try:
            from core.drama_pool import pick_share_urls
            pool_urls = pick_share_urls(
                drama_name, limit=pool_top, prefer_cdn=False, exclude_hosts=[],
            )
            local_set = set(local_urls)
            pool_new = [u for u in pool_urls if u not in local_set]
            if pool_new:
                local_urls.extend(pool_new)
        except Exception as e:
            log.debug("[downloader] mcn_url_pool fallback failed: %s", e)

    # ── 合并: realtime 主路 → 本地备份 (去重) ──
    seen = set()
    merged: list[str] = []
    for u in realtime_urls + local_urls:
        if u and u not in seen:
            seen.add(u)
            merged.append(u)

    if realtime_urls and local_urls:
        log.info("[downloader] drama=%r merged: realtime=%d + local=%d → %d unique",
                  drama_name, len(realtime_urls), len(local_urls), len(merged))

    # ★ 2026-04-24 v6 Day 8: Layer 0.5 — 如果全是短链无 CDN, 实时调 KS184 profile 采集
    # 2026-04-17 起快手短链反爬升级, 短链 100% 限流. profile/feed + graphql
    # 通路仍活 (实测 2026-04-24). 按需采集能补 CDN, 避免 dead_letter.
    def _is_cdn(u: str) -> bool:
        u = u.lower()
        return any(x in u for x in ("djvod", "kwaicdn", "ndcimgs", ".mp4"))

    cdn_count = sum(1 for u in merged if _is_cdn(u))
    if cdn_count == 0 and cfg_get("ai.profile_collector.on_demand_enabled", True):
        log.warning("[downloader] drama=%r 全短链 0 CDN, 走 KS184 profile 采集", drama_name)
        try:
            from core.ks_profile_collector import collect_for_drama
            cdns = collect_for_drama(drama_name, max_retries=5)
            new_cdn_urls = []
            for c in cdns:
                u = c.get("url")
                if u and u not in seen and _is_cdn(u):
                    new_cdn_urls.append(u)
                    seen.add(u)
            if new_cdn_urls:
                # CDN 直链插最前面 (优先下)
                merged = new_cdn_urls + merged
                log.info("[downloader] ✅ drama=%r profile 采集补充 %d 条 CDN",
                          drama_name, len(new_cdn_urls))
            else:
                log.warning("[downloader] profile 采集也无 CDN (可能剧凉了 / 作者删视频)")
        except Exception as e:
            log.warning("[downloader] profile 采集失败 (non-fatal): %s", e)

    return merged


def _get_healthy_account_pool(conn: sqlite3.Connection,
                                pool_size: int = 5) -> list[int]:
    """★ 2026-04-21 Top 3: 获取健康账号池 (替代 browser_account_pk=3 写死).

    筛选条件:
      - login_status = 'logged_in' 或 'ok'
      - tier != 'frozen'
      - cookies 非空
      - cookie_last_success_at 近 24h 内 (证明 cookie 活)
    排序: cookie_last_success_at DESC (最新鲜优先)
    """
    try:
        rs = conn.execute("""
            SELECT id FROM device_accounts
            WHERE login_status IN ('logged_in', 'ok')
              AND (tier IS NULL OR tier != 'frozen')
              AND cookies IS NOT NULL AND cookies != ''
              AND (cookie_last_success_at IS NULL
                   OR (julianday('now') - julianday(cookie_last_success_at)) < 1.0)
            ORDER BY
              CASE WHEN cookie_last_success_at IS NULL THEN 1 ELSE 0 END,
              cookie_last_success_at DESC
            LIMIT ?
        """, (pool_size,)).fetchall()
        pool = [r[0] for r in rs]
        if not pool:
            # fallback: 宽松条件
            rs = conn.execute("""
                SELECT id FROM device_accounts
                WHERE login_status IN ('logged_in', 'ok')
                  AND cookies IS NOT NULL AND cookies != ''
                ORDER BY id
                LIMIT ?
            """, (pool_size,)).fetchall()
            pool = [r[0] for r in rs]
        return pool
    except Exception as e:
        log.warning("[downloader] _get_healthy_account_pool failed: %s", e)
        return []


def _refresh_stale_urls(conn: sqlite3.Connection, drama_name: str) -> int:
    """★ 2026-04-20 step①: 下载前自动 refresh 过期 URL.
    ★ 2026-04-21 Top 3: 账号池轮换 (不再钉死 pk=3) + refresh_attempts 日志.

    对 drama_links 中 url_resolved_at > cfg.refresh_hours (6h) 且有
    photo_encrypt_id + author_id 的行, 重新 fetch_profile_feed 拿**新鲜**
    CDN 直链. 成功 → 更新 drama_url + url_resolved_at + last_success_at;
    失败 → 标 broken + 累加 fail_count.

    每个 URL 最多试 N 个账号 cookie, 第一个成功就返回.
    """
    refresh_hours = int(cfg_get("downloader.url_refresh_hours", 6))
    if refresh_hours <= 0:
        return 0
    rs = conn.execute(
        """SELECT id, photo_encrypt_id, author_id, url_resolved_at, fail_count
           FROM drama_links
           WHERE drama_name = ?
             AND (status IS NULL OR status='pending')
             AND quarantined_at IS NULL                          -- 拉黑的不刷
             AND photo_encrypt_id IS NOT NULL AND photo_encrypt_id != ''
             AND author_id IS NOT NULL AND author_id != ''
             AND (url_resolved_at IS NULL
                  OR (julianday('now') - julianday(url_resolved_at)) * 24 > ?)""",
        (drama_name, refresh_hours),
    ).fetchall()
    if not rs:
        return 0
    log.info("[downloader] '%s' %d row(s) need URL refresh (> %dh old)",
             drama_name, len(rs), refresh_hours)

    # ★ 健康账号池 (轮换用)
    pool_size = int(cfg_get("ai.url_health.refresh_pool_size", 5))
    max_retry = int(cfg_get("ai.url_health.refresh_max_retry", 3))
    account_pool = _get_healthy_account_pool(conn, pool_size=pool_size)
    if not account_pool:
        # 兜底: 老逻辑 pk=3
        account_pool = [int(cfg_get("collector.on_demand.browser_account_pk", 3))]
    log.info("[downloader][refresh] account pool: %s (max %d retry/url)",
             account_pool, max_retry)

    try:
        from core.drama_collector import DramaCollector
        from core.db_manager import DBManager
        from core.cookie_manager import CookieManager
        db = DBManager()
        cm = CookieManager(db)
        coll = DramaCollector(db, cm)
    except Exception as e:
        log.warning("[downloader] can't init collector for refresh: %s", e)
        return 0

    import json as _json
    from datetime import datetime, timezone
    now = datetime.now(timezone.utc).isoformat()
    refreshed = 0

    # group by author_id
    by_author: dict[str, list] = {}
    for r in rs:
        by_author.setdefault(r["author_id"], []).append(r)

    for aid, rows in by_author.items():
        # 为此 author 逐账号试, 直到拿到 feed
        feeds = []
        attempts_log = []
        for i, acc_pk in enumerate(account_pool[:max_retry]):
            try:
                feeds = coll.fetch_profile_feed(aid, browser_account_pk=acc_pk,
                                                  max_pages=1)
                if feeds:
                    attempts_log.append({
                        "account_pk": acc_pk, "ok": True, "feed_count": len(feeds),
                        "ts": now,
                    })
                    log.info("[refresh] author=%s via acc_pk=%d → %d feeds",
                             aid[:10], acc_pk, len(feeds))
                    break
                else:
                    attempts_log.append({
                        "account_pk": acc_pk, "ok": False, "reason": "empty_feed",
                        "ts": now,
                    })
            except Exception as e:
                attempts_log.append({
                    "account_pk": acc_pk, "ok": False, "reason": str(e)[:100],
                    "ts": now,
                })
                log.warning("[refresh] acc_pk=%d author=%s failed: %s",
                            acc_pk, aid[:10], e)
                continue

        # 更新每条 drama_link
        fresh_map = {}
        for f in feeds:
            pid = f.get("photo_encrypt_id")
            raw_photo = (f.get("raw") or {}).get("photo") or {}
            photo_urls = raw_photo.get("photoUrls") or []
            for pu in photo_urls:
                if isinstance(pu, dict) and pu.get("url"):
                    fresh_map[pid] = pu["url"]
                    break

        for r in rows:
            pid = r["photo_encrypt_id"]
            fresh = fresh_map.get(pid)
            if fresh:
                conn.execute(
                    """UPDATE drama_links
                       SET drama_url=?, url_resolved_at=?,
                           status='pending', verified_at=NULL,
                           last_success_at=?, fail_count=0,
                           refresh_attempts_json=?,
                           updated_at=?,
                           remark=COALESCE(remark,'')||' [refreshed]'
                       WHERE id=?""",
                    (fresh, now, now, _json.dumps(attempts_log, ensure_ascii=False),
                     now, r["id"]),
                )
                refreshed += 1
            else:
                # 全池账号都没拿到这 photo_id → fail_count++ + 检查 quarantine
                cur_fails = (r["fail_count"] or 0) + 1
                threshold = int(cfg_get("ai.url_health.quarantine_threshold", 5))
                if cur_fails >= threshold:
                    conn.execute(
                        """UPDATE drama_links
                           SET status='broken',
                               fail_count=?,
                               quarantined_at=?,
                               refresh_attempts_json=?,
                               updated_at=?
                           WHERE id=?""",
                        (cur_fails, now,
                         _json.dumps(attempts_log, ensure_ascii=False),
                         now, r["id"]),
                    )
                    log.warning("[refresh] 🚫 QUARANTINE id=%s '%s' fail_count=%d",
                                r["id"], drama_name, cur_fails)
                else:
                    conn.execute(
                        """UPDATE drama_links
                           SET status='broken',
                               fail_count=?,
                               refresh_attempts_json=?,
                               updated_at=?
                           WHERE id=?""",
                        (cur_fails,
                         _json.dumps(attempts_log, ensure_ascii=False),
                         now, r["id"]),
                    )
    conn.commit()
    if refreshed:
        log.info("[downloader] ★ refreshed %d URLs for '%s' (pool rotation)",
                 refreshed, drama_name)
    return refreshed


def _ensure_url_in_drama_links(conn: sqlite3.Connection, url: str,
                                  drama_name: str | None = None,
                                  source: str = "mcn_url_pool") -> None:
    """★ 2026-04-22 §26: URL 从 mcn_url_pool 补上来时, 自动 INSERT 到 drama_links,
    这样 mark_url_success/_broken 才能跟踪健康度. 幂等, 已存在不动."""
    try:
        exists = conn.execute(
            "SELECT 1 FROM drama_links WHERE drama_url=? LIMIT 1", (url,),
        ).fetchone()
        if exists: return
        # 从 mcn_url_pool 反查 drama_name (若调用方没传)
        if not drama_name:
            row = conn.execute(
                "SELECT name FROM mcn_url_pool WHERE url=? LIMIT 1", (url,),
            ).fetchone()
            drama_name = row[0] if row else "unknown"
        conn.execute(
            """INSERT OR IGNORE INTO drama_links
                (drama_name, drama_url, source_file, status, link_mode,
                 fail_count, use_count)
               VALUES (?, ?, ?, 'pending', 'drama', 0, 0)""",
            (drama_name, url, source),
        )
        conn.commit()
    except Exception:
        pass


def _mark_url_broken(conn: sqlite3.Connection, url: str, reason: str) -> None:
    """★ 2026-04-21 Top 3: 累加 fail_count, 达阈值自动 quarantine."""
    try:
        # ★ 2026-04-22 §26: 先确保 URL 在 drama_links (mcn_url_pool 补的)
        _ensure_url_in_drama_links(conn, url)

        threshold = int(cfg_get("ai.url_health.quarantine_threshold", 5))
        # 先读当前 fail_count
        row = conn.execute(
            "SELECT fail_count FROM drama_links WHERE drama_url=? LIMIT 1",
            (url,),
        ).fetchone()
        cur_fails = (row[0] if row and row[0] else 0) + 1
        if cur_fails >= threshold:
            # quarantine — 设 quarantined_at, 后续 refresh / planner 都跳过
            conn.execute(
                """UPDATE drama_links
                   SET status='broken',
                       fail_count=?,
                       quarantined_at=datetime('now','localtime'),
                       updated_at=datetime('now','localtime'),
                       remark=COALESCE(remark,'') || ' [QUARANTINED: ' || ? || ']'
                   WHERE drama_url=?""",
                (cur_fails, reason[:80], url),
            )
            log.warning("[downloader] 🚫 QUARANTINE url (fail_count=%d ≥ %d): %s",
                        cur_fails, threshold, url[:60])
        else:
            conn.execute(
                """UPDATE drama_links
                   SET status='broken',
                       fail_count=?,
                       updated_at=datetime('now','localtime'),
                       remark=COALESCE(remark,'') || ' [broken: ' || ? || ']'
                   WHERE drama_url=?""",
                (cur_fails, reason[:100], url),
            )
        conn.commit()
    except Exception:
        pass


def _mark_url_success(conn: sqlite3.Connection, url: str,
                        drama_name: str | None = None) -> None:
    """★ 2026-04-21 Top 3: 下载成功 → 清零 fail_count + 更新 last_success_at.
    ★ 2026-04-22 §26: URL 不在 drama_links 时自动 INSERT (从 mcn_url_pool 补的)."""
    try:
        _ensure_url_in_drama_links(conn, url, drama_name)
        conn.execute(
            """UPDATE drama_links
               SET last_success_at=datetime('now','localtime'),
                   fail_count=0,
                   status='pending',
                   updated_at=datetime('now','localtime')
               WHERE drama_url=?""",
            (url,),
        )
        conn.commit()
    except Exception:
        pass


def _bump_url_use(conn: sqlite3.Connection, url: str,
                   drama_name: str | None = None) -> None:
    try:
        _ensure_url_in_drama_links(conn, url, drama_name)
        conn.execute(
            """UPDATE drama_links SET
                 use_count = COALESCE(use_count, 0) + 1,
                 last_used_at = datetime('now','localtime')
               WHERE drama_url=?""",
            (url,),
        )
        conn.commit()
    except Exception:
        pass


def _cache_download(conn: sqlite3.Connection, url: str, file_path: str,
                    file_size: int) -> None:
    """写/更新 download_cache."""
    url_hash = hashlib.md5(url.encode("utf-8")).hexdigest()
    try:
        conn.execute(
            """INSERT INTO download_cache
                 (drama_url, drama_url_hash, cache_type, file_path, file_size,
                  created_time, last_used_time, use_count)
               VALUES (?, ?, 'video', ?, ?, datetime('now','localtime'),
                       datetime('now','localtime'), 1)
               ON CONFLICT(drama_url_hash) DO UPDATE SET
                 file_path=excluded.file_path,
                 file_size=excluded.file_size,
                 last_used_time=datetime('now','localtime'),
                 use_count=use_count+1""",
            (url, url_hash, file_path, file_size),
        )
        conn.commit()
    except Exception as e:
        log.debug("[downloader] cache write failed: %s", e)


# ═══════════════════════════════════════════════════════════════
# ★ 2026-04-21 跨账号视频复用 (KS184 同款)
# 13 账号发同剧时, 只下 1 次, copy 13 份, 每份末尾追加 17 随机字节改 MD5.
# 带宽消耗: 13 次 HTTP → 1 次 (省 92%).
# 处理成本: 13 次全量下载 (~10 分钟) → 1 次下载 + 13 次文件 copy (~30 秒).
# ═══════════════════════════════════════════════════════════════

def _try_cache_hit(
    urls: list[str],
    out_dir: Path,
    drama_name: str = "",
) -> dict[str, Any] | None:
    """在 download_cache 查任一 URL. 命中 → copy 到新路径 + bump use_count + 返回.

    为什么要 copy: Stage 1.5 MD5 modifier 会往文件末尾追加随机字节,
    如果直接用缓存文件, 后续任务读到的是已被改过的文件 (累加坏掉).
    所以每次 cache hit 先 copy 到任务专属路径, MD5 改只动 copy.

    Args:
        urls: 候选 URL 列表
        out_dir: 任务输出目录
        drama_name: 剧名 (日志用)

    Returns:
        dict (同 download_drama 格式) 或 None (未命中)
    """
    import shutil

    with _connect() as conn:
        for url in urls:
            url_hash = hashlib.md5(url.encode("utf-8")).hexdigest()
            row = conn.execute(
                """SELECT file_path, file_size, use_count, created_time
                   FROM download_cache
                   WHERE drama_url_hash=? AND cache_type='video'""",
                (url_hash,),
            ).fetchone()
            if not row:
                continue
            src_path, src_size, use_count, created_time = row
            src = Path(src_path)
            # 源文件已删 / 大小不一致 → 跳过此条, 删掉 cache row 下次重下
            if not src.exists():
                log.info("[downloader][cache] file missing, purge: %s", src)
                conn.execute(
                    "DELETE FROM download_cache WHERE drama_url_hash=?",
                    (url_hash,),
                )
                conn.commit()
                continue
            try:
                actual_size = src.stat().st_size
            except Exception:
                continue
            # size 不一致说明文件损坏
            if src_size and abs(actual_size - src_size) > 1024:
                log.warning("[downloader][cache] size mismatch src=%s cache=%s, purge",
                            actual_size, src_size)
                conn.execute(
                    "DELETE FROM download_cache WHERE drama_url_hash=?",
                    (url_hash,),
                )
                conn.commit()
                continue
            # 太小 (< 100KB) 可能是错误 HTML → 跳过
            if actual_size < 100 * 1024:
                log.warning("[downloader][cache] file too small %sB, skip", actual_size)
                continue

            # ★ 命中 — copy 到新任务专属路径
            safe_hash = url_hash[:8]
            stamp = time.strftime("%Y%m%d_%H%M%S")
            rand = secrets.token_hex(3)
            target = out_dir / f"{safe_hash}_{stamp}_{rand}.mp4"
            try:
                shutil.copy2(src, target)
            except Exception as e:
                log.warning("[downloader][cache] copy failed %s → %s: %s", src, target, e)
                continue

            # bump use_count + last_used_time + 标 URL 健康
            try:
                conn.execute(
                    """UPDATE download_cache
                       SET use_count = COALESCE(use_count,0) + 1,
                           last_used_time = datetime('now','localtime')
                       WHERE drama_url_hash=?""",
                    (url_hash,),
                )
                _bump_url_use(conn, url)
                _mark_url_success(conn, url)   # ★ 2026-04-21 Top 3: cache hit 也算 URL 健康
                conn.commit()
            except Exception:
                pass

            # cover_url 也从 drama_links 取
            cover_url_found = _cover_url_for(conn, url)

            log.info(
                "[downloader][cache] ✅ HIT '%s' use=%s src=%s → %s (%.1fMB)",
                drama_name, (use_count or 0) + 1, src.name, target.name,
                actual_size / 1024 / 1024,
            )
            return {
                "ok": True,
                "file_path": str(target),
                "drama_url": url,
                "cover_url": cover_url_found,
                "n_urls_tried": 0,    # 0 表示没真下
                "verify_info": "cache_hit",
                "size": actual_size,
                "cache_hit": True,
                "cache_use_count": (use_count or 0) + 1,
                "cache_source": str(src),
            }
    # 全未命中
    return None


def _extract_cdn_url_from_share_page(share_url: str,
                                      cookie_str: str = "",
                                      timeout: int = 15) -> str | None:
    """从 kuaishou.com/f/<token> 短链页面 HTML 里提 CDN 视频 URL.

    快手分享页 SSR HTML 里嵌 JSON (window.__APOLLO_STATE__ 或
    window.__INITIAL_STATE__), 含 photoUrl/playUrl/srcNoMark 字段.

    ★ KS184 Frida (2026-04-21 §23.2 #2) 铁证:
       `www.kuaishou.com/f/X{token}` 返 `result=2` **限流** 100%,
       KS184 自动 fallback 到 `az1-api.ksapisrv.com/rest/n/xinhui/share/getSharePhotoId`
       (iOS H5 API) 100% 成功. 但 xinhui 需客户端签 `sig=` (MD5), 未破解.
       目前我们走**HTML SSR 直抓**路径 (未限流时 OK, 限流时会返 result=2).
       P2 TODO: Frida hook xinhui `sig=` 签名算法 → 替代 HTML 路径.

    返回直接可下载的 mp4 CDN URL (通常是 *.yximgs.com/...).
    """
    headers = {
        "User-Agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                       "AppleWebKit/537.36 (KHTML, like Gecko) "
                       "Chrome/120.0.0.0 Safari/537.36"),
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "zh-CN,zh;q=0.9",
    }
    if cookie_str:
        headers["Cookie"] = cookie_str
    try:
        r = requests.get(share_url, headers=headers, timeout=timeout,
                         allow_redirects=True)
        html = r.text
        # 检测限流早退: result=2 说明我们被 www.kuaishou.com 反爬限流
        if '"result":2' in html[:500] or '"result": 2' in html[:500]:
            log.warning(
                "[downloader] ⚠ share page RATE-LIMITED (result=2): %s — "
                "KS184 在此处 fallback 到 xinhui H5 API, 我们暂无 sig 算法; "
                "触发 drama URL 冷却规则让别处 resolve",
                share_url[:80],
            )
            # 触发 healing 规则让系统知道限流了 (healing 可标 drama cooldown)
            try:
                import sqlite3
                from core.config import DB_PATH as _DBP
                _c = sqlite3.connect(_DBP, timeout=5)
                _c.execute("PRAGMA busy_timeout=5000")
                _c.execute(
                    """INSERT INTO healing_diagnoses
                        (cycle_id, playbook_code, severity, matched_pattern,
                         task_id, metadata, created_at, auto_resolved)
                       VALUES (?, ?, 'warning', ?, NULL, ?,
                               datetime('now','localtime'), 0)""",
                    (
                        f"inline_downloader_{int(__import__('time').time())}",
                        "kuaishou_short_link_rate_limited",
                        'share_page_result_2',
                        __import__('json').dumps({"share_url": share_url[:200]}, ensure_ascii=False),
                    ),
                )
                _c.commit()
                _c.close()
            except Exception:
                pass
            return None
        # 按优先级找各种 playUrl 字段 (无 mark 的优先)
        patterns = [
            r'"srcNoMark"\s*:\s*"([^"]+)"',          # 无水印
            r'"photoUrl"\s*:\s*"([^"]+)"',
            r'"playUrl"\s*:\s*"([^"]+)"',
            r'"mainMvUrls?"[^\]]*"url"\s*:\s*"([^"]+)"',
            r'"url"\s*:\s*"(https?://[^"]+\.mp4[^"]*)"',
        ]
        for pat in patterns:
            for m in re.finditer(pat, html):
                url = m.group(1).replace("\\u002F", "/").replace("\\/", "/")
                if "yximgs.com" in url or "ksyun" in url or ".mp4" in url:
                    return url
        return None
    except Exception as exc:
        log.debug("[downloader] extract_cdn err: %s", exc)
        return None


def _extract_share_id_from_page(share_url: str, cookie_str: str = "",
                                  timeout: int = 10) -> tuple[str | None, str | None]:
    """从 www.kuaishou.com/f/<token> 首次 HTML 响应里提取 shareId + encryptPid.

    HTML (即使限流时) 通常仍含 `"shareId":"...","encryptPid":"..."` JSON fragment.
    拿到这两个值后, 就能走 xinhui_resolver 绕过限流.

    Returns (share_id, encrypt_pid), 任一为 None 表示未解析到.
    """
    try:
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
            "Accept-Language": "zh-CN,zh;q=0.9",
        }
        if cookie_str: headers["Cookie"] = cookie_str
        r = requests.get(share_url, headers=headers, timeout=timeout, allow_redirects=True)
        html = r.text
        sid_m = re.search(r'"shareId"\s*:\s*"(\d+)"', html)
        epid_m = re.search(r'"encryptPid"\s*:\s*"([^"]+)"', html)
        sid = sid_m.group(1) if sid_m else None
        epid = epid_m.group(1) if epid_m else None
        return sid, epid
    except Exception as e:
        log.debug("[downloader] _extract_share_id err: %s", e)
        return None, None


def _resolve_via_xinhui(share_url: str, cookie_str: str = "") -> str | None:
    """通过 xinhui API 解析短链 → CDN URL (当 HTML SSR 限流时 fallback).

    CLAUDE.md §25 (2026-04-22): sig 算法完整破解 (salt='23caab00356c').
    xinhui 返 sharePhotoId + feedInject, 需再调 feed/selection 拿 CDN URL.
    但 feed/selection 需 MCN :50002 代签 (§23), 我们通过 SigService 可调.
    """
    try:
        from core.xinhui_resolver import resolve_share
    except ImportError:
        return None
    # Step 1: 从 HTML 拿 shareId + encryptPid
    share_id, encrypt_pid = _extract_share_id_from_page(share_url, cookie_str=cookie_str)
    if not share_id:
        log.debug("[downloader] xinhui fallback: HTML 未含 shareId, 跳过")
        return None
    # Step 2: 调 xinhui
    info = resolve_share(share_id, encrypt_pid or "")
    if not info:
        log.debug("[downloader] xinhui fallback: API 拒绝 (result!=1)")
        return None
    # xinhui 只返 sharePhotoId, 不返 CDN URL. 需进一步 feed/selection.
    # 但 feed/selection 需 clientRealReportData (我们没), 走 MCN :50002 代签.
    # 暂时只把 sharePhotoId 存下, 实际 CDN 仍需别处获取.
    log.info("[downloader] xinhui OK: shareId=%s → sharePhotoId=%s",
              share_id, info.get("sharePhotoId"))
    # TODO: 配合 MCN :50002 代签 feed/selection 完成 CDN URL 解析
    return None  # 暂不返 CDN, 等接入 feed/selection 代签后补


def _resolve_to_cdn(url: str) -> str:
    """如果 url 是 kuaishou.com 短链/页面, 解析成真 CDN mp4 URL. 否则原样返回."""
    low = url.lower()
    # 已经是 CDN 直链
    if any(d in low for d in ("yximgs.com", "ksyun.com", "kwaicdn.com",
                                "djvod.ndcimgs.com", ".mp4?", "kwaizt.com")):
        return url
    # 短链 / 分享页 / short-video 页 → 去解析
    if any(p in low for p in ("kuaishou.com/f/", "kuaishou.com/short-video/",
                                "v.kuaishou.com/", "/u/")):
        # 用账号 3 的 main 域 cookie 试 (后台任务时)
        cookie_str = ""
        try:
            from core.cookie_manager import CookieManager
            from core.db_manager import DBManager
            db = DBManager()
            cm = CookieManager(db)
            browser_pk = cfg_get("collector.on_demand.browser_account_pk", 3)
            cookie_str = cm.get_cookie_string(browser_pk, domain="all") or ""
        except Exception:
            pass

        # Primary: HTML SSR 直抓 playUrl
        cdn = _extract_cdn_url_from_share_page(url, cookie_str=cookie_str)
        if cdn:
            log.info("[downloader] 短链 → CDN (HTML): %s → %s", url[:60], cdn[:80])
            return cdn

        # Fallback: xinhui API (限流时 HTML 无 playUrl, 用 xinhui 拿 sharePhotoId)
        # CLAUDE.md §25 算法破解完成, 但需要 MCN :50002 代签 feed/selection 才能拿 CDN
        xinhui_cdn = _resolve_via_xinhui(url, cookie_str=cookie_str)
        if xinhui_cdn:
            log.info("[downloader] 短链 → CDN (xinhui): %s → %s", url[:60], xinhui_cdn[:80])
            return xinhui_cdn
    return url


def _is_hls_url(url: str) -> bool:
    """HLS m3u8 流识别 (KS184 真实下载入口).

    KS184 抓包见: URL 含 /bs3/video-hls/ 或 .m3u8 就要走 N_m3u8DL-RE.
    """
    low = url.lower()
    return (".m3u8" in low or "/video-hls/" in low or
            "hlsb" in low or "hlsa" in low)


def _get_n_m3u8dl_path() -> str | None:
    """N_m3u8DL-RE.exe 路径 — 优先项目副本, 其次 KS184 原路径."""
    for p in [
        r"D:\ks_automation\tools\m3u8dl\N_m3u8DL-RE.exe",
        r"C:\Program Files\kuaishou2\KS184.7z\KS184\tools\ffmpeg\bin\N_m3u8DL-RE.exe",
    ]:
        if os.path.isfile(p):
            return p
    return None


def _get_ffmpeg_bin_xin() -> str:
    """KS184 用的 bin-xin/ffmpeg.exe (有些版本/filter 差异, 保持一致)."""
    for p in [
        r"C:\Program Files\kuaishou2\KS184.7z\KS184\tools\ffmpeg\bin-xin\ffmpeg.exe",
        r"D:\ks_automation\tools\m3u8dl\ffmpeg.exe",
    ]:
        if os.path.isfile(p):
            return p
    return _get_ffmpeg_exe()


def _download_hls(url: str, target_path: Path, timeout: int | None = None) -> tuple[bool, str]:
    """用 N_m3u8DL-RE.exe 下载 HLS 流, 自动合并成 mp4.

    完全对齐 KS184 抓包的命令行:
        N_m3u8DL-RE.exe <m3u8_url>
            --save-dir <dir>
            --save-name <filename_no_ext>
            -mt --thread-count 16
            --ffmpeg-binary-path <ffmpeg.exe>

    ★ 2026-04-21: timeout + thread_count 改 app_config 可配
    """
    if timeout is None:
        timeout = int(cfg_get("download.hls.timeout_sec", 600))
    thread_count = int(cfg_get("download.hls.thread_count", 16))

    exe = _get_n_m3u8dl_path()
    if not exe:
        return False, "N_m3u8DL-RE.exe not found"

    save_dir = target_path.parent
    save_name = target_path.stem   # 不含 .mp4
    save_dir.mkdir(parents=True, exist_ok=True)

    cmd = [
        exe, url,
        "--save-dir", str(save_dir),
        "--save-name", save_name,
        "-mt", "--thread-count", str(thread_count),
        "--ffmpeg-binary-path", _get_ffmpeg_bin_xin(),
        # 静默额外交互
        "--auto-select",   # 自动选最好码率
        "--log-level", "WARN",
    ]
    try:
        log.info("[downloader] HLS: N_m3u8DL-RE %s...", url[:80])
        r = subprocess.run(cmd, capture_output=True, text=True,
                           timeout=timeout, encoding="utf-8", errors="replace")
        if r.returncode != 0:
            err = (r.stderr or r.stdout or "")[:300]
            return False, f"N_m3u8DL_rc={r.returncode}: {err}"

        # 找输出文件 — N_m3u8DL 可能输出 .mp4 或 .ts
        for cand in [target_path, target_path.with_suffix(".ts"),
                      target_path.with_suffix(".mkv")]:
            if cand.exists() and cand.stat().st_size > 1024:
                if cand.suffix != ".mp4":
                    # rename 到 .mp4
                    cand.rename(target_path)
                sz = target_path.stat().st_size
                return True, f"ok HLS {sz//1024}KB (N_m3u8DL-RE)"
        return False, "N_m3u8DL-RE ran OK but no output file"
    except subprocess.TimeoutExpired:
        return False, f"N_m3u8DL_timeout after {timeout}s"
    except Exception as e:
        return False, f"N_m3u8DL_exception: {e}"


def _download_one(url: str, target_path: Path, timeout: int | None = None) -> tuple[bool, str]:
    """下载一个 URL 到 target_path. 返回 (ok, 信息).

    智能分流:
      1. HLS m3u8 → N_m3u8DL-RE (16 线程 + 自动合并) — KS184 真实做法
      2. 短链 kuaishou.com/f/... → 先 _resolve_to_cdn 解析
      3. 直链 mp4 → requests GET

    ★ 2026-04-21: timeout + chunk_size 改 app_config 可配
    """
    if timeout is None:
        timeout = int(cfg_get("download.direct.timeout_sec", 120))
    chunk_size = int(cfg_get("download.direct.chunk_size_kb", 256)) * 1024

    # ① HLS 优先 (KS184 canonical)
    if _is_hls_url(url):
        return _download_hls(url, target_path)

    # ② 短链解析
    real_url = _resolve_to_cdn(url)
    was_resolved = real_url != url

    # 解析结果可能是 m3u8 → 再走 HLS
    if was_resolved and _is_hls_url(real_url):
        return _download_hls(real_url, target_path)

    # ③ 直链 GET
    try:
        headers = {
            "User-Agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                           "AppleWebKit/537.36 (KHTML, like Gecko) "
                           "Chrome/120.0.0.0 Safari/537.36"),
            "Accept": "*/*",
            "Referer": "https://www.kuaishou.com/",
        }
        with requests.get(real_url, headers=headers, stream=True, timeout=timeout) as r:
            r.raise_for_status()
            total = int(r.headers.get("Content-Length", 0))
            downloaded = 0
            target_path.parent.mkdir(parents=True, exist_ok=True)
            with open(target_path, "wb") as f:
                for chunk in r.iter_content(chunk_size=chunk_size):
                    if chunk:
                        f.write(chunk)
                        downloaded += len(chunk)
        if downloaded < 1024:
            return False, f"downloaded too small ({downloaded}B)"
        resolved_marker = " (resolved from share link)" if was_resolved else ""
        return True, f"ok {downloaded // 1024}KB{resolved_marker}"
    except requests.exceptions.RequestException as e:
        return False, f"http_error: {e}"
    except Exception as e:
        return False, f"unexpected: {e}"


def download_drama(
    drama_name: str,
    out_dir: str | None = None,
    attempts_per_url: int = 2,
    skip_verify: bool = False,
    auto_collect: bool = True,
) -> dict[str, Any]:
    """下载一个剧的视频, 按 URL 优先级逐个试, 第一个成功 + verify 通过就返回.

    Args:
        drama_name: 剧名, 对应 drama_links.drama_name
        out_dir: 下载目录, None = `short_drama_videos/`
        attempts_per_url: 每个 URL 重试次数
        skip_verify: 跳过 ffmpeg 完整性验证 (调试用)
        auto_collect: 无 URL 或 URL 全挂时自动调 collector_on_demand 去快手爬
                     (默认 True — pipeline 执行任务时按需补链)

    Returns:
        {ok: bool, file_path?, drama_url?, n_urls_tried: int, error?, verify_info?,
         collector_triggered?: bool, collector_result?: dict}
    """
    out_dir = out_dir or cfg_get("download.output_dir", "short_drama_videos")
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    with _connect() as conn:
        urls = _candidate_urls(conn, drama_name)

    # ★ 2026-04-21: 跨账号缓存优先 (KS184 style)
    # 13 账号发同剧 → 第 1 次真下, 后 12 次走 cache (省 92% 带宽)
    if urls and cfg_get("download.cache.enabled", True):
        cache_hit = _try_cache_hit(urls, out_dir, drama_name)
        if cache_hit:
            return cache_hit

    collector_result = None

    # 【fallback 层 1】初始无 URL → 自动调 collector 临时从快手爬
    if not urls and auto_collect:
        log.info("[downloader] '%s' 无 URL, 触发 collector_on_demand", drama_name)
        try:
            from core.collector_on_demand import ensure_urls_for_drama
            collector_result = ensure_urls_for_drama(drama_name, min_new_urls=1)
            log.info("[downloader] collector 回来: %s", collector_result)
            if collector_result.get("ok"):
                # 再查一次
                with _connect() as conn:
                    urls = _candidate_urls(conn, drama_name)
        except Exception as e:
            log.exception("[downloader] collector_on_demand 异常")
            collector_result = {"ok": False, "error": f"exception: {e}"}

    if not urls:
        msg = f"剧《{drama_name}》在 drama_links 无可用 URL"
        if collector_result and not collector_result.get("ok"):
            msg += f" (collector 也失败: {collector_result.get('error')})"
        log.warning("[downloader] %s", msg)
        notify(f"下载失败: 无可用 URL",
               f"drama_name={drama_name}\n{msg}",
               level="error", source="downloader",
               extra={"drama_name": drama_name,
                      "collector_result": collector_result})
        return {
            "ok": False, "error": "no_urls", "n_urls_tried": 0,
            "collector_triggered": bool(collector_result),
            "collector_result": collector_result,
        }

    tried_errors: list[str] = []
    for url_idx, url in enumerate(urls):
        safe_hash = hashlib.md5(url.encode("utf-8")).hexdigest()[:8]
        stamp = time.strftime("%Y%m%d_%H%M%S")
        rand = secrets.token_hex(3)
        target = out_dir / f"{safe_hash}_{stamp}_{rand}.mp4"

        log.info("[downloader] trying url %d/%d (hash=%s) for '%s'",
                 url_idx + 1, len(urls), safe_hash, drama_name)

        # 重试
        for attempt in range(1, attempts_per_url + 1):
            ok, info = _download_one(url, target)
            if ok:
                break
            log.warning("[downloader] attempt %d/%d failed: %s",
                        attempt, attempts_per_url, info)
            if attempt < attempts_per_url:
                time.sleep(2 ** attempt)

        if not ok:
            tried_errors.append(f"url{url_idx+1}:{info[:80]}")
            with _connect() as conn:
                _mark_url_broken(conn, url, f"download failed: {info[:60]}")
            try: target.unlink(missing_ok=True)
            except Exception: pass
            continue

        # 成功了, verify (★ 2026-04-21 Day 2 下午: 升级到 video_verifier 3-layer)
        vinfo = "skipped"
        verify_result: dict = {}
        if not skip_verify and cfg_get("video_verifier.enabled", True):
            from core.video_verifier import verify_video
            verify_result = verify_video(target)
            if not verify_result.get("ok"):
                errs = verify_result.get("errors", [])
                err_s = "; ".join(errs)[:150]
                log.warning("[downloader] %s video_verifier failed: %s", target, err_s)
                tried_errors.append(f"url{url_idx+1}:verify:{err_s[:80]}")
                fail_is_fatal = bool(cfg_get("video_verifier.fail_is_fatal", True))
                if fail_is_fatal:
                    with _connect() as conn:
                        _mark_url_broken(conn, url, f"verify failed: {err_s[:60]}")
                    try: target.unlink(missing_ok=True)
                    except Exception: pass
                    continue
                # 非 fatal — 仅记录, 继续用
                vinfo = f"verify_failed_non_fatal: {err_s[:60]}"
            else:
                dur = verify_result.get("duration", 0)
                cdc = verify_result.get("codec", "?")
                w = verify_result.get("width", 0)
                h = verify_result.get("height", 0)
                vinfo = f"ok {w}x{h} {cdc} dur={dur:.1f}s"

        # 成功且 verified
        cover_url_found = None
        with _connect() as conn:
            _bump_url_use(conn, url)
            _mark_url_success(conn, url)     # ★ 2026-04-21 Top 3: 清 fail_count
            _cache_download(conn, url, str(target), target.stat().st_size)
            cover_url_found = _cover_url_for(conn, url)
            # ★ 写 verify 结果到 drama_links
            if verify_result.get("ok"):
                try:
                    import json as _json
                    conn.execute(
                        """UPDATE drama_links SET
                             duration_sec=?, codec=?, width=?, height=?,
                             has_audio=?,
                             verify_errors_json=NULL,
                             updated_at=datetime('now','localtime')
                           WHERE drama_url=?""",
                        (verify_result.get("duration"),
                         verify_result.get("codec"),
                         verify_result.get("width"),
                         verify_result.get("height"),
                         1 if verify_result.get("has_audio") else 0,
                         url),
                    )
                    # 写 download_cache 的 verify + sha1 (如果算了)
                    sha1 = verify_result.get("hash_sha1")
                    if sha1:
                        import hashlib as _hl
                        url_hash = _hl.md5(url.encode("utf-8")).hexdigest()
                        conn.execute(
                            """UPDATE download_cache SET
                                 sha1_hash=?, verify_passed=1,
                                 verified_at=datetime('now','localtime')
                               WHERE drama_url_hash=?""",
                            (sha1, url_hash),
                        )
                    else:
                        import hashlib as _hl
                        url_hash = _hl.md5(url.encode("utf-8")).hexdigest()
                        conn.execute(
                            """UPDATE download_cache SET
                                 verify_passed=1,
                                 verified_at=datetime('now','localtime')
                               WHERE drama_url_hash=?""",
                            (url_hash,),
                        )
                    conn.commit()
                except Exception as e:
                    log.debug("[downloader] write verify result failed: %s", e)

        log.info("[downloader] ✅ %s → %s (verify: %s)", drama_name, target, vinfo)
        return {
            "ok": True,
            "file_path": str(target),
            "drama_url": url,
            "cover_url": cover_url_found,   # 给 cover_service 用 (cover_service 会下这个)
            "n_urls_tried": url_idx + 1,
            "verify_info": vinfo,
            "verify_result": verify_result,
            "size": target.stat().st_size,
        }

    # 所有 DB 里的 URL 全挂 → 【fallback 层 2】再调一次 collector 临时爬新 URL
    err_summary = "; ".join(tried_errors)[:300]
    log.warning("[downloader] DB 里 %d 个 URL 全挂, 尝试再调 collector 刷新",
                len(urls))

    retry_collector_result = None
    if auto_collect and not collector_result:  # 初始有 URL 所以还没调过 collector
        try:
            from core.collector_on_demand import ensure_urls_for_drama
            retry_collector_result = ensure_urls_for_drama(
                drama_name, min_new_urls=1,
                target_count=cfg_get("collector.on_demand.per_drama_count", 5),
            )
            if retry_collector_result.get("ok"):
                with _connect() as conn:
                    # 重取 候选池 (排除刚标记 broken 的)
                    new_urls = _candidate_urls(conn, drama_name)
                fresh_urls = [u for u in new_urls if u not in urls]
                if fresh_urls:
                    log.info("[downloader] collector 刷出 %d 个新 URL, 再试",
                             len(fresh_urls))
                    for fresh_url in fresh_urls:
                        safe_hash = hashlib.md5(fresh_url.encode("utf-8")).hexdigest()[:8]
                        target = out_dir / f"{safe_hash}_{time.strftime('%Y%m%d_%H%M%S')}_{secrets.token_hex(3)}.mp4"
                        ok, info = _download_one(fresh_url, target)
                        if ok:
                            if skip_verify:
                                vinfo = "skipped"
                            else:
                                ok, vinfo = verify_mp4(target)
                            if ok:
                                with _connect() as conn:
                                    _bump_url_use(conn, fresh_url)
                                    _cache_download(conn, fresh_url, str(target),
                                                    target.stat().st_size)
                                return {
                                    "ok": True,
                                    "file_path": str(target),
                                    "drama_url": fresh_url,
                                    "n_urls_tried": len(urls) + len(fresh_urls),
                                    "verify_info": vinfo,
                                    "size": target.stat().st_size,
                                    "collector_triggered": True,
                                    "collector_result": retry_collector_result,
                                    "from_fresh_collection": True,
                                }
                            try: target.unlink(missing_ok=True)
                            except Exception: pass
        except Exception as e:
            log.exception("[downloader] 二次 collector 异常")
            retry_collector_result = {"ok": False, "error": str(e)}

    log.error("[downloader] ❌ all %d URLs failed for '%s'", len(urls), drama_name)
    notify(
        f"下载失败: 所有 URL 失效",
        f"drama_name={drama_name}\n尝试 {len(urls)} 个 URL 全挂\n"
        f"collector fallback: {retry_collector_result}\n详情: {err_summary}",
        level="error", source="downloader",
        extra={"drama_name": drama_name, "n_urls": len(urls),
               "errors": tried_errors,
               "retry_collector": retry_collector_result},
    )
    return {
        "ok": False,
        "error": "all_urls_failed_even_after_recollect",
        "n_urls_tried": len(urls),
        "tried_errors": tried_errors,
        "collector_triggered": bool(collector_result or retry_collector_result),
        "collector_result": collector_result or retry_collector_result,
    }


if __name__ == "__main__":
    import argparse, json
    ap = argparse.ArgumentParser()
    ap.add_argument("--drama", required=True)
    ap.add_argument("--out-dir", default=None)
    ap.add_argument("--verify-only", default=None,
                    help="给一个视频路径, 只跑 verify_mp4")
    args = ap.parse_args()

    if args.verify_only:
        ok, info = verify_mp4(args.verify_only)
        print(f'verify_mp4({args.verify_only}) = {ok}  {info}')
    else:
        r = download_drama(args.drama, out_dir=args.out_dir)
        print(json.dumps(r, ensure_ascii=False, indent=2, default=str))
