"""KuaishouClient: 单 cookie 视角的快手三域统一客户端。

特性：
  - 自动处理 cp.kuaishou.com 的隐式签名（body 注入 api_ph）
  - 区分 personal / org cookie，调用前预检
  - 错误码自动转 KuaishouAPIError
  - 内置 RateLimiter（默认 www 25/min, cp 60/min）
  - 重试：指数退避 + 限流后等 Retry-After

使用：
    from app.integrations.kuaishou import KuaishouClient
    client = KuaishouClient.from_cookie_string(cookie_str)

    # 快手用户基础信息
    user = client.cp_creator_user_info()
    # data: {"coreUserInfo": {"userName": "看看短剧", ...}}

    # 已发布视频列表
    videos = client.cp_photo_list()

    # 数据总览
    overview = client.cp_analysis_overview(time_type=1)

    # 收益
    income = client.cp_income()

    # www 公开 GraphQL
    profile = client.www_vision_profile(user_id="3xqpap3wpucy4sc")
"""
from __future__ import annotations

import logging
import random
import time
from typing import Any, Optional

import requests

from . import endpoints as ep
from .cookie_jar import CookieJar
from .errors import (
    KuaishouAPIError,
    KuaishouAuthError,
    KuaishouRateLimitError,
    map_result_to_error,
)
from .rate_limiter import RateLimiter


log = logging.getLogger(__name__)


