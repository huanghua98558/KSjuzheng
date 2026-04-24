# -*- coding: utf-8 -*-
"""On-demand 短剧 URL 采集器 — pipeline 执行任务时临时去快手爬.

调用时机:
  downloader.download_drama(name) 检查 drama_links 无可用 URL
  → 调 ensure_urls_for_drama(name)
  → 内部 drama_collector.search_by_keyword(name)
  → 过滤 + 生成分享链接 + 存 drama_links
  → downloader 再查一次, 找到 URL 就下

与 drama_collector.save_to_drama_links 的关键差异:
  save_to_drama_links 用 **caption** 作 drama_name → 结果就是 '#快来看短剧' 脏数据
  我们这里用 **目标剧名** 作 drama_name → 保证 drama_banner_tasks ↔ drama_links 对齐

配置项 (app_config):
    collector.on_demand.enabled              = true
    collector.on_demand.min_duration_sec     = 60
    collector.on_demand.per_drama_count      = 5      # 每个剧存几条 URL
    collector.on_demand.search_max_pages     = 2
    collector.on_demand.browser_account_pk   = 3      # 用哪个账号的 cookie 发搜索
"""
from __future__ import annotations

import json
import logging
import os
import sqlite3
import time
from datetime import datetime, timezone
from typing import Any

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


_coll = None


def _get_collector():
    """Lazy init DramaCollector (共享 1 个)."""
    global _coll
    if _coll is None:
        from core.db_manager import DBManager
        from core.cookie_manager import CookieManager
        from core.drama_collector import DramaCollector
        db = DBManager()
        cm = CookieManager(db)
        _coll = DramaCollector(db, cm)
        _coll._db = db   # 给 caller 留引用防 GC
    return _coll


def _has_usable_urls(drama_name: str) -> int:
    """当前 drama_links 里这个剧有几个真正可用 URL (2026-04-21 fix).

    筛选条件 (全部满足才算"可用"):
      a) drama_url 非空
      b) status 不是 broken/blocked/failed/downloading/completed
      c) 不在 cooldown_until 冷却期 (2026-04-21 新增 — 防死循环)
      d) verified_at 新于 12h, 或 NULL (从没 ffprobe 过的当作可尝试)
    """
    with _connect() as c:
        r = c.execute(
            """SELECT COUNT(*) FROM drama_links
               WHERE drama_name = ?
                 AND drama_url IS NOT NULL AND drama_url != ''
                 AND (status IS NULL OR status NOT IN
                      ('broken', 'blocked', 'failed', 'downloading', 'completed'))
                 AND (cooldown_until IS NULL OR cooldown_until < datetime('now'))
                 AND (verified_at IS NULL
                      OR (julianday('now') - julianday(verified_at)) * 24 < 12)""",
            (drama_name,),
        ).fetchone()
    return r[0] if r else 0


# 2026-04-20 step③ — caption 硬过滤黑/白名单
# UGC/二创/搬运关键词 (命中即过滤)
_CAPTION_BLACKLIST = (
    "解说", "剪辑", "搬运", "合集", "完整版", "完整在简介", "完整", "看简介",
    "二创", "精彩片段", "花絮", "片段", "看完整", "看全集", "全集", "预告",
    "打卡", "盘点", "推荐一部", "今日份", "短剧推荐",
)
# 作者名白名单特征 (含此词的作者更可信)
_AUTHOR_WHITELIST_HINT = ("影视", "官方", "短剧", "剧场", "追剧", "好剧")


def _caption_matches_drama(caption: str, drama_name: str,
                            author_name: str = "") -> tuple[bool, str]:
    """严格过滤: 筛选出真正属于该剧的 photo.

    规则 (按优先级):
      BLOCK — caption 含 UGC/搬运关键词 → 拒
      PASS  — caption 含 drama_name 完整名 (>= 4 字) → 通过
      PASS  — author_name 含白名单特征 + caption 含 drama_name 前 3 字 → 通过
      REJECT — 其他 (比如只是热门标签沾边)
    """
    cap = (caption or "").strip()
    au = (author_name or "").strip()

    # BLOCK: UGC 黑名单
    for bad in _CAPTION_BLACKLIST:
        if bad in cap:
            return False, f"blacklist:{bad}"

    # 剧名为空或过短 — 不能严格判 → 放行 (避免把短剧名误杀)
    if len(drama_name) < 3:
        return True, "drama_name_too_short_skip_check"

    # PASS 1: caption 直接含完整剧名 (最严)
    if drama_name in cap:
        return True, "caption_contains_full_name"

    # PASS 2: author_name 有白名单特征 + caption 含剧名前 3 字
    if any(h in au for h in _AUTHOR_WHITELIST_HINT) and drama_name[:3] in cap:
        return True, f"author_hint+name_prefix({au})"

    return False, "no_match"


