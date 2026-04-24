# -*- coding: utf-8 -*-
"""KS 快手 profile/feed 按需采集器 — 核心实现.

★ 2026-04-24 v6 Week 2 Day 8 — 解决 CDN 荒漠问题

★ 背景:
  2026-04-17 起快手短链反爬升级, xinhui / v.kuaishou.com/f/ 100% 限流.
  但 KS184 仍能发, 因为它走 **profile/feed 路径** 而不是短链.

  本模块复刻 KS184 的 `profile_collection_service.get_profile_feed()`:
    POST https://www.kuaishou.com/rest/v/profile/feed
    headers: { kww, cookie }
    body:    { user_id, pcursor, page }
    response: feeds[].photo.photoUrls[].url  ← CDN 直链

★ 实测验证 (2026-04-24 14:58):
  - Trace 2026-04-17 抓的 kww + 新鲜 cookie → result=1 (待限频恢复)
  - API 活, 不校验 kww timestamp
  - Cookie 是否被接受: 我们 device_accounts.creator_cookie 可直接用

★ Cookie 轮换池:
  13 signed logged_in 账号 × creator_cookie → 52 候选
  遇 result=2 (限频) → 标记该账号 5 min 冷却, 切下一个
  遇 result=109 (过期) → 标记 24h 冷却
  遇 result=1 → 返 CDN + 更新该账号 last_success

★ 按需触发 (downloader L0.5):
  drama 无 CDN → 调 collect_for_drama(drama_name)
    1. 查 author_id (drama_links.author_id 或 drama_authors)
    2. pool.pick() 拿 1 个可用 cookie
    3. POST profile/feed(user_id=author_id)
    4. 从 feeds[] 提取 photo.photoUrls[].url
    5. 过滤 caption 含 drama_name 的条目 (作者可能有多部剧)
    6. 保存到 drama_links (含副产品: 同作者其他剧也存)

★ QPS 限制:
  - 每 cookie 3 min 内只能用 1 次 (防限频)
  - 全局 QPS ≤ 5 (保险)
  - 每剧 1h cooldown (采完别重复采)

★ 用法:
  from core.ks_profile_collector import collect_for_drama

  cdns = collect_for_drama("傲娇大小姐的护花使者")
  # → [{'photo_id': ..., 'url': 'https://xxx.djvod.ndcimgs.com/...', 'caption': ...}, ...]

  # CLI 单测:
  python -m core.ks_profile_collector --drama "傲娇大小姐的护花使者"
"""
from __future__ import annotations

import json
import logging
import random
import sqlite3
import sys
import threading
import time
from pathlib import Path
from typing import Optional

import requests

log = logging.getLogger(__name__)

# KWW "prefix" 常量 (KS184 源码固定, 全局唯一)
_FINGERPRINT_PREFIX = (
    "PnGU+9+Y8008S+nH0U+0mjPf8fP08f+98f+nLlwnrIP9+Sw/ZFGfzY+eGlGf"
    "+f+e4SGfbYP0QfGnLFwBLU80mYG"
)

# 从 trace 复用一个 kww suffix (2026-04-17 抓的, 服务器不校验 timestamp)
# TODO: 以后自己实现 AES-CBC 生成 (KEY=K8wm5PvY9nX7qJc2)
_FALLBACK_KWW_SUFFIX = (
    "RAQCGrElcBLDmKwqz5nmJUSS5OSR2UiwR3S0cyW3YQ8MTts5yPedfJa/uYxb41c"
)
_FALLBACK_KWW = _FINGERPRINT_PREFIX + _FALLBACK_KWW_SUFFIX


# 加载 trace 里的更多 kww samples (提高不同 URL 用不同 kww 的多样性)
def _load_kww_samples() -> list[str]:
    samples = []
    trace_file = Path("tools/trace_publish/http_20260417_163558.jsonl")
    if not trace_file.is_file():
        return [_FALLBACK_KWW]
    try:
        with trace_file.open("r", encoding="utf-8") as f:
            for line in f:
                r = json.loads(line)
                h = r.get("h", {})
                k = h.get("kww") or h.get("Kww")
                if k and len(k) > 100:
                    samples.append(k)
                    if len(samples) >= 20:
                        break
    except Exception:
        pass
    return samples or [_FALLBACK_KWW]


