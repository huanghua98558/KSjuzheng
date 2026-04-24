# -*- coding: utf-8 -*-
"""Kuaishou drama collector (Level 4: drama acquisition).

Rewritten 2026-04-17 based on Frida-captured real KS184 collection flow
(http_20260417_163558.jsonl — 1498 requests during UI "视频采集" operation).

Captured pipeline per target UID:
  Step A.  POST /rest/v/profile/feed           (list works of target UID)
  Step B.  For each photo:
           POST /rest/zt/share/w/any           (make kuaishou.com/f/ short link)
  Step C.  Filters: view_count / like_count / comment_count / duration
  Step D.  De-dup by (drama_url) OR (drama_name)
  Step E.  Upsert to drama_links table

The Cookie used for collection is ONE OF OUR MATRIX ACCOUNTS' OWN cookie
(``domain="all"`` suite). Collector masquerades as a logged-in user to
view another account's public profile — no special privilege needed.

Signing: ``profile/feed`` and ``share/w/any`` both need NONE (cookie only).
Only ``nebula/feed/selection`` (optional stats enrichment) needs sig3.
"""

from __future__ import annotations

import json
import logging
import time
from datetime import datetime
from typing import Any

import requests

log = logging.getLogger(__name__)

_PROFILE_FEED_URL = "https://www.kuaishou.com/rest/v/profile/feed"
_SHARE_ANY_URL = "https://www.kuaishou.com/rest/zt/share/w/any"
_GRAPHQL_URL = "https://www.kuaishou.com/graphql"

# Minimal subset of the captured visionSearchPhoto GraphQL query.
# Only requests the fields we actually need; full field-set still works but
# over-fetches. Captured via Frida trace 2026-04-17 18:48.
_SEARCH_QUERY = """
fragment photoContent on PhotoEntity {
  __typename id duration caption likeCount viewCount commentCount
  coverUrl timestamp videoRatio
}
fragment feedContent on Feed {
  type
  author { id name headerUrl following }
  photo { ...photoContent }
  tags { type name }
}
query visionSearchPhoto($keyword: String, $pcursor: String, $searchSessionId: String, $page: String) {
  visionSearchPhoto(keyword: $keyword, pcursor: $pcursor, searchSessionId: $searchSessionId, page: $page) {
    result llsid searchSessionId pcursor
    feeds { ...feedContent }
  }
}
""".strip()

_WEB_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "zh-CN,zh;q=0.9",
    "Origin": "https://www.kuaishou.com",
    "Referer": "https://www.kuaishou.com/",
    "Content-Type": "application/json",
}