def _ffprobe_verify_url(url: str, timeout: float = 3.0) -> tuple[bool, str]:
    """★ 2026-04-20 step② — 下载前 ffprobe 快验 URL 真实可播放性.

    只探 moov atom (文件头), ~100ms. 不真下载内容.
    Returns: (ok, reason)
    """
    import subprocess
    import shutil
    # 短链跳过探测 (因为需要先跳转) — 留给后续 _download_one 处理
    if "/f/" in url or "kuaishou.com/short-video" in url:
        return True, "shortlink_skip_probe"
    # HLS m3u8 单独处理
    if ".m3u8" in url.lower():
        return True, "hls_skip_probe"
    # 找 ffprobe
    ffprobe = (r"D:\ks_automation\tools\ffmpeg\bin\ffprobe.exe"
               if os.path.isfile(r"D:\ks_automation\tools\ffmpeg\bin\ffprobe.exe")
               else shutil.which("ffprobe"))
    if not ffprobe:
        return True, "ffprobe_not_found_skip"
    try:
        r = subprocess.run(
            [ffprobe, "-v", "error", "-select_streams", "v:0",
             "-show_entries", "stream=codec_name,width,height",
             "-of", "default=nw=1", "-timeout", "3000000",  # 3s usec * 1e6
             url],
            capture_output=True, text=True, timeout=timeout,
            encoding="utf-8", errors="replace",
        )
        if r.returncode != 0:
            return False, (r.stderr or "ffprobe_rc=!=0")[:80]
        if "codec_name" not in (r.stdout or ""):
            return False, "no_codec_in_probe"
        return True, "ok"
    except subprocess.TimeoutExpired:
        return False, "ffprobe_timeout"
    except Exception as e:
        return False, f"ffprobe_exc:{type(e).__name__}"


def _save_photos_as_drama(drama_name: str, photos: list[dict],
                           source_file: str = "on_demand_search") -> int:
    """存 photos 到 drama_links, 用传入的 drama_name 作 key (不用 caption).

    ★ 2026-04-20 升级: 入库前做 2 道过滤
      step ③ caption/author 硬过滤 (拒 UGC/二创)
      step ② ffprobe 快验 (拒 broken URL)
    """
    saved = 0
    skipped_dup = 0
    skipped_caption = 0
    skipped_probe = 0
    now = datetime.now(timezone.utc).isoformat()

    do_caption = cfg_get("collector.on_demand.caption_filter", True)
    do_probe = cfg_get("collector.on_demand.ffprobe_verify", True)

    with _connect() as c:
        for p in photos:
            share_url = (p.get("share_url") or "").strip()
            if not share_url:
                skipped_dup += 1
                continue

            # 先去重 (同 URL 已存在)
            exists = c.execute(
                "SELECT id, drama_name FROM drama_links WHERE drama_url = ?",
                (share_url,),
            ).fetchone()
            if exists:
                # 如果同 URL 之前是脏 drama_name, 这次校正成真剧名
                if exists["drama_name"] != drama_name:
                    c.execute(
                        "UPDATE drama_links SET drama_name = ?, updated_at = ? WHERE id = ?",
                        (drama_name, now, exists["id"]),
                    )
                skipped_dup += 1
                continue

            caption = (p.get("caption") or "")
            author_name = (p.get("author_name") or "")

            # ★ step ③ caption/author 过滤
            if do_caption:
                cap_ok, cap_reason = _caption_matches_drama(caption, drama_name, author_name)
                if not cap_ok:
                    log.debug("[on_demand] filter '%s' caption=%r → %s",
                              drama_name, caption[:40], cap_reason)
                    skipped_caption += 1
                    continue

            # ★ step ② ffprobe 预验
            if do_probe:
                ok, reason = _ffprobe_verify_url(share_url)
                if not ok:
                    log.debug("[on_demand] ffprobe reject '%s': %s", drama_name, reason)
                    skipped_probe += 1
                    continue

            remark = json.dumps({
                "photo_id": p.get("photo_encrypt_id"),
                "duration_sec": p.get("duration_sec"),
                "view_count": p.get("view_count"),
                "like_count": p.get("like_count"),
                "author_name": author_name,
                "cover_url": p.get("cover_url"),
                "collected_at": now,
                "ffprobe_verified": do_probe,
            }, ensure_ascii=False)
            try:
                # ★ step① v29: 存 photo_encrypt_id + author_id + short_link + resolved_at
                c.execute(
                    """INSERT INTO drama_links
                         (drama_name, drama_url, source_file, link_mode,
                          status, created_at, updated_at, remark,
                          description, photo_encrypt_id, author_id,
                          short_link, url_resolved_at, verified_at)
                       VALUES (?, ?, ?, 'firefly', 'pending', ?, ?, ?, ?,
                               ?, ?, ?, ?, ?)""",
                    (drama_name, share_url, source_file, now, now,
                     remark, caption[:200],
                     p.get("photo_encrypt_id") or None,
                     p.get("author_id") or None,
                     p.get("short_link") or None,
                     now,                           # url_resolved_at = 采集时
                     now if do_probe else None,     # verified_at = ffprobe 通过的时间
                    ),
                )
                saved += 1
            except sqlite3.IntegrityError:
                skipped_dup += 1
        c.commit()

    if skipped_caption or skipped_probe:
        log.info(
            "[on_demand] '%s' save=%d | filter caption=%d ffprobe=%d | dup=%d",
            drama_name, saved, skipped_caption, skipped_probe, skipped_dup,
        )
    return saved