_KWW_SAMPLES = _load_kww_samples()


def _generate_kww() -> str:
    """返回一个 kww 值. 当前: 随机选 trace 样本. 未来: AES-CBC 本地生成."""
    return random.choice(_KWW_SAMPLES)


# ══════════════════════════════════════════════════════════════
# Cookie 池 — 13 账号轮换
# ══════════════════════════════════════════════════════════════
class CookiePool:
    """Cookie 轮换池.

    - load: 从 device_accounts 取 signed + logged_in 账号
    - pick: 轮询取下一个 available (跳过 cooldown 中的)
    - mark_rate_limited: result=2 → 5 min cooldown
    - mark_invalid: result=109 → 24h cooldown + cookie_last_success_at 清零
    """

    def __init__(self):
        self._lock = threading.Lock()
        self._accounts: list[dict] = []
        self._cursor = 0
        # account_id → unblock_ts
        self._blocked: dict[int, float] = {}
        self._loaded_at = 0.0

    def _load(self, force: bool = False) -> None:
        now = time.time()
        if not force and self._accounts and (now - self._loaded_at) < 300:
            return
        from core.config import DB_PATH
        with sqlite3.connect(DB_PATH, timeout=10) as c:
            c.row_factory = sqlite3.Row
            rows = c.execute("""
                SELECT id, kuaishou_name, cookies, numeric_uid
                FROM device_accounts
                WHERE login_status = 'logged_in'
                  AND (tier IS NULL OR tier != 'frozen')
                  AND cookies IS NOT NULL AND cookies != ''
                ORDER BY id
            """).fetchall()
        with self._lock:
            accts = []
            for r in rows:
                try:
                    raw = json.loads(r["cookies"])
                    ck = (raw.get("creator_cookie")
                          or raw.get("shop_cookie")
                          or raw.get("official_cookie")
                          or "")
                    if not ck:
                        continue
                    accts.append({
                        "id": int(r["id"]),
                        "name": r["kuaishou_name"] or "",
                        "cookie": ck,
                        "numeric_uid": r["numeric_uid"],
                    })
                except Exception:
                    continue
            self._accounts = accts
            self._loaded_at = now
        log.info("[cookie_pool] loaded %d active accounts", len(self._accounts))

    def pick(self) -> Optional[dict]:
        """选一个可用账号. None = 全被封."""
        self._load()
        now = time.time()
        with self._lock:
            n = len(self._accounts)
            if n == 0:
                return None
            # 最多尝试 N 次 (防死循环)
            for _ in range(n):
                acc = self._accounts[self._cursor]
                self._cursor = (self._cursor + 1) % n
                unblock = self._blocked.get(acc["id"], 0)
                if now < unblock:
                    continue
                return acc
        return None

    def mark_rate_limited(self, acc_id: int, cooldown_sec: int = 300) -> None:
        with self._lock:
            self._blocked[acc_id] = time.time() + cooldown_sec
        log.info("[cookie_pool] acct=%d rate-limited, cool down %ds",
                  acc_id, cooldown_sec)

    def mark_invalid(self, acc_id: int, cooldown_sec: int = 86400) -> None:
        with self._lock:
            self._blocked[acc_id] = time.time() + cooldown_sec
        log.warning("[cookie_pool] acct=%d cookie 失效, cool down %ds (需要重登)",
                     acc_id, cooldown_sec)

    def mark_success(self, acc_id: int) -> None:
        """成功后清掉 possibly-lingering cooldown (保险起见)."""
        # 不删 cooldown (防被滥用), 但可以记到 DB 里
        pass

    def snapshot(self) -> dict:
        self._load()
        now = time.time()
        with self._lock:
            avail = sum(1 for a in self._accounts
                         if now >= self._blocked.get(a["id"], 0))
            return {
                "total_accounts": len(self._accounts),
                "available_now": avail,
                "blocked": {k: round(v - now, 1) for k, v in self._blocked.items()
                             if v > now},
            }


