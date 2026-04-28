"""快手 GraphQL 客户端.

核心方法:
  - get_profile(uid_short)       → 用户档案
  - search_photo(keyword, ...)   → 关键词搜剧
  - get_video_detail(photo_id)   → 单作品详情
  - resolve_short_url(url)       → v.kuaishou.com 短链解析

容错:
  - 网络错误 → 退避重试 3 次
  - 风控/cookie 失效 → 自动切下一条 cookie 重试
  - schema 错误 → 直接抛 KSSchemaError (代码问题, 不该重试)
"""
from __future__ import annotations

import re
import time
from typing import Any
from urllib.parse import urlparse

import httpx

from app.core.logging import logger
from app.integrations.ks import cookie_pool, queries
from app.integrations.ks.errors import (
    KSCookieExpired,
    KSDataError,
    KSNetworkError,
    KSRateLimited,
    KSSchemaError,
)


GRAPHQL_URL = "https://www.kuaishou.com/graphql"
DEFAULT_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)
TIMEOUT = httpx.Timeout(15.0, connect=5.0)
SHORT_URL_RE = re.compile(r"https?://v\.kuaishou\.com/[A-Za-z0-9]+")


class KSClient:
    def __init__(self, db=None):
        self.db = db
        self._client = httpx.Client(timeout=TIMEOUT, follow_redirects=False)

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self._client.close()

    # ----------------------------------------------------------------
    # 内部: 发送 graphql, 自动 cookie 轮换 + 退避
    # ----------------------------------------------------------------
    def _post_graphql(
        self,
        op: str,
        variables: dict,
        query: str,
        *,
        referer: str | None = None,
        max_attempts: int = 3,
    ) -> dict:
        last_err: Exception | None = None
        for attempt in range(max_attempts):
            ck = cookie_pool.pick(self.db)
            if not ck:
                raise KSCookieExpired("池中无健康 cookie")

            headers = {
                "Content-Type": "application/json",
                "User-Agent": DEFAULT_UA,
                "Cookie": ck.cookie,
                "Origin": "https://www.kuaishou.com",
                "Referer": referer or "https://www.kuaishou.com/",
            }
            payload = {"operationName": op, "variables": variables, "query": query}

            try:
                resp = self._client.post(GRAPHQL_URL, headers=headers, json=payload)
            except httpx.RequestError as ex:
                last_err = KSNetworkError(f"网络错误: {ex!r}")
                logger.warning(
                    f"[ks.client] {op} 网络错误 (attempt={attempt+1}, "
                    f"cookie={ck.uid_short}): {ex}"
                )
                cookie_pool.mark_failed(ck)
                time.sleep(2 ** attempt)
                continue

            # 网关层的非 200 — 通常是 401/403/429/5xx
            if resp.status_code == 401:
                cookie_pool.mark_failed(ck, fatal=True, reason="HTTP 401")
                last_err = KSCookieExpired(f"401: cookie {ck.uid_short} 失效")
                continue
            if resp.status_code in (429, 503):
                cookie_pool.mark_failed(ck)
                last_err = KSRateLimited(f"{resp.status_code}: 风控限流")
                time.sleep(2 ** attempt)
                continue
            if resp.status_code >= 500:
                last_err = KSNetworkError(f"上游 {resp.status_code}")
                time.sleep(2 ** attempt)
                continue

            # 200 但响应可能是网关风控
            try:
                d = resp.json()
            except Exception:
                last_err = KSNetworkError("响应非 JSON")
                continue

            # 网关层风控: {"result": 2, "error_msg": null, "request_id": "..."}
            # 这种 envelope 没有 "data" key
            if "data" not in d and "errors" not in d:
                # 是网关层(quota/风控)拒绝
                gw_result = d.get("result")
                if gw_result in (2, 22, 23):
                    cookie_pool.mark_failed(ck, reason=f"gw result={gw_result}")
                    last_err = KSRateLimited(f"网关风控 result={gw_result} req={d.get('request_id')}")
                    time.sleep(2 ** attempt)
                    continue
                last_err = KSDataError(f"网关层异常: {d}")
                continue

            # GraphQL schema 错误 — 不重试
            if "errors" in d and d["errors"]:
                msgs = [e.get("message", "") for e in d["errors"][:3]]
                logger.error(f"[ks.client] {op} schema 错误: {msgs}")
                raise KSSchemaError(" | ".join(msgs))

            # 成功响应
            cookie_pool.mark_success(ck)
            return d

        # max_attempts 用尽
        raise last_err or KSNetworkError("max_attempts 用尽")

    # ----------------------------------------------------------------
    # 公开 API
    # ----------------------------------------------------------------
    def get_profile(self, uid_short: str) -> dict:
        """visionProfile 查档案. 返 userProfile 子对象 (含 ownerCount + profile)."""
        if not uid_short or not uid_short.startswith("3x"):
            raise KSDataError(f"uid 必须是 short 格式 (3xxxxx), got: {uid_short}", code=21)
        d = self._post_graphql(
            "visionProfile",
            {"userId": uid_short},
            queries.VISION_PROFILE,
            referer=f"https://www.kuaishou.com/profile/{uid_short}",
        )
        node = d.get("data", {}).get("visionProfile") or {}
        result = node.get("result")
        if result == 1:
            return node.get("userProfile") or {}
        # cookie 层失效:抛 KSCookieExpired (调用方可重试)
        if result in (109, 116):
            raise KSCookieExpired(f"visionProfile result={result}: cookie 失效")
        label, msg = queries.RESULT_CODE.get(result, ("unknown", "未知 code"))
        raise KSDataError(f"visionProfile result={result} ({label}: {msg})", code=result)

    def search_photo(
        self,
        keyword: str,
        *,
        pcursor: str = "",
        search_session_id: str = "",
    ) -> dict:
        """关键词搜剧. 返 {feeds, pcursor, searchSessionId, llsid}."""
        d = self._post_graphql(
            "visionSearchPhoto",
            {
                "keyword": keyword,
                "pcursor": pcursor,
                "searchSessionId": search_session_id,
            },
            queries.VISION_SEARCH_PHOTO,
            referer="https://www.kuaishou.com/search/video",
        )
        node = d.get("data", {}).get("visionSearchPhoto") or {}
        result = node.get("result")
        if result != 1:
            label, msg = queries.RESULT_CODE.get(result, ("unknown", "未知 code"))
            raise KSDataError(f"visionSearchPhoto result={result} ({label}: {msg})", code=result)
        return {
            "feeds": node.get("feeds") or [],
            "pcursor": node.get("pcursor"),
            "search_session_id": node.get("searchSessionId"),
            "llsid": node.get("llsid"),
        }

    def get_video_detail(self, photo_id: str) -> dict:
        """单作品详情. 返 {status, author, photo, tags, llsid}."""
        if not photo_id:
            raise KSDataError("photo_id 不能为空")
        d = self._post_graphql(
            "visionVideoDetail",
            {"photoId": photo_id, "page": "detail"},
            queries.VISION_VIDEO_DETAIL,
            referer=f"https://www.kuaishou.com/short-video/{photo_id}",
        )
        node = d.get("data", {}).get("visionVideoDetail") or {}
        status = node.get("status")
        if status != 1 and status is not None:
            label, msg = queries.VIDEO_STATUS.get(status, ("unknown", "未知 status"))
            raise KSDataError(f"visionVideoDetail status={status} ({label}: {msg})", code=status)
        return node

    def resolve_short_url(self, url: str) -> dict:
        """v.kuaishou.com 短链 → {photo_id, author_uid_short?, raw_location}.

        快手短链 302 跳到 chenzhongtech.com,Location 含 photoId / userId.
        """
        if not SHORT_URL_RE.match(url):
            # 非短链,可能本身就是 long URL
            m = re.search(r"/(?:short-video|long-video)/([a-zA-Z0-9]+)", url)
            if m:
                return {"photo_id": m.group(1), "author_uid_short": None, "raw_location": url}
            raise KSDataError(f"非快手短链: {url}")

        try:
            r = self._client.get(
                url,
                headers={"User-Agent": DEFAULT_UA},
                follow_redirects=False,
            )
        except httpx.RequestError as ex:
            raise KSNetworkError(f"短链解析网络错误: {ex}")

        if r.status_code != 302:
            raise KSDataError(f"短链非 302 (got {r.status_code}): {url}")

        loc = r.headers.get("Location") or ""
        photo_id_m = re.search(r"photoId=([a-zA-Z0-9]+)", loc)
        # userId in chenzhongtech location 是 short uid
        uid_m = re.search(r"userId=(3x[a-zA-Z0-9]+)", loc)

        if not photo_id_m:
            # fallback: 从路径里抠 (.../fw/long-video/<photoId>?...)
            path_m = re.search(r"/fw/(?:long|short|photo)-?video/([a-zA-Z0-9]+)", loc)
            if path_m:
                photo_id_m = path_m

        if not photo_id_m:
            raise KSDataError(f"短链 Location 无 photoId: {loc[:200]}")

        return {
            "photo_id": photo_id_m.group(1),
            "author_uid_short": uid_m.group(1) if uid_m else None,
            "raw_location": loc,
        }


# 全局客户端 (httpx.Client 是线程安全的)
_global: KSClient | None = None


def get_client() -> KSClient:
    """获取全局 KSClient 单例."""
    global _global
    if _global is None:
        _global = KSClient()
    return _global