def ensure_urls_for_drama(
    drama_name: str,
    min_new_urls: int = 1,
    target_count: int | None = None,
) -> dict[str, Any]:
    """确保这个剧在 drama_links 里有至少 min_new_urls 个可用 URL.

    如果已足够 → 直接返回 (no-op).
    不够 → 搜索 + 保存, 直到满足或搜索穷尽.

    Returns:
        {ok, have_before, have_after, new_saved, searched, error?}
    """
    if not cfg_get("collector.on_demand.enabled", True):
        return {"ok": False, "error": "on_demand_disabled"}

    target = target_count or cfg_get("collector.on_demand.per_drama_count", 5)
    before = _has_usable_urls(drama_name)

    if before >= min_new_urls:
        log.info("[on_demand] '%s' 已有 %d 个 URL, skip", drama_name, before)
        return {"ok": True, "have_before": before, "have_after": before,
                "new_saved": 0, "searched": False}

    log.info("[on_demand] '%s' 仅 %d 个 URL (目标 >=%d), 开始搜索",
             drama_name, before, min_new_urls)

    try:
        coll = _get_collector()
    except Exception as e:
        log.error("[on_demand] DramaCollector 初始化失败: %s", e)
        return {"ok": False, "error": f"init_failed: {e}",
                "have_before": before, "have_after": before}

    # 选个 browser account (有 main 域 cookie 的账号, search API 要)
    browser_pk = cfg_get("collector.on_demand.browser_account_pk", 3)
    max_pages = cfg_get("collector.on_demand.search_max_pages", 2)
    min_dur = cfg_get("collector.on_demand.min_duration_sec", 60)

    # 类型强转 helper
    def _to_int(v, default=0):
        if isinstance(v, int): return v
        if isinstance(v, float): return int(v)
        if isinstance(v, str):
            s = v.strip()
            try: return int(float(s))
            except Exception:
                try:
                    if s.endswith(('万', 'w', 'W')):
                        return int(float(s[:-1]) * 10000)
                except Exception:
                    return default
        return default

    # ─── Step 1: search_by_keyword → 拿候选作者 ───
    # ★ 2026-04-21 14:30 hotfix: 单号风控严重, 轮换账号池
    # 原只用 browser_pk (default=3) → 风控后全挂. 现遍历健康账号, 第一个成功即用.
    t0 = time.time()
    search_results = []
    search_attempts = []

    # 拿健康账号池
    try:
        from core.downloader import _get_healthy_account_pool
        with _connect() as _c:
            acc_pool = _get_healthy_account_pool(_c, pool_size=int(cfg_get("ai.url_health.refresh_pool_size", 5)))
    except Exception:
        acc_pool = [browser_pk]

    # 保证 browser_pk 在最前 (若它还健康就先它)
    if browser_pk in acc_pool:
        acc_pool = [browser_pk] + [x for x in acc_pool if x != browser_pk]

    for try_pk in acc_pool[:int(cfg_get("ai.url_health.refresh_max_retry", 3))]:
        try:
            search_results = coll.search_by_keyword(drama_name,
                                                      browser_account_pk=try_pk,
                                                      max_pages=max_pages)
            search_attempts.append({"acct_pk": try_pk, "n": len(search_results)})
            if search_results:
                log.info("[on_demand] search '%s' via acc_pk=%d OK (%d results)",
                         drama_name, try_pk, len(search_results))
                break
        except Exception as e:
            search_attempts.append({"acct_pk": try_pk, "err": str(e)[:80]})
            log.warning("[on_demand] search acc_pk=%d for '%s' failed: %s",
                         try_pk, drama_name, e)
            continue

    if not search_results:
        log.warning("[on_demand] '%s' 搜索 0 结果 (轮换 %d 账号全失败)",
                    drama_name, len(search_attempts))
        notify(f"采集失败: 搜索 0 结果",
               f"drama_name={drama_name}\n轮换 {len(search_attempts)} 账号全无果\n"
               f"attempts: {search_attempts}",
               level="warning", source="collector_on_demand",
               extra={"drama_name": drama_name, "attempts": search_attempts})
        return {"ok": False, "error": "search_empty",
                "have_before": before, "have_after": before, "searched": True,
                "search_attempts": search_attempts}

    # 候选作者 (按出现次数排)
    author_scores: dict[str, int] = {}
    for r in search_results:
        aid = r.get("author_id")
        if aid:
            author_scores[aid] = author_scores.get(aid, 0) + 1
    top_authors = sorted(author_scores.items(), key=lambda x: x[1],
                         reverse=True)[:5]
    log.info("[on_demand] search '%s' → %d results (%.1fs), TOP 作者: %s",
             drama_name, len(search_results), time.time() - t0,
             [(a[:8], n) for a, n in top_authors])

    # ─── Step 2: fetch_profile_feed 从作者 feed 提 CDN 直链 ───
    candidates: list[dict] = []
    for aid, score in top_authors:
        if len(candidates) >= target:
            break
        try:
            feeds = coll.fetch_profile_feed(aid, browser_account_pk=browser_pk,
                                              max_pages=1)
        except Exception as e:
            log.warning("[on_demand] profile_feed %s failed: %s", aid[:10], e)
            continue
        for f in feeds:
            if len(candidates) >= target:
                break
            caption = (f.get("caption") or "").strip()
            dur = _to_int(f.get("duration_sec", 0))
            if dur < min_dur:
                continue
            # caption 含剧名 (宽松匹配, 支持带#号的标题)
            if drama_name not in caption:
                continue
            raw_photo = (f.get("raw") or {}).get("photo") or {}
            photo_urls = raw_photo.get("photoUrls") or []
            cdn_url = ""
            for pu in photo_urls:
                if isinstance(pu, dict) and pu.get("url"):
                    cdn_url = pu["url"]
                    break
            if not cdn_url:
                continue
            candidates.append({
                "photo_encrypt_id": f.get("photo_encrypt_id"),
                "caption": caption,
                "duration_sec": dur,
                "view_count": _to_int(f.get("view_count", 0)),
                "like_count": _to_int(f.get("like_count", 0)),
                "author_id": aid,
                "author_name": f.get("nickname", ""),
                "cover_url": f.get("cover_url", ""),
                "share_url": cdn_url,   # ✨ CDN 直链
            })

    log.info("[on_demand] feed 提取 CDN 候选 %d 条", len(candidates))

    # 兜底: feed 没找, 退回 share_link (下载时可能失败, 但至少存下来)
    if not candidates:
        log.warning("[on_demand] feed 为空, 兜底用 search_link")
        filtered = [p for p in search_results
                    if _to_int(p.get("duration_sec", 0)) >= min_dur]
        if len(filtered) > target:
            filtered = sorted(filtered, key=lambda p: _to_int(p.get("view_count", 0)),
                              reverse=True)[:target]
        for p in filtered[:target]:
            pid = p.get("photo_encrypt_id")
            if not pid:
                continue
            try:
                sl = coll.generate_share_link(
                    pid, browser_account_pk=browser_pk,
                    title=p.get("caption", "")[:100],
                    nickname=p.get("author_name", ""),
                    cover_url=p.get("cover_url", ""),
                )
                if sl.get("share_url"):
                    p["share_url"] = sl["share_url"]
                    candidates.append(p)
            except Exception as e:
                log.warning("[on_demand] gen share for %s failed: %s", pid, e)

    if not candidates:
        return {"ok": False, "error": "no_candidates",
                "have_before": before, "have_after": before,
                "searched": True, "raw_results": len(search_results)}

    # 存 (用目标 drama_name 不用 caption)
    saved = _save_photos_as_drama(drama_name, candidates,
                                     source_file="on_demand_feed")

    after = _has_usable_urls(drama_name)
    log.info("[on_demand] '%s' before=%d → after=%d (new=%d)",
             drama_name, before, after, saved)

    return {
        "ok": after >= min_new_urls,
        "have_before": before,
        "have_after": after,
        "new_saved": saved,
        "searched": True,
        "raw_results": len(search_results),
        "candidates_found": len(candidates),
        "drama_name": drama_name,
    }


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--drama", required=True)
    ap.add_argument("--count", type=int, default=5)
    args = ap.parse_args()

    import logging as _lg
    _lg.basicConfig(level=_lg.INFO, format="[%(asctime)s] %(levelname)s %(name)s %(message)s")
    r = ensure_urls_for_drama(args.drama, target_count=args.count)
    print(json.dumps(r, ensure_ascii=False, indent=2, default=str))