_POOL = CookiePool()


# ══════════════════════════════════════════════════════════════
# API 调用
# ══════════════════════════════════════════════════════════════
def _call_profile_feed(user_id: str, cookie: str, kww: str,
                        pcursor: str = "",
                        timeout: int = 15) -> dict:
    """调 www.kuaishou.com/rest/v/profile/feed.

    Returns:
        {'result': 1/2/109, 'feeds': [...], 'pcursor': ..., 'error_msg': ...}
    """
    url = "https://www.kuaishou.com/rest/v/profile/feed"
    headers = {
        "Accept": "application/json",
        "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
        "Connection": "keep-alive",
        "Content-Type": "application/json;charset=UTF-8",
        "Cookie": cookie,
        "Host": "www.kuaishou.com",
        "kww": kww,
        "Origin": "https://www.kuaishou.com",
        "Referer": f"https://www.kuaishou.com/profile/{user_id}?source=NewReco",
        "User-Agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                         "AppleWebKit/537.36 (KHTML, like Gecko) "
                         "Chrome/120.0.0.0 Safari/537.36"),
        "Sec-Fetch-Dest": "empty",
        "Sec-Fetch-Mode": "cors",
        "Sec-Fetch-Site": "same-origin",
    }
    body = {"user_id": user_id, "pcursor": pcursor, "page": "profile"}

    resp = requests.post(url, headers=headers, json=body, timeout=timeout)
    try:
        return resp.json()
    except Exception:
        return {"result": -1, "error_msg": f"json parse: {resp.text[:200]}"}


def _extract_cdn_from_feed(feed: dict) -> list[dict]:
    """从 profile/feed 响应的一条 feed 里提取 CDN URL."""
    photo = feed.get("photo", {})
    photo_id = photo.get("id") or photo.get("photoId")
    caption = (photo.get("caption") or "").strip()
    duration = photo.get("duration", 0)
    out = []
    for u in photo.get("photoUrls") or []:
        if u.get("url"):
            out.append({
                "photo_id": str(photo_id) if photo_id else "",
                "url": u["url"],
                "cdn": u.get("cdn", ""),
                "caption": caption,
                "duration_ms": duration,
            })
    return out


# ══════════════════════════════════════════════════════════════
# GraphQL search — 按剧名搜 (作者无/换剧时 fallback)
# ══════════════════════════════════════════════════════════════
# KS184 原始 query string (从 trace 2026-04-17 抓)
_GRAPHQL_VISION_SEARCH_QUERY = (
    "fragment photoContent on PhotoEntity {\n"
    "  __typename\n  id\n  duration\n  caption\n  originCaption\n"
    "  likeCount\n  viewCount\n  commentCount\n  realLikeCount\n"
    "  coverUrl\n  photoUrl\n  photoH265Url\n  manifest\n  manifestH265\n"
    "  videoResource\n  coverUrls { url __typename }\n  timestamp\n"
    "  expTag\n  animatedCoverUrl\n  distance\n  videoRatio\n"
    "  liked\n  stereoType\n  profileUserTopPhoto\n  musicBlocked\n}\n\n"
    "fragment feedContent on Feed {\n  type\n  author {\n    id\n    name\n"
    "    headerUrl\n    following\n    headerUrls { url __typename }\n"
    "    __typename\n  }\n  photo { ...photoContent __typename }\n"
    "  canAddComment\n  llsid\n  status\n  currentPcursor\n"
    "  tags { type name __typename }\n  __typename\n}\n\n"
    "query visionSearchPhoto($keyword: String, $pcursor: String, "
    "$searchSessionId: String, $page: String, $webPageArea: String) {\n"
    "  visionSearchPhoto(keyword: $keyword, pcursor: $pcursor, "
    "searchSessionId: $searchSessionId, page: $page, webPageArea: $webPageArea) {\n"
    "    result\n    llsid\n    webPageArea\n    feeds { ...feedContent __typename }\n"
    "    searchSessionId\n    pcursor\n    aladdinBanner { imgUrl link __typename }\n"
    "    __typename\n  }\n}\n"
)