class KuaishouClient:
    def __init__(
        self,
        jar: CookieJar,
        *,
        timeout: int = 15,
        cp_rate_limit: int = 60,
        www_rate_limit: int = 25,
        max_retries: int = 3,
    ):
        self.jar = jar
        self.timeout = timeout
        self.max_retries = max_retries
        self._cp_limiter = RateLimiter(cp_rate_limit, 60)
        self._www_limiter = RateLimiter(www_rate_limit, 60)
        self._session = requests.Session()
        self._session.cookies.update(jar.to_requests_cookies())

    # ---------------- 工厂 ----------------
    @classmethod
    def from_cookie_string(cls, cookie_str: str, **kwargs) -> "KuaishouClient":
        return cls(CookieJar.from_string(cookie_str), **kwargs)

    # ---------------- 底层调用 ----------------
    def _post_cp(self, path: str, body: Optional[dict] = None) -> dict:
        if not self.jar.api_ph:
            raise KuaishouAuthError("cookie 缺 kuaishou.web.cp.api_ph", result_code=109)
        body = dict(body or {})
        body["kuaishou.web.cp.api_ph"] = self.jar.api_ph
        url = f"{ep.CP_BASE}{path}"
        return self._do_request("POST", url, body=body, headers=ep.cp_headers(), limiter=self._cp_limiter)

    def _post_jigou(self, path: str, body: Optional[dict] = None) -> dict:
        body = dict(body or {})
        if self.jar.api_ph:
            body["kuaishou.web.cp.api_ph"] = self.jar.api_ph
        url = f"{ep.JIGOU_BASE}{path}"
        return self._do_request("POST", url, body=body, headers=ep.jigou_headers(), limiter=self._cp_limiter)

    def _post_www(self, path: str, body: Optional[dict] = None) -> dict:
        url = f"{ep.WWW_BASE}{path}"
        return self._do_request("POST", url, body=body, headers=ep.www_headers(), limiter=self._www_limiter)

    def _post_graphql(self, operation_name: str, variables: dict, query: str) -> dict:
        payload = {"operationName": operation_name, "variables": variables, "query": query}
        return self._do_request("POST", ep.WWW_GRAPHQL, body=payload, headers=ep.www_headers(),
                                  limiter=self._www_limiter, _is_graphql=True)

    def _do_request(self, method: str, url: str, *, body: Any = None, headers: Optional[dict] = None,
                     limiter: Optional[RateLimiter] = None, _is_graphql: bool = False) -> dict:
        if limiter:
            limiter.acquire()
        last_exc = None
        for attempt in range(self.max_retries):
            try:
                resp = self._session.request(
                    method, url, json=body, headers=headers, timeout=self.timeout, allow_redirects=False,
                )

                # HTTP 级错误
                if resp.status_code == 429:
                    retry_after = int(resp.headers.get("Retry-After", 30))
                    log.warning(f"快手限流 429, retry_after={retry_after}s url={url}")
                    if attempt < self.max_retries - 1:
                        time.sleep(retry_after)
                        continue
                    raise KuaishouRateLimitError("HTTP 429", http_status=429, url=url)
                if resp.status_code in (401, 403):
                    raise KuaishouAuthError(f"HTTP {resp.status_code}", http_status=resp.status_code, url=url)
                if resp.status_code >= 500:
                    if attempt < self.max_retries - 1:
                        wait = (2 ** attempt) + random.random()
                        log.warning(f"快手 5xx 重试 attempt={attempt+1} wait={wait:.1f}s")
                        time.sleep(wait)
                        continue
                    raise KuaishouAPIError(f"HTTP {resp.status_code}", http_status=resp.status_code, url=url,
                                            response_body=resp.text[:500])

                # 解析 JSON
                try:
                    data = resp.json()
                except Exception as e:
                    raise KuaishouAPIError(f"非 JSON 响应: {e}", http_status=resp.status_code,
                                            url=url, response_body=resp.text[:500]) from e

                # GraphQL 错误优先
                if _is_graphql:
                    if "errors" in data and data["errors"]:
                        msg = data["errors"][0].get("message", "graphql error")[:120]
                        if "Need captcha" in msg:
                            raise KuaishouRateLimitError(msg, result_code=500002, url=url, response_body=resp.text[:500])
                        raise KuaishouAPIError(f"GraphQL: {msg}", url=url, response_body=resp.text[:500])
                    return data

                # REST 错误码
                rc = data.get("result")
                if rc and rc != 1:
                    msg = data.get("message") or data.get("error_id") or ""
                    raise map_result_to_error(rc, msg, http_status=resp.status_code, url=url,
                                                 response_body=str(data)[:500])
                return data

            except (requests.ConnectionError, requests.Timeout) as e:
                last_exc = e
                if attempt < self.max_retries - 1:
                    time.sleep((2 ** attempt) + random.random())
                    continue
                raise KuaishouAPIError(f"网络错误: {e}", url=url) from e

        if last_exc:
            raise KuaishouAPIError(f"重试耗尽: {last_exc}", url=url) from last_exc
        raise KuaishouAPIError("未知错误", url=url)

    # ===================== cp.kuaishou.com 业务 API =====================

    def cp_creator_user_info(self) -> dict:
        """当前创作者信息（昵称/UID/粉丝数/头像）"""
        return self._post_cp(ep.CP_CREATOR_USER_INFO)

    def cp_creator_info_v2(self) -> dict:
        """主页详细统计"""
        return self._post_cp(ep.CP_CREATOR_INFO_V2)

    def cp_authority_account(self) -> dict:
        """账号开关 + 权限"""
        return self._post_cp(ep.CP_AUTHORITY_ACCOUNT)

    def cp_analysis_overview(self, time_type: int = 1) -> dict:
        """数据总览（时间类型：1=近 7 天 / 2=近 30 天）"""
        return self._post_cp(ep.CP_ANALYSIS_OVERVIEW, {"timeType": time_type})

    def cp_analysis_photo_list(self, page: int = 0, count: int = 15) -> dict:
        """作品分析列表"""
        return self._post_cp(ep.CP_ANALYSIS_PHOTO_LIST, {"page": page, "count": count})

    def cp_photo_list(self) -> dict:
        """已发布视频列表"""
        return self._post_cp(ep.CP_PHOTO_LIST)

    def cp_collection_tab(self) -> dict:
        """作品集 Tab"""
        return self._post_cp(ep.CP_COLLECTION_TAB)

    def cp_upload_config(self) -> dict:
        """上传配置（最大尺寸/格式）"""
        return self._post_cp(ep.CP_UPLOAD_CONFIG)

    def cp_income(self) -> dict:
        """当前账号收益（response: {data: {income, banance}}）"""
        return self._post_cp(ep.CP_INCOME)

    def cp_home_comment_list(self) -> dict:
        """我作品的评论列表"""
        return self._post_cp(ep.CP_HOME_COMMENT_LIST)

    def cp_notif_unread(self) -> dict:
        """未读消息数"""
        return self._post_cp(ep.CP_NOTIF_UNREAD)

    def cp_activity_home(self, page: int = 1, count: int = 12, sort_type: int = 0,
                          unclaimed: bool = False, reward_type: int = 0,
                          tag_type: int = 0, page_source: int = 1, category: int = 0) -> dict:
        """活动/任务列表"""
        return self._post_cp(ep.CP_ACTIVITY_HOME, {
            "page": page, "count": count, "sortType": sort_type,
            "unclaimed": unclaimed, "rewardType": reward_type,
            "tagType": tag_type, "pageSource": page_source, "category": category,
        })

    def cp_inspiration_material(self, category_id: int = -1, pcursor: str = "") -> dict:
        """灵感素材"""
        return self._post_cp(ep.CP_INSPIRATION_MATERIAL, {"categoryId": category_id, "pcursor": pcursor})

    def cp_kconf_get(self, key: str, type_: str = "json") -> dict:
        """动态拿一个配置 key"""
        return self._post_cp(ep.CP_KCONF_GET, {"key": key, "type": type_})

    # ===================== jigou.kuaishou.com 机构后台 =====================

    def jigou_account_current(self) -> dict:
        """账号在机构平台的身份"""
        return self._post_jigou(ep.JIGOU_ACCOUNT_CURRENT, {"path": "/"})

    def jigou_org_list(self) -> dict:
        """所属机构列表"""
        return self._post_jigou(ep.JIGOU_ORG_LIST)

    def jigou_settled_precheck(self) -> dict:
        """入驻预检"""
        return self._post_jigou(ep.JIGOU_SETTLED_PRECHECK)

    # ===================== www.kuaishou.com C 端公开 =====================

    def www_vision_profile(self, user_id: str) -> dict:
        """公开用户资料（任意 uid，不需要本人 cookie）"""
        return self._post_graphql(
            ep.GQL_VISION_PROFILE,
            {"userId": user_id},
            "query visionProfile($userId: String) { visionProfile(userId: $userId) { result userProfile { profile { user_id user_name headurl user_text gender } ownerCount { fan photo follow } isFollowing } } }",
        )

    def www_vision_video_detail(self, photo_id: str, type_: str = "DOMAIN_NEW",
                                  page: str = "", web_page_area: str = "") -> dict:
        """视频详情"""
        return self._post_graphql(
            ep.GQL_VISION_VIDEO_DETAIL,
            {"photoId": photo_id, "type": type_, "page": page, "webPageArea": web_page_area},
            "query visionVideoDetail($photoId: String, $type: String, $page: String, $webPageArea: String) "
            "{ visionVideoDetail(photoId: $photoId, type: $type, page: $page, webPageArea: $webPageArea) "
            "{ status type author { id name following headerUrl } "
            "photo { id duration caption likeCount realLikeCount coverUrl photoUrl timestamp expTag } } }",
        )

    # ===================== 验证 =====================

    def verify_cookie(self) -> dict:
        """快速验证 cookie 是否仍然有效。

        返回：{
          "valid": bool,
          "cookie_kind": "personal"|"org"|"unknown",
          "user_id": str,
          "user_name": str,
          "fans_num": int,
          "raw": <userInfo response>,
        }
        """
        result = {
            "valid": False,
            "cookie_kind": self.jar.kind,
            "user_id": self.jar.user_id,
            "user_name": None,
            "fans_num": None,
            "error": None,
        }
        try:
            resp = self.cp_creator_user_info()
            ci = resp.get("data", {}).get("coreUserInfo", {}) if isinstance(resp, dict) else {}
            result["valid"] = True
            result["user_name"] = ci.get("userName")
            result["fans_num"] = ci.get("fansNum")
            result["raw"] = ci
        except KuaishouAuthError as e:
            result["error"] = e.user_facing_message
        except KuaishouAPIError as e:
            result["error"] = e.user_facing_message
        return result
