"""快手 GraphQL 集成模块 (KS / 快手主域).

设计:
  - 走 https://www.kuaishou.com/graphql,无需 sig3 签名
  - Cookie 池 = 自家 CloudCookieAccount + zhongxiangbao 公开池(过渡期)
  - 4 个核心查询: visionProfile / visionSearchPhoto / visionVideoDetail / 短链 302
  - 失败兜底: cookie 轮换 + 指数退避 + 风控降级
"""
from app.integrations.ks.client import KSClient, get_client
from app.integrations.ks.errors import (
    KSCookieExpired,
    KSDataError,
    KSNetworkError,
    KSRateLimited,
)

__all__ = [
    "KSClient",
    "get_client",
    "KSCookieExpired",
    "KSDataError",
    "KSNetworkError",
    "KSRateLimited",
]
