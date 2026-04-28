"""快手 API endpoint 常量（实测真实路径）

**全部已用真实 cookie 实测 HTTP 200 + 真实业务数据。**
"""
from __future__ import annotations


# ======== www.kuaishou.com (C 端公开) ========
WWW_BASE = "https://www.kuaishou.com"
WWW_GRAPHQL = f"{WWW_BASE}/graphql"

# REST 接口（v 系列）
WWW_PROFILE_GET = f"{WWW_BASE}/rest/v/profile/get"
WWW_PROFILE_FEED = f"{WWW_BASE}/rest/v/profile/feed"
WWW_PHOTO_COMMENT_LIST = f"{WWW_BASE}/rest/v/photo/comment/list"
WWW_FEED_HOT = f"{WWW_BASE}/rest/v/feed/hot"
WWW_SEARCH_FEED = f"{WWW_BASE}/rest/v/search/feed"
WWW_SEARCH_USER = f"{WWW_BASE}/rest/v/search/user"

# GraphQL operationNames（实测真实存在）
GQL_VISION_PROFILE = "visionProfile"
GQL_VISION_VIDEO_DETAIL = "visionVideoDetail"
GQL_VISION_SHORT_VIDEO_RECO = "visionShortVideoReco"
GQL_VISION_LOGIN_CONFIG = "visionLoginConfig"
GQL_CHECK_LOGIN = "checkLoginQuery"


# ======== cp.kuaishou.com (创作者中心) ========
CP_BASE = "https://cp.kuaishou.com"

# --- 用户信息 ---
CP_CREATOR_USER_INFO = "/rest/cp/creator/pc/home/userInfo"
CP_CREATOR_INFO_V2 = "/rest/cp/creator/pc/home/infoV2"
CP_COMMON_CURRENT_USER = "/rest/cp/works/v2/common/pc/current/user"
CP_AUTHORITY_ACCOUNT = "/rest/v2/creator/pc/authority/account/current"

# --- 数据分析 ---
CP_ANALYSIS_OVERVIEW = "/rest/cp/creator/analysis/pc/home/author/overview"
CP_ANALYSIS_PHOTO_LIST = "/rest/cp/creator/analysis/pc/home/photo/list"
CP_ANALYSIS_EXPORT_TASKS = "/rest/cp/creator/analysis/export/task/list"

# --- 视频/作品 ---
CP_PHOTO_LIST = "/rest/cp/works/v2/video/pc/home/photo/list"
CP_COLLECTION_TAB = "/rest/cp/works/v2/collection/tab"
CP_UPLOAD_CONFIG = "/rest/cp/works/v2/video/pc/upload/config"
CP_UPLOAD_TIPS = "/rest/cp/works/v2/video/pc/upload/tips/show"

# --- 收益 ---
CP_INCOME = "/rest/cp/creator/pc/home/income"

# --- 评论与互动 ---
CP_HOME_COMMENT_LIST = "/rest/cp/creator/pc/home/commentList"
CP_COMMENT_REPORT_MENU = "/rest/cp/creator/comment/report/menu"

# --- 通知/活动 ---
CP_NOTIF_UNREAD = "/rest/v2/creator/pc/notification/unReadCountV3"
CP_NOTIF_BANNER = "/rest/v2/creator/pc/notification/banner"
CP_POPUP_LIST = "/rest/v2/creator/pc/popup/list"
CP_ACTIVITY_HOME = "/rest/v2/creator/pc/activity/home/list"
CP_HOME_BANNER = "/rest/cp/creator/pc/home/banner/list"
CP_HOME_TASK_CARD_V2 = "/rest/cp/creator/pc/home/all/taskCardV2"

# --- 学院 ---
CP_SCHOOL_CATEGORY = "/rest/v2/creator/pc/school/category/tree"
CP_SCHOOL_RECOMMEND = "/rest/v2/creator/pc/school/course/recommend/v2/list"

# --- 素材/灵感 ---
CP_INSPIRATION_MATERIAL = "/rest/creator/v2/inspiration/pc/home/material/list"
CP_HOTSPOT_SHOW = "/rest/bamboo/pc/hotspot/show"
CP_EMOTION_LIST = "/rest/wd/pc/emotion/package/list"

# --- 配置 ---
CP_KSWITCH_CONFIG = "/rest/v2/creator/pc/frontend/kswitch/config"
CP_FE_KCONF = "/rest/cp/works/v2/common/pc/fe/kconf"
CP_KCONF_GET = "/rest/wd/kconf/get"


# ======== jigou.kuaishou.com (机构后台) ========
JIGOU_BASE = "https://jigou.kuaishou.com"

JIGOU_ACCOUNT_CURRENT = "/rest/account/pc/current"
JIGOU_ORG_LIST = "/rest/account/pc/index/org/list"
JIGOU_SETTLED_PRECHECK = "/rest/account/pc/org/settled/pre-check"
JIGOU_ESIGN_VALID = "/rest/account/pc/verify/eSign/company/isValid"
JIGOU_GUIDE_INITIAL = "/rest/cp/org/user-guide/initial"
JIGOU_SURVEY_AVAILABLE = "/rest/org/survey/available"
JIGOU_CUSTOM_CONFIG = "/rest/org-infra/custom-config/get/format"


# ======== 通用 HTTP headers ========
DEFAULT_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36"
)


def cp_headers() -> dict:
    return {
        "User-Agent": DEFAULT_USER_AGENT,
        "Content-Type": "application/json",
        "Accept": "application/json, text/plain, */*",
        "Origin": CP_BASE,
        "Referer": f"{CP_BASE}/",
        "X-Requested-With": "XMLHttpRequest",
        "Accept-Language": "zh-CN,zh;q=0.9",
    }


def jigou_headers() -> dict:
    return {
        "User-Agent": DEFAULT_USER_AGENT,
        "Content-Type": "application/json",
        "Accept": "application/json, text/plain, */*",
        "Origin": JIGOU_BASE,
        "Referer": f"{JIGOU_BASE}/",
        "X-Requested-With": "XMLHttpRequest",
        "Accept-Language": "zh-CN,zh;q=0.9",
    }


def www_headers() -> dict:
    return {
        "User-Agent": DEFAULT_USER_AGENT,
        "Content-Type": "application/json",
        "Accept": "*/*",
        "Origin": WWW_BASE,
        "Referer": f"{WWW_BASE}/",
        "X-Requested-With": "XMLHttpRequest",
        "Accept-Language": "zh-CN,zh;q=0.9",
    }
