"""快手 cookie 解析 + 关键字段提取。

输入：浏览器 Cookie 字符串 (可能带空格、引号、`Cookie:` 前缀)
输出：CookieJar 对象，提供：
  - dict 形式访问  ck["userId"]
  - 序列化回 cookie 字符串
  - 提取 api_ph (cp.kuaishou.com 隐式签名字段)
  - 判断 cookie 类型 (org / personal)
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional


# 必备字段定义（实测）
PERSONAL_COOKIE_REQUIRED = {
    "userId",
    "bUserId",
    "did",
    "kuaishou.web.cp.api_st",
    "kuaishou.web.cp.api_ph",
    "passToken",
    "kuaishou.server.webday7_st",
    "kuaishou.server.webday7_ph",
}

ORG_COOKIE_REQUIRED = {
    "userId",
    "bUserId",
    "did",
    "kuaishou.web.cp.api_st",
    "kuaishou.web.cp.api_ph",
}


def parse_cookie_string(raw: str) -> dict:
    """把 'Cookie: a=1; b=2' / 'a=1;b=2' / '{"a":"1"}' 等格式转 dict."""
    if not raw:
        return {}
    raw = raw.strip()
    # 去掉 'Cookie:' 前缀
    if raw.lower().startswith("cookie:"):
        raw = raw[7:].strip()
    out = {}
    for part in raw.split(";"):
        part = part.strip()
        if not part or "=" not in part:
            continue
        name, _, value = part.partition("=")
        name = name.strip()
        value = value.strip()
        # 去外层引号
        if (value.startswith('"') and value.endswith('"')) or (value.startswith("'") and value.endswith("'")):
            value = value[1:-1]
        if name:
            out[name] = value
    return out


@dataclass
class CookieJar:
    """封装快手 cookie 的便利对象."""

    raw: str
    fields: dict

    @classmethod
    def from_string(cls, raw: str) -> "CookieJar":
        return cls(raw=raw, fields=parse_cookie_string(raw))

    @property
    def user_id(self) -> Optional[str]:
        return self.fields.get("userId")

    @property
    def b_user_id(self) -> Optional[str]:
        return self.fields.get("bUserId")

    @property
    def api_ph(self) -> Optional[str]:
        """cp.kuaishou.com 隐式签名值（直接从 cookie 复制到 body）."""
        return self.fields.get("kuaishou.web.cp.api_ph")

    @property
    def api_st(self) -> Optional[str]:
        return self.fields.get("kuaishou.web.cp.api_st")

    @property
    def pass_token(self) -> Optional[str]:
        return self.fields.get("passToken")

    @property
    def did(self) -> Optional[str]:
        return self.fields.get("did")

    @property
    def kind(self) -> str:
        """识别 cookie 类型：personal / org / unknown."""
        keys = set(self.fields.keys())
        if PERSONAL_COOKIE_REQUIRED.issubset(keys):
            return "personal"
        if ORG_COOKIE_REQUIRED.issubset(keys):
            return "org"
        return "unknown"

    @property
    def can_access_cp_business(self) -> bool:
        """是否能访问 cp.kuaishou.com 业务页（必须有 passToken + 5 套 token）"""
        return self.kind == "personal"

    @property
    def can_access_www_graphql(self) -> bool:
        """www.kuaishou.com/graphql 公开接口最低要求"""
        return bool(self.user_id and (self.api_st or self.fields.get("kuaishou.server.web_st")))

    def to_cookie_string(self) -> str:
        """重新序列化为 Cookie header 值."""
        return "; ".join(f"{k}={v}" for k, v in self.fields.items())

    def to_requests_cookies(self) -> dict:
        """给 requests.session.cookies 用的 dict."""
        return dict(self.fields)

    def __repr__(self) -> str:
        return f"<CookieJar kind={self.kind} user_id={self.user_id} fields={len(self.fields)}>"
