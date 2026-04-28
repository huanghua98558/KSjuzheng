"""快手 API 错误码体系（实测）"""
from __future__ import annotations


# 实测错误码字典
KUAISHOU_RESULT_CODES = {
    1: "成功",
    109: "未登录 / cookie 失效",
    530: "没有权限",
    500002: "风控触发（C 端）",
    560: "非组织账号",
}


class KuaishouAPIError(Exception):
    """快手 API 调用基类异常"""

    def __init__(self, message: str, *, result_code: int = 0, http_status: int = 0,
                  url: str = "", response_body: str = ""):
        self.message = message
        self.result_code = result_code
        self.http_status = http_status
        self.url = url
        self.response_body = response_body
        super().__init__(self.user_facing_message)

    @property
    def user_facing_message(self) -> str:
        """中文友好消息（按 APP2 红线 5：不暴露原始堆栈）"""
        rc = self.result_code
        if rc == 109:
            return "快手账号登录已失效，请重新上传 cookie"
        if rc == 530:
            return "当前账号权限不足，无法访问该功能"
        if rc == 500002:
            return "操作过于频繁，请稍后重试"
        if rc == 560:
            return "该账号未加入机构后台"
        if self.http_status == 429:
            return "请求过于频繁，请稍后重试"
        if self.http_status == 0:
            return f"网络错误：{self.message}"
        return f"快手接口异常 (code={rc})"


class KuaishouAuthError(KuaishouAPIError):
    """Cookie 失效专用（result=109）"""


class KuaishouRateLimitError(KuaishouAPIError):
    """风控/限流专用（HTTP 429 或 result=500002）"""


class KuaishouPermissionError(KuaishouAPIError):
    """权限不足（result=530）"""


def map_result_to_error(result_code: int, message: str = "", **kwargs) -> KuaishouAPIError:
    """把 quaishou result code 映射到对应异常"""
    if result_code == 109:
        return KuaishouAuthError(message or "Cookie 失效", result_code=109, **kwargs)
    if result_code == 530:
        return KuaishouPermissionError(message or "权限不足", result_code=530, **kwargs)
    if result_code == 500002:
        return KuaishouRateLimitError(message or "风控触发", result_code=500002, **kwargs)
    if result_code == 560:
        return KuaishouPermissionError(message or "非组织账号", result_code=560, **kwargs)
    return KuaishouAPIError(message or KUAISHOU_RESULT_CODES.get(result_code, f"unknown result={result_code}"),
                              result_code=result_code, **kwargs)
