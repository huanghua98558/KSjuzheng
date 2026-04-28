"""KS 集成错误类型."""


class KSError(Exception):
    """所有 KS 集成层错误的基类."""


class KSNetworkError(KSError):
    """网络层错误 (超时 / 连接失败 / DNS)."""


class KSCookieExpired(KSError):
    """Cookie 已失效 (result=109/116, 或网关 401).

    收到此错误的调用方应在调用 cookie_pool.mark_expired 后切下一条 cookie 重试.
    """


class KSRateLimited(KSError):
    """风控限流 (网关 result=2 + error_msg=null, 或 GraphQL 持续 result=2).

    调用方应退避 + 切 cookie.
    """


class KSDataError(KSError):
    """业务层错误 (作品被删 status=2 / 用户隐私 result=2 / 用户不存在 result=10 等).

    不重试, 不切 cookie, 直接向上抛.
    """

    def __init__(self, message: str, code: int | None = None):
        super().__init__(message)
        self.code = code


class KSSchemaError(KSError):
    """GraphQL schema 校验失败 (字段不存在 / fragment 写错).

    通常是代码问题, 不是 cookie 问题. 直接抛, 不重试.
    """