class DramaCollector:
    """Collect drama videos from external Kuaishou accounts by UID."""

    def __init__(self, db_manager, cookie_manager):
        """
        Parameters
        ----------
        db_manager : DBManager
        cookie_manager : CookieManager
            Used to fetch the cookie of ONE of our own matrix accounts —
            serves as the browsing identity for profile/feed calls.
        """
        self.db = db_manager
        self.cookie_mgr = cookie_manager
        self._sess = requests.Session()

    # ------------------------------------------------------------------
    # Step A: profile/feed
    # ------------------------------------------------------------------

    def fetch_profile_feed(
        self,
        target_user_id: str,
        browser_account_pk: int,
        max_pages: int = 3,
    ) -> list[dict[str, Any]]:
        """Fetch all photos from ``target_user_id`` using ``browser_account_pk``'s cookie.

        Parameters
        ----------
        target_user_id : str
            Kuaishou encryptUid (e.g. ``3x27nq77424xvce``) of the account
            to scrape. This is the ``user_id`` field in profile/feed body.
        browser_account_pk : int
            ``device_accounts.id`` of the cookie to use for browsing.
        max_pages : int
            Upper bound on pagination (default 3).

        Returns
        -------
        list[dict]
            Each dict = one photo row with keys: ``photo_encrypt_id``,
            ``caption``, ``duration_ms``, ``view_count``, ``like_count``,
            ``comment_count``, ``cover_url``, ``nickname``, ``tags``, ``raw``.
        """
        # www.kuaishou.com lives in the cookies[] array. "all" triggers a 431
        # Request Header Fields Too Large, so pick "main" which is the exact
        # cookie subset www.kuaishou.com expects.
        cookie_str = self.cookie_mgr.get_cookie_string(browser_account_pk, domain="main")
        if not cookie_str:
            log.error("[Collector] no cookie for browser account pk=%s", browser_account_pk)
            return []

        headers = {**_WEB_HEADERS, "Cookie": cookie_str}
        all_photos: list[dict[str, Any]] = []
        pcursor = ""

        for page in range(max_pages):
            payload = {"user_id": target_user_id, "pcursor": pcursor, "page": "profile"}
            try:
                resp = self._sess.post(_PROFILE_FEED_URL, json=payload,
                                       headers=headers, timeout=15)
                resp.raise_for_status()
                data = resp.json()
            except (requests.RequestException, ValueError) as exc:
                log.error("[Collector] profile/feed failed (page %d, uid=%s): %s",
                          page + 1, target_user_id, exc)
                break

            if data.get("result") != 1:
                log.warning("[Collector] profile/feed result=%s for uid=%s",
                            data.get("result"), target_user_id)
                break

            feeds = data.get("feeds") or []
            for feed in feeds:
                photo = feed.get("photo") or {}
                ext = feed.get("ext_params") or {}
                photo_id = photo.get("id") or photo.get("photoId", "")
                tags = [t.get("name", "") for t in (feed.get("tags") or [])]
                duration_ms = photo.get("duration", 0)
                row = {
                    "photo_encrypt_id": str(photo_id),
                    "caption": photo.get("caption", ""),
                    "duration_ms": duration_ms,
                    "duration_sec": duration_ms / 1000 if duration_ms else 0,
                    "view_count": photo.get("viewCount") or ext.get("play", 0),
                    "like_count": photo.get("likeCount") or ext.get("like", 0),
                    "comment_count": photo.get("commentCount") or ext.get("comment", 0),
                    "cover_url": (photo.get("coverUrls") or [{}])[0].get("url", "")
                                 or photo.get("thumbnailUrl", ""),
                    "nickname": (feed.get("user") or {}).get("user_name", ""),
                    "tags": tags,
                    "timestamp": photo.get("timestamp", 0),
                    "raw": feed,
                }
                all_photos.append(row)

            pcursor = data.get("pcursor", "")
            log.info("[Collector] uid=%s page %d: fetched %d (cursor=%s)",
                     target_user_id, page + 1, len(feeds), pcursor[:20])
            if not pcursor or pcursor == "no_more":
                break
            time.sleep(0.5)

        log.info("[Collector] uid=%s total photos: %d", target_user_id, len(all_photos))
        return all_photos

    # ------------------------------------------------------------------
    # Keyword search (discover new authors + dramas in one shot)
    # ------------------------------------------------------------------

    def search_by_keyword(
        self,
        keyword: str,
        browser_account_pk: int,
        max_pages: int = 3,
    ) -> list[dict[str, Any]]:
        """GraphQL visionSearchPhoto — discover photos + authors by keyword.

        Captured via Frida on 2026-04-17. Each result contains an
        ``author`` block which is the gold mine for populating
        ``drama_authors``.

        Returns list of dicts:
          {photo_encrypt_id, caption, duration_sec, view_count, like_count,
           comment_count, cover_url, author_id, author_name, tags}
        """
        cookie_str = self.cookie_mgr.get_cookie_string(browser_account_pk, domain="main")
        if not cookie_str:
            log.error("[Collector] no cookie for browser account pk=%s", browser_account_pk)
            return []

        headers = {**_WEB_HEADERS, "Cookie": cookie_str}
        results: list[dict[str, Any]] = []
        pcursor = ""
        search_session_id = ""

        for page in range(max_pages):
            body = {
                "operationName": "visionSearchPhoto",
                "variables": {
                    "keyword": keyword,
                    "pcursor": pcursor,
                    "page": "search_result",
                    "searchSessionId": search_session_id,
                },
                "query": _SEARCH_QUERY,
            }
            try:
                resp = self._sess.post(_GRAPHQL_URL, json=body, headers=headers, timeout=15)
                resp.raise_for_status()
                rj = resp.json()
            except (requests.RequestException, ValueError) as exc:
                log.error("[Collector] graphql search failed (page %d): %s", page + 1, exc)
                break

            vs = (rj.get("data") or {}).get("visionSearchPhoto") or {}
            if vs.get("result") != 1:
                log.warning("[Collector] search result=%s for '%s'", vs.get("result"), keyword)
                break

            feeds = vs.get("feeds") or []
            for f in feeds:
                author = f.get("author") or {}
                photo = f.get("photo") or {}
                tags = [t.get("name", "") for t in (f.get("tags") or [])]
                duration_ms = photo.get("duration", 0)
                results.append({
                    "photo_encrypt_id": photo.get("id", ""),
                    "caption": photo.get("caption", ""),
                    "duration_ms": duration_ms,
                    "duration_sec": duration_ms / 1000 if duration_ms else 0,
                    "view_count": photo.get("viewCount", 0),
                    "like_count": photo.get("likeCount", 0),
                    "comment_count": photo.get("commentCount", 0),
                    "cover_url": photo.get("coverUrl", ""),
                    "author_id": author.get("id", ""),
                    "author_name": author.get("name", ""),
                    "author_header": author.get("headerUrl", ""),
                    "tags": tags,
                    "timestamp": photo.get("timestamp", 0),
                    "raw": f,
                })

            pcursor = vs.get("pcursor", "")
            search_session_id = vs.get("searchSessionId", "")
            log.info("[Collector] search '%s' page %d: %d feeds (cursor=%s)",
                     keyword, page + 1, len(feeds), str(pcursor)[:20])
            if not pcursor or pcursor == "no_more":
                break
            time.sleep(0.5)

        log.info("[Collector] search '%s' total: %d feeds, %d unique authors",
                 keyword, len(results),
                 len({r["author_id"] for r in results if r.get("author_id")}))
        return results

    def harvest_authors_from_search(
        self,
        keyword: str,
        browser_account_pk: int,
        max_pages: int = 3,
    ) -> int:
        """Search by keyword + insert every unique author into drama_authors.

        Returns number of NEW authors added.
        """
        results = self.search_by_keyword(keyword, browser_account_pk, max_pages=max_pages)
        unique_authors = {}
        for r in results:
            aid = r.get("author_id")
            if not aid:
                continue
            if aid not in unique_authors:
                unique_authors[aid] = r.get("author_name") or ""

        new_count = 0
        for aid, name in unique_authors.items():
            existing = self.db.conn.execute(
                "SELECT 1 FROM drama_authors WHERE kuaishou_uid = ?", (aid,)
            ).fetchone()
            if existing:
                # Update nickname if we now have one
                if name:
                    self.db.conn.execute(
                        """UPDATE drama_authors SET
                             nickname = COALESCE(NULLIF(?,''), nickname),
                             updated_at = datetime('now','localtime')
                           WHERE kuaishou_uid = ?""",
                        (name, aid),
                    )
                continue
            self.db.conn.execute(
                """INSERT INTO drama_authors
                     (kuaishou_uid, nickname, source, notes, is_active)
                   VALUES (?, ?, 'search', ?, 1)""",
                (aid, name, f"keyword={keyword}"),
            )
            new_count += 1
        self.db.conn.commit()
        log.info("[Collector] search harvest '%s': %d unique authors, %d new",
                 keyword, len(unique_authors), new_count)
        return new_count

    # ------------------------------------------------------------------
    # Step B: share link generation
    # ------------------------------------------------------------------

    def generate_share_link(
        self,
        photo_encrypt_id: str,
        browser_account_pk: int,
        title: str = "",
        nickname: str = "",
        cover_url: str = "",
    ) -> dict[str, Any]:
        """Convert photo encrypt id → kuaishou.com/f/ short link."""
        cookie_str = self.cookie_mgr.get_cookie_string(browser_account_pk, domain="main")
        if not cookie_str:
            return {}

        payload = {
            "kpn": "KUAISHOU_VISION",
            "kpf": "PC_WEB",
            "subBiz": "SINGLE_ROW_WEB",
            "sdkVersion": "1.1.2.2.0",
            "shareChannel": "COPY_LINK",
            "shareMethod": "TOKEN",
            "shareObjectId": photo_encrypt_id,
            "extTokenStoreParams": {
                "title": title,
                "nickname": nickname,
                "coverUrl": cover_url,
                "photoId": photo_encrypt_id,
                "queries": "?source=PROFILE&",
                "videoType": "short-video",
            },
        }
        headers = {**_WEB_HEADERS, "Cookie": cookie_str}
        try:
            resp = self._sess.post(_SHARE_ANY_URL, json=payload,
                                   headers=headers, timeout=15)
            resp.raise_for_status()
            data = resp.json()
            if data.get("result") != 1:
                log.warning("[Collector] share/w/any result=%s: %s",
                            data.get("result"), data.get("error_msg"))
                return {}
            so = (data.get("share") or {}).get("shareObject") or {}
            return {
                "share_url": so.get("shortLink") or so.get("shareMessage", ""),
                "kwai_token": so.get("kwaiToken", ""),
                "share_id": so.get("shareId", ""),
            }
        except (requests.RequestException, ValueError) as exc:
            log.error("[Collector] share/w/any failed for %s: %s",
                      photo_encrypt_id, exc)
            return {}

    # ------------------------------------------------------------------
    # Filtering + de-dup
    # ------------------------------------------------------------------

    @staticmethod
    def apply_filters(
        photos: list[dict],
        min_view: int = 0,
        min_like: int = 0,
        min_comment: int = 0,
        min_duration_sec: int = 60,
    ) -> list[dict]:
        """Apply per-video filters (UI '过滤条件' equivalents)."""
        out = []
        for p in photos:
            if p.get("view_count", 0) < min_view: continue
            if p.get("like_count", 0) < min_like: continue
            if p.get("comment_count", 0) < min_comment: continue
            if p.get("duration_sec", 0) < min_duration_sec: continue
            out.append(p)
        return out

    def filter_duplicates(
        self,
        photos: list[dict],
        by_link: bool = True,
        by_content: bool = True,
    ) -> list[dict]:
        """Drop photos duplicating existing drama_links rows."""
        if not (by_link or by_content):
            return photos

        existing_urls = set()
        existing_names = set()
        if by_link:
            for r in self.db.conn.execute(
                "SELECT drama_url FROM drama_links WHERE drama_url IS NOT NULL AND drama_url != ''"
            ).fetchall():
                existing_urls.add(r[0])
        if by_content:
            for r in self.db.conn.execute(
                "SELECT drama_name FROM drama_links WHERE drama_name IS NOT NULL"
            ).fetchall():
                existing_names.add(r[0])

        out = []
        for p in photos:
            url = p.get("share_url") or ""
            name = (p.get("caption") or "").strip().split("\n")[0][:100]
            if by_link and url and url in existing_urls:
                continue
            if by_content and name and name in existing_names:
                continue
            out.append(p)
        return out

    # ------------------------------------------------------------------
    # Persistence
    # ------------------------------------------------------------------

    def save_to_drama_links(
        self,
        photos: list[dict],
        source_file: str = "profile_feed",
        link_mode: str = "firefly",
    ) -> int:
        saved = 0
        now = datetime.utcnow().isoformat()
        for p in photos:
            share_url = p.get("share_url") or ""
            if not share_url:
                continue
            drama_name = (p.get("caption") or "").strip().split("\n")[0][:200] \
                or p.get("photo_encrypt_id", "")
            try:
                self.db.conn.execute(
                    """INSERT INTO drama_links
                         (drama_name, drama_url, source_file, link_mode,
                          status, created_at, updated_at, remark)
                       VALUES (?, ?, ?, ?, 'pending', ?, ?, ?)
                       ON CONFLICT(drama_url, link_mode) DO UPDATE SET
                         updated_at = excluded.updated_at,
                         remark = excluded.remark""",
                    (
                        drama_name, share_url, source_file, link_mode,
                        now, now,
                        json.dumps({
                            "photo_id": p.get("photo_encrypt_id"),
                            "duration_sec": p.get("duration_sec"),
                            "view_count": p.get("view_count"),
                            "like_count": p.get("like_count"),
                            "nickname": p.get("nickname"),
                        }, ensure_ascii=False),
                    ),
                )
                saved += 1
            except Exception as exc:
                log.error("[Collector] save %s failed: %s",
                          p.get("photo_encrypt_id"), exc)
        self.db.conn.commit()
        log.info("[Collector] saved %d photos to drama_links", saved)
        return saved

    # ------------------------------------------------------------------
    # One-shot orchestration
    # ------------------------------------------------------------------

    def collect_from_uids(
        self,
        target_user_ids: list[str],
        browser_account_pk: int,
        *,
        max_pages: int = 3,
        min_view: int | None = None,
        min_like: int | None = None,
        min_comment: int | None = None,
        min_duration_sec: int | None = None,
        with_share_link: bool = True,
        link_mode: str = "firefly",
    ) -> dict[str, Any]:
        """Full collection pipeline for a list of target UIDs.

        UI 过滤默认从 app_config 读 (None → config → 0/60).
        """
        # UI "过滤条件" 对齐 (截图 collector.filter.*)
        from core.app_config import get as _cg
        def _int(k, d):
            try: return int(_cg(k, d))
            except Exception: return d
        if min_view is None:
            min_view = _int("collector.filter.min_views", 0)
        if min_like is None:
            min_like = _int("collector.filter.min_likes", 0)
        if min_comment is None:
            min_comment = _int("collector.filter.min_comments", 0)
        if min_duration_sec is None:
            min_duration_sec = _int("collector.filter.min_duration_sec", 60)

        fetched = 0
        kept_after_filter = 0
        kept_after_dedup = 0
        saved = 0
        per_uid = {}

        for uid in target_user_ids:
            photos = self.fetch_profile_feed(uid, browser_account_pk, max_pages=max_pages)
            fetched += len(photos)
            per_uid[uid] = {"fetched": len(photos)}

            filtered = self.apply_filters(
                photos, min_view=min_view, min_like=min_like,
                min_comment=min_comment, min_duration_sec=min_duration_sec,
            )
            kept_after_filter += len(filtered)
            per_uid[uid]["filtered"] = len(filtered)

            if with_share_link:
                for p in filtered:
                    time.sleep(0.3)
                    info = self.generate_share_link(
                        p["photo_encrypt_id"], browser_account_pk,
                        title=p.get("caption", ""),
                        nickname=p.get("nickname", ""),
                        cover_url=p.get("cover_url", ""),
                    )
                    p["share_url"] = info.get("share_url", "")
                    p["kwai_token"] = info.get("kwai_token", "")

            deduped = self.filter_duplicates(filtered)
            kept_after_dedup += len(deduped)
            per_uid[uid]["deduped"] = len(deduped)

            n = self.save_to_drama_links(deduped, source_file=f"profile_feed:{uid}",
                                         link_mode=link_mode)
            saved += n
            per_uid[uid]["saved"] = n

        return {
            "uids": len(target_user_ids),
            "fetched_photos": fetched,
            "after_filters": kept_after_filter,
            "after_dedup": kept_after_dedup,
            "saved": saved,
            "per_uid": per_uid,
        }