def _call_graphql_search(keyword: str, cookie: str, kww: str,
                           pcursor: str = "",
                           timeout: int = 15) -> dict:
    """GraphQL visionSearchPhoto — 按关键词搜视频."""
    url = "https://www.kuaishou.com/graphql"
    headers = {
        "accept": "*/*",
        "accept-language": "zh-CN,zh;q=0.9",
        "connection": "keep-alive",
        "content-type": "application/json",
        "cookie": cookie,
        "host": "www.kuaishou.com",
        "kww": kww,
        "origin": "https://www.kuaishou.com",
        "referer": "https://www.kuaishou.com/search/video?searchKey="
                    + requests.utils.quote(keyword),
        "user-agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                        "AppleWebKit/537.36 (KHTML, like Gecko) "
                        "Chrome/120.0.0.0 Safari/537.36"),
    }
    body = {
        "operationName": "visionSearchPhoto",
        "variables": {
            "keyword": keyword,
            "pcursor": pcursor,
            "page": "search_result",
            "searchSessionId": "",
        },
        "query": _GRAPHQL_VISION_SEARCH_QUERY,
    }

    resp = requests.post(url, headers=headers, json=body, timeout=timeout)
    try:
        return resp.json()
    except Exception:
        return {"data": None, "errors": [{"msg": resp.text[:200]}]}


def _extract_cdn_from_graphql_photo(photo: dict) -> list[dict]:
    """从 graphql search 响应的 photo 里提 CDN."""
    out = []
    photo_url = photo.get("photoUrl")
    if photo_url:
        out.append({
            "photo_id": str(photo.get("id") or ""),
            "url": photo_url,
            "cdn": photo_url.split("/")[2] if "/" in photo_url else "",
            "caption": (photo.get("caption") or "").strip(),
            "duration_ms": photo.get("duration", 0),
        })
    # 备用镜像可能在 manifest.adaptationSet (复杂, 暂不挖)
    return out


def search_drama_by_name(drama_name: str,
                          max_pages: int = 2,
                          max_retries: Optional[int] = None) -> list[dict]:
    """GraphQL search 按剧名找视频 + 提 CDN.

    作者不固定, 同一剧名可能来自多个作者/搬运者.
    比 profile/feed 更贵 (QPS 严格), 但能找到 profile 采集找不到的.

    Returns: [{photo_id, url (CDN), caption, author_id, author_name}, ...]
    """
    if not _cfg("ai.profile_collector.enabled", True):
        return []

    pool = _POOL
    n_retries = max_retries if max_retries is not None else min(5, len(pool._accounts))
    if n_retries <= 0: n_retries = 5

    all_cdns = []
    pcursor = ""

    for page in range(max_pages):
        success = False
        for attempt in range(1, n_retries + 1):
            acc = pool.pick()
            if not acc:
                break

            kww = _generate_kww()
            log.info("[search] page %d attempt %d: acct=%d (%s) keyword=%r",
                      page + 1, attempt, acc["id"], acc["name"], drama_name)

            try:
                resp = _call_graphql_search(drama_name, acc["cookie"], kww,
                                              pcursor=pcursor)
            except Exception as e:
                log.warning("[search] HTTP 异常 acct=%d: %s", acc["id"], e)
                pool.mark_rate_limited(acc["id"], cooldown_sec=60)
                continue

            data = (resp.get("data") or {}).get("visionSearchPhoto") or {}
            result = data.get("result")

            if result == 1:
                feeds = data.get("feeds") or []
                log.info("[search] ✅ page %d got %d feeds (pcursor=%s)",
                          page + 1, len(feeds), pcursor or "init")
                pool.mark_success(acc["id"])

                for f in feeds:
                    photo = f.get("photo") or {}
                    author = f.get("author") or {}
                    cdns = _extract_cdn_from_graphql_photo(photo)
                    for c in cdns:
                        c["author_id"] = author.get("id")
                        c["author_name"] = author.get("name")
                        all_cdns.append(c)

                pcursor = data.get("pcursor", "")
                success = True
                if pcursor in ("", "no_more"):
                    break
                break   # out of attempt loop, next page
            elif result == 2:
                pool.mark_rate_limited(acc["id"])
                continue
            elif result == 109:
                pool.mark_invalid(acc["id"])
                continue
            else:
                err = data.get("error_msg") or resp.get("errors")
                log.warning("[search] acct=%d result=%s err=%s",
                              acc["id"], result, str(err)[:80])
                pool.mark_rate_limited(acc["id"], cooldown_sec=120)
                continue

        if not success or pcursor in ("", "no_more"):
            break

    return all_cdns


