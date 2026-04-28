"""快手 / MCN 集成层

依据 D:/APP2/docs/mcn_research/MCN_KUAISHOU_INTEGRATION_DICTIONARY.md 的实测产出
对接 cp.kuaishou.com / jigou.kuaishou.com / www.kuaishou.com 三个域。

使用：
    from app.integrations.kuaishou import KuaishouClient
    client = KuaishouClient.from_cookie_string(cookie_str)
    info = client.cp_creator_user_info()
    photos = client.cp_photo_list()
"""
from .client import KuaishouClient
from .cookie_jar import CookieJar, parse_cookie_string
from .errors import (
    KuaishouAPIError,
    KuaishouAuthError,
    KuaishouRateLimitError,
    KuaishouPermissionError,
)

__all__ = [
    "KuaishouClient",
    "CookieJar",
    "parse_cookie_string",
    "KuaishouAPIError",
    "KuaishouAuthError",
    "KuaishouRateLimitError",
    "KuaishouPermissionError",
]
