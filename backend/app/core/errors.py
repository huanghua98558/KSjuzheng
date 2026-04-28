"""统一错误码 + 业务异常体系.

对应蓝图: 后端开发技术文档与接口规范v1.md §2.3 错误码表.

设计原则:
  1. 所有客户端可见的 message 必须中文 + 用户可读
  2. 严禁返回堆栈 / SQL 错误原文 / 文件路径
  3. error.code 是稳定 API, 客户端依据 code 做行为决策
"""
from __future__ import annotations

from dataclasses import dataclass


# ============================================================
# 错误码表 (与文档 §2.3 一一对应)
# ============================================================

@dataclass(frozen=True)
class ErrorSpec:
    code: str
    http_status: int
    message: str       # 默认中文用户可读 message (实际可被 raise 时覆盖)
    hint: str | None = None


# ---- 鉴权 (4xx) ----
AUTH_401 = ErrorSpec("AUTH_401", 401, "登录已过期, 请重新登录", "点击右上角头像退出重登")
AUTH_402 = ErrorSpec("AUTH_402", 402, "您的套餐已到期, 请续费", "前往订阅中心")
AUTH_403 = ErrorSpec("AUTH_403", 403, "此功能需升级到高级版", "查看升级选项")
AUTH_423 = ErrorSpec("AUTH_423", 423, "账号已被锁定, 请联系客服", None)
AUTH_498 = ErrorSpec("AUTH_498", 498, "登录设备已变更, 请重新激活", "重新输入卡密")

# ---- 校验/资源/冲突 ----
VALIDATION_422 = ErrorSpec("VALIDATION_422", 422, "请求参数不正确, 请检查输入", None)
RESOURCE_404 = ErrorSpec("RESOURCE_404", 404, "请求的资源不存在", None)
CONFLICT_409 = ErrorSpec("CONFLICT_409", 409, "操作冲突, 请刷新后重试", None)
RATE_LIMIT_429 = ErrorSpec("RATE_LIMIT_429", 429, "请求过于频繁, 请稍后再试", None)

# ---- 服务器内部 ----
INTERNAL_500 = ErrorSpec("INTERNAL_500", 500, "服务器内部错误, 请稍后重试", None)
UPSTREAM_502 = ErrorSpec("UPSTREAM_502", 502, "上游服务暂时不可用", None)
MAINTENANCE_503 = ErrorSpec("MAINTENANCE_503", 503, "系统维护中", None)
GATEWAY_TIMEOUT_504 = ErrorSpec("GATEWAY_TIMEOUT_504", 504, "请求超时, 请重试", None)

# ---- 业务错误 (HTTP 200) ----
BUSINESS_NO_URL = ErrorSpec("BUSINESS_NO_URL", 200, "该剧暂无可用素材, 请稍后", "尝试更换其他剧")
BUSINESS_BLACKLIST = ErrorSpec("BUSINESS_BLACKLIST", 200, "该剧已被屏蔽, 无法发布", None)
BUSINESS_MCN_80004 = ErrorSpec(
    "BUSINESS_MCN_80004", 200, "账号暂无法发布该剧, 系统自动切换", None
)
BUSINESS_QUOTA_EXCEEDED = ErrorSpec(
    "BUSINESS_QUOTA_EXCEEDED", 200, "今日发布额度已用完", "查看剩余额度或续费"
)
BUSINESS_ACCOUNT_FROZEN = ErrorSpec(
    "BUSINESS_ACCOUNT_FROZEN", 200, "该账号已暂停, 请先解除", "前往账号详情解冻"
)
BUSINESS_INVALID_COOKIE = ErrorSpec(
    "BUSINESS_INVALID_COOKIE", 200, "账号登录状态已失效, 请重新登录", "触发重登"
)


# ============================================================
# 业务异常 — 统一抛出, 由 ExceptionHandler 转 envelope
# ============================================================

class BizError(Exception):
    """业务异常基类.

    用法:
        raise BizError(AUTH_401)
        raise BizError(BUSINESS_NO_URL, message="自定义中文 message", details={...})
    """

    def __init__(
        self,
        spec: ErrorSpec,
        *,
        message: str | None = None,
        hint: str | None = None,
        details: dict | None = None,
    ):
        self.spec = spec
        self.code = spec.code
        self.http_status = spec.http_status
        self.message = message or spec.message
        self.hint = hint or spec.hint
        self.details = details or {}
        super().__init__(self.message)


class AuthError(BizError):
    """鉴权类异常 (401/402/403/423/498)."""


class ValidationError(BizError):
    def __init__(self, message: str = VALIDATION_422.message, **kw):
        super().__init__(VALIDATION_422, message=message, **kw)


class ResourceNotFound(BizError):
    def __init__(self, message: str = RESOURCE_404.message, **kw):
        super().__init__(RESOURCE_404, message=message, **kw)


class ConflictError(BizError):
    def __init__(self, message: str = CONFLICT_409.message, **kw):
        super().__init__(CONFLICT_409, message=message, **kw)


class RateLimitError(BizError):
    def __init__(self, retry_after: int = 60, **kw):
        super().__init__(RATE_LIMIT_429, **kw)
        self.retry_after = retry_after


class InternalError(BizError):
    def __init__(self, message: str = INTERNAL_500.message, **kw):
        super().__init__(INTERNAL_500, message=message, **kw)


class UpstreamError(BizError):
    def __init__(self, message: str = UPSTREAM_502.message, **kw):
        super().__init__(UPSTREAM_502, message=message, **kw)