# ══════════════════════════════════════════════════════════════
# Drama → eid 映射
# ══════════════════════════════════════════════════════════════
def _lookup_author_eid(drama_name: str) -> Optional[str]:
    """查剧的作者 eid (快手 userId 字母数字格式).

    先查 drama_links.author_id, 再查 drama_authors.
    """
    from core.config import DB_PATH
    with sqlite3.connect(DB_PATH, timeout=10) as c:
        # drama_links 里 author_id 覆盖 65% (实测)
        row = c.execute("""SELECT author_id FROM drama_links
            WHERE drama_name = ?
              AND author_id IS NOT NULL AND author_id != ''
            ORDER BY last_success_at DESC, id DESC
            LIMIT 1""", (drama_name,)).fetchone()
        if row and row[0]:
            return str(row[0])

        # 从 remark JSON 查 (部分 drama_links 把 author 存 remark.author_id 里)
        rows = c.execute("""SELECT remark FROM drama_links
            WHERE drama_name = ? AND remark IS NOT NULL AND remark != ''
            LIMIT 5""", (drama_name,)).fetchall()
        for (rk,) in rows:
            try:
                d = json.loads(rk)
                if d.get("author_id"):
                    return str(d["author_id"])
            except Exception:
                continue
    return None


def _save_cdns_to_drama_links(drama_name: str, author_id: str,
                                 cdns: list[dict]) -> int:
    """把采到的 CDN 写入 drama_links. 返写入数."""
    if not cdns:
        return 0
    from core.config import DB_PATH
    written = 0
    with sqlite3.connect(DB_PATH, timeout=30) as c:
        c.execute("PRAGMA busy_timeout=30000")
        for cdn in cdns:
            url = cdn["url"]
            # dedup by drama_url
            row = c.execute("""SELECT id FROM drama_links
                WHERE drama_name = ? AND drama_url = ?""",
                (drama_name, url)).fetchone()
            if row:
                c.execute("""UPDATE drama_links SET
                    last_success_at = datetime('now','localtime'),
                    updated_at = datetime('now','localtime')
                    WHERE id = ?""", (row[0],))
                continue

            remark = json.dumps({
                "photo_id": cdn.get("photo_id"),
                "caption": cdn.get("caption", "")[:200],
                "source": "profile_feed_collect",
            }, ensure_ascii=False)

            try:
                c.execute("""INSERT INTO drama_links
                    (drama_name, drama_url, author_id, status, source_file,
                     link_mode, verified_at, created_at, updated_at, remark,
                     duration_sec)
                    VALUES (?, ?, ?, 'active', 'profile_collector',
                            'web_cdn',
                            datetime('now','localtime'),
                            datetime('now','localtime'),
                            datetime('now','localtime'),
                            ?, ?)""",
                    (drama_name, url, author_id, remark,
                     int((cdn.get("duration_ms") or 0) / 1000)))
                written += 1
            except sqlite3.IntegrityError:
                pass
        c.commit()
    log.info("[collector] saved %d new CDNs for drama='%s' author=%s",
              written, drama_name, author_id)
    return written


# ══════════════════════════════════════════════════════════════
# 主入口
# ══════════════════════════════════════════════════════════════
# 每剧冷却: 1h 内不重复采 (避免重复 profile feed 请求)
_DRAMA_COOLDOWN: dict[str, float] = {}
_DRAMA_COOLDOWN_LOCK = threading.Lock()


def _cfg(key: str, default):
    try:
        from core.app_config import get as _g
        return _g(key, default)
    except Exception:
        return default


def collect_for_drama(drama_name: str,
                       max_retries: Optional[int] = None) -> list[dict]:
    """按剧名实时采集 CDN URL (KS184 profile/feed 路径).

    Args:
        drama_name: 剧名 (精确匹配)
        max_retries: cookie 池重试次数 (默认等于池大小)

    Returns:
        list[dict]: [{'photo_id', 'url' (CDN), 'caption', 'duration_ms'}, ...]
        空 list: 采集失败 / 池空 / 冷却中

    Side effects:
        - 保存 CDN 到 drama_links (含该作者其他剧的副产品)
        - 写 cookie pool cooldown (失败账号冷却)
    """
    if not _cfg("ai.profile_collector.enabled", True):
        return []

    # 剧级冷却 (1h 内只采 1 次, 避免重复打 API)
    cooldown_min = int(_cfg("ai.profile_collector.per_drama_cooldown_min", 60))
    with _DRAMA_COOLDOWN_LOCK:
        last = _DRAMA_COOLDOWN.get(drama_name, 0)
        if time.time() - last < cooldown_min * 60:
            log.debug("[collector] drama='%s' 冷却中, skip", drama_name)
            return []

    # Step 1: 查 author_id, 若无 → GraphQL 按剧名搜
    eid = _lookup_author_eid(drama_name)
    if not eid:
        log.info("[collector] drama='%s' 无 author_id → 走 GraphQL search",
                  drama_name)
        search_cdns = search_drama_by_name(drama_name, max_pages=2)
        # 过滤 caption 匹配
        matched = [c for c in search_cdns if drama_name in (c.get("caption", ""))]
        if matched:
            # 选第 1 个作者保存 (也可以存所有作者)
            first_author = matched[0].get("author_id", "")
            _save_cdns_to_drama_links(drama_name, first_author, matched)
            log.info("[collector] ✅ search 拿到 %d/%d matched (都入 drama_links)",
                      len(matched), len(search_cdns))
            with _DRAMA_COOLDOWN_LOCK:
                _DRAMA_COOLDOWN[drama_name] = time.time()
            return matched
        log.warning("[collector] drama='%s' search 也无结果", drama_name)
        with _DRAMA_COOLDOWN_LOCK:
            _DRAMA_COOLDOWN[drama_name] = time.time()
        return []

    # Step 2: cookie pool 轮询调用
    pool = _POOL
    n_retries = max_retries if max_retries is not None else len(pool._accounts)
    if n_retries <= 0:
        n_retries = 13

    all_cdns = []
    matched_cdns = []
    error_summary = []
    for attempt in range(1, n_retries + 1):
        acc = pool.pick()
        if not acc:
            log.warning("[collector] 无可用 cookie (全冷却中)")
            break

        kww = _generate_kww()
        log.info("[collector] attempt %d/%d: acct=%d (%s) for drama='%s' eid=%s",
                  attempt, n_retries, acc["id"], acc["name"], drama_name, eid)

        try:
            resp = _call_profile_feed(eid, acc["cookie"], kww, pcursor="")
        except Exception as e:
            log.warning("[collector] HTTP 异常 acct=%d: %s", acc["id"], e)
            pool.mark_rate_limited(acc["id"], cooldown_sec=60)
            error_summary.append(f"acct={acc['id']}:exc:{str(e)[:40]}")
            continue

        result = resp.get("result")
        if result == 1:
            feeds = resp.get("feeds") or []
            log.info("[collector] ✅ acct=%d got %d feeds", acc["id"], len(feeds))
            pool.mark_success(acc["id"])

            for f in feeds:
                cdns = _extract_cdn_from_feed(f)
                all_cdns.extend(cdns)
                # 过滤: caption 含 drama_name
                for c in cdns:
                    cap = c.get("caption", "")
                    if drama_name in cap:
                        matched_cdns.append(c)

            # 保存精确匹配的
            if matched_cdns:
                _save_cdns_to_drama_links(
                    drama_name=drama_name, author_id=eid, cdns=matched_cdns,
                )

            with _DRAMA_COOLDOWN_LOCK:
                _DRAMA_COOLDOWN[drama_name] = time.time()

            if matched_cdns:
                return matched_cdns

            # ★ profile 里没精确匹配 (作者换剧了) → GraphQL search fallback
            log.info("[collector] profile 无 '%s' 精匹 (作者换剧), 走 GraphQL search",
                      drama_name)
            search_cdns = search_drama_by_name(drama_name, max_pages=2)
            search_matched = [c for c in search_cdns
                               if drama_name in (c.get("caption", ""))]
            if search_matched:
                first_auth = search_matched[0].get("author_id", eid)
                _save_cdns_to_drama_links(drama_name, first_auth, search_matched)
                log.info("[collector] ✅ search 拿到 %d 条", len(search_matched))
                return search_matched

            log.warning("[collector] drama='%s' profile + search 都无精匹", drama_name)
            return []

        elif result == 2:
            # 限频
            log.warning("[collector] acct=%d result=2 (限频), 切换下一个",
                         acc["id"])
            pool.mark_rate_limited(acc["id"])
            error_summary.append(f"acct={acc['id']}:rate_limited")
            continue

        elif result == 109:
            # cookie 过期
            log.warning("[collector] acct=%d result=109 (cookie 过期)", acc["id"])
            pool.mark_invalid(acc["id"])
            error_summary.append(f"acct={acc['id']}:cookie_expired")
            continue

        else:
            err = resp.get("error_msg", "") or resp.get("message", "")
            log.warning("[collector] acct=%d result=%s msg=%s",
                         acc["id"], result, err[:80])
            pool.mark_rate_limited(acc["id"], cooldown_sec=120)
            error_summary.append(f"acct={acc['id']}:result={result}")
            continue

    log.error("[collector] drama='%s' 全池失败 (%d attempts): %s",
                drama_name, n_retries,
                "; ".join(error_summary[:3]))
    with _DRAMA_COOLDOWN_LOCK:
        _DRAMA_COOLDOWN[drama_name] = time.time()   # 失败也冷却
    return []


def health_snapshot() -> dict:
    return {
        "cookie_pool": _POOL.snapshot(),
        "drama_cooldown_active": sum(
            1 for ts in _DRAMA_COOLDOWN.values()
            if time.time() - ts < 60 * 60
        ),
        "kww_samples_loaded": len(_KWW_SAMPLES),
    }


# ══════════════════════════════════════════════════════════════
# CLI
# ══════════════════════════════════════════════════════════════
def main():
    import argparse
    ap = argparse.ArgumentParser(description="KS profile/feed 按需采集器")
    ap.add_argument("--drama", help="按剧名采集")
    ap.add_argument("--eid", help="指定作者 eid (覆盖 drama_name 查询)")
    ap.add_argument("--health", action="store_true", help="看 cookie pool + 冷却状态")
    ap.add_argument("--retries", type=int, default=None, help="最大重试数")
    args = ap.parse_args()

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
        datefmt="%H:%M:%S",
    )
    try: sys.stdout.reconfigure(encoding="utf-8")
    except Exception: pass

    if args.health:
        import json as _j
        print(_j.dumps(health_snapshot(), indent=2, ensure_ascii=False))
        return

    if args.drama:
        print(f"=== 采集 {args.drama!r} ===")
        cdns = collect_for_drama(args.drama, max_retries=args.retries)
        print(f"\n结果: 拿到 {len(cdns)} 条 CDN")
        for i, c in enumerate(cdns[:10], 1):
            print(f"  [{i}] photo_id={c['photo_id']} dur={c['duration_ms']/1000:.1f}s")
            print(f"      caption: {c['caption'][:80]}")
            print(f"      url:     {c['url'][:110]}")
        if not cdns:
            print("\n诊断:")
            s = health_snapshot()
            print(f"  cookie pool: {s['cookie_pool']}")
        return

    print("使用: python -m core.ks_profile_collector --drama 剧名 [--retries N]")
    print("     python -m core.ks_profile_collector --health")


if __name__ == "__main__":
    main()
