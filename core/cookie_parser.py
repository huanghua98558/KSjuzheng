# -*- coding: utf-8 -*-
"""统一 cookie 解析器 — 支持所有主流格式, 分 7 suite 存储.

支持格式:
  1. 字符串: "name=value; name=value; ..."
  2. Chrome 扩展导出 JSON 数组 (EditThisCookie / Cookie-Editor / Playwright):
     [{"name":..., "value":..., "domain":..., "path":..., "expirationDate":...,
       "httpOnly":..., "secure":..., "sameSite":...}]
  3. Netscape cookie file (TSV, '# Netscape' 开头)
  4. Python dict name→value

输出到 device_accounts.cookies JSON (符合 CookieManager 规范):
  {
    "cookies": [{"name", "value", "domain", "path", ...}],   # www.kuaishou.com 主站
    "creator_cookie":  "k=v; k=v",   # cp.kuaishou.com
    "shop_cookie":     "...",         # cps.kuaishou.com / kwaixiaodian.com
    "niu_cookie":      "...",         # niu.kuaishou.com
    "official_cookie": "...",         # 其他 kuaishou 子域
    "login_time":      "2026-04-17T...",
    "login_method":    "cookie_import" | "browser_login" | "qr_scan",
    "user_info":       {"userId", "userName", ...}
  }
"""
from __future__ import annotations

import json
import re
from datetime import datetime
from typing import Any


# ---------------------------------------------------------------------------
# 识别阶段
# ---------------------------------------------------------------------------

def detect_format(raw: Any) -> str:
    """识别 cookie 的格式."""
    if raw is None:
        return "empty"
    if isinstance(raw, list):
        return "json_array"
    if isinstance(raw, dict):
        return "dict"
    if not isinstance(raw, str):
        return "unknown"

    s = raw.strip()
    if not s:
        return "empty"
    if s.startswith("[") or (s.startswith("{") and "name" in s and "value" in s):
        # 尝试 JSON
        try:
            parsed = json.loads(s)
            if isinstance(parsed, list):
                return "json_array"
            if isinstance(parsed, dict):
                return "dict"
        except Exception:
            pass
    if s.startswith("# Netscape") or "\tTRUE\t" in s or "\tFALSE\t" in s:
        return "netscape"
    if "=" in s and ";" in s:
        return "string"
    if "=" in s:
        return "string"
    return "unknown"


# ---------------------------------------------------------------------------
# 解析为 list of dicts
# ---------------------------------------------------------------------------

def _parse_string(s: str) -> list[dict]:
    out = []
    for pair in s.split(";"):
        pair = pair.strip()
        if "=" not in pair:
            continue
        name, _, value = pair.partition("=")
        out.append({"name": name.strip(), "value": value.strip()})
    return out


def _parse_json_array(arr: list) -> list[dict]:
    out = []
    for item in arr:
        if not isinstance(item, dict):
            continue
        if not item.get("name") or item.get("value") is None:
            continue
        c = {"name": item["name"], "value": str(item["value"])}
        for k in ("domain", "path", "httpOnly", "secure", "sameSite"):
            if k in item:
                c[k] = item[k]
        if "expirationDate" in item:
            c["expires"] = int(item["expirationDate"])
        elif "expires" in item:
            try:
                c["expires"] = int(item["expires"])
            except Exception:
                pass
        out.append(c)
    return out


def _parse_netscape(s: str) -> list[dict]:
    out = []
    for line in s.split("\n"):
        if not line or line.startswith("#"):
            continue
        parts = line.split("\t")
        if len(parts) < 7:
            continue
        domain, flag, path, secure, expires, name, value = parts[:7]
        c = {
            "name": name, "value": value,
            "domain": domain.lstrip("."),
            "path": path,
            "secure": secure.upper() == "TRUE",
        }
        try:
            c["expires"] = int(expires)
        except Exception:
            pass
        out.append(c)
    return out


def _parse_dict(d: dict) -> list[dict]:
    # {name: value} 的简单 dict (不是 Chrome 导出格式)
    if "name" in d and "value" in d:
        return _parse_json_array([d])
    return [{"name": k, "value": str(v)} for k, v in d.items()]


def parse_cookies(raw: Any) -> list[dict]:
    """统一入口 — 返回 cookie dict 数组."""
    fmt = detect_format(raw)
    if fmt == "empty" or fmt == "unknown":
        return []
    if fmt == "json_array":
        arr = raw if isinstance(raw, list) else json.loads(raw)
        return _parse_json_array(arr)
    if fmt == "dict":
        d = raw if isinstance(raw, dict) else json.loads(raw)
        return _parse_dict(d)
    if fmt == "netscape":
        return _parse_netscape(raw)
    if fmt == "string":
        return _parse_string(raw)
    return []


# ---------------------------------------------------------------------------
# 域名分类 → 7 suite
# ---------------------------------------------------------------------------

def classify_suite(cookie: dict) -> str:
    """返回该 cookie 属于哪个 suite: cp/shop/niu/official/main/unknown"""
    domain = (cookie.get("domain") or "").lstrip(".").lower()
    name = (cookie.get("name") or "").lower()
    if not domain:
        # 没 domain 信息 — 启发式: 特定 cookie name
        if name in ("userid", "kuaishou.server.web_st", "kuaishou.server.webid_ph"):
            return "main"
        if name.startswith("kuaishou.web.cp.") or name == "kuaishou.web.cp.api_ph":
            return "cp"
        return "unknown"

    if "cp.kuaishou.com" in domain:
        return "cp"
    if "cps.kuaishou.com" in domain or "kwaixiaodian" in domain or "shop" in domain:
        return "shop"
    if "niu.e.kuaishou.com" in domain or "niu.kuaishou" in domain:
        return "niu"
    # 其他 kuaishou 子域
    if "kuaishou.com" in domain:
        # www.kuaishou / live.kuaishou / 主站
        if domain in ("kuaishou.com", "www.kuaishou.com"):
            return "main"
        return "official"
    return "unknown"


def _cookies_to_header_string(cookies: list[dict]) -> str:
    return "; ".join(
        f"{c['name']}={c['value']}"
        for c in cookies
        if c.get("name") and c.get("value") is not None
    )


# ---------------------------------------------------------------------------
# 构建最终入库 JSON
# ---------------------------------------------------------------------------

def build_account_cookies_json(
    raw: Any,
    *,
    login_method: str = "cookie_import",
    user_info: dict | None = None,
) -> dict:
    """输入原始 cookie (任何格式), 输出 device_accounts.cookies 规范 JSON."""
    cookies = parse_cookies(raw)
    if not cookies:
        return {}

    by_suite: dict[str, list[dict]] = {
        "cp": [], "shop": [], "niu": [], "official": [], "main": [], "unknown": [],
    }
    for c in cookies:
        by_suite[classify_suite(c)].append(c)

    # 没 domain 提示的 cookie 全部作为主站补充
    main_pool = by_suite["main"] + by_suite["unknown"]

    result = {
        "cookies": main_pool,           # 主站 cookies[] 保存完整结构 (CookieManager 读这里)
        "creator_cookie": _cookies_to_header_string(by_suite["cp"] + main_pool),
        "shop_cookie":    _cookies_to_header_string(by_suite["shop"] + main_pool),
        "niu_cookie":     _cookies_to_header_string(by_suite["niu"] + main_pool),
        "official_cookie":_cookies_to_header_string(by_suite["official"] + main_pool),
        "login_time":     datetime.now().isoformat(timespec="seconds"),
        "login_method":   login_method,
        "user_info":      user_info or {},
    }
    return result


# ---------------------------------------------------------------------------
# 从 JSON 提取 userId (给 device_accounts.kuaishou_uid 用)
# ---------------------------------------------------------------------------

def extract_user_id(raw: Any) -> str:
    """从 cookie 中提取 userId (数字格式). 返回空字符串表示未找到."""
    cookies = parse_cookies(raw)
    for c in cookies:
        if c.get("name") == "userId":
            return str(c.get("value") or "")
    # 次选: userid (小写)
    for c in cookies:
        if (c.get("name") or "").lower() == "userid":
            return str(c.get("value") or "")
    # 再次选: 在 creator_cookie 里 kuaishou.web.cp.api_ph 解码 (太复杂, 先跳过)
    return ""


# ---------------------------------------------------------------------------
# 预览: 给前端展示解析结果
# ---------------------------------------------------------------------------

def preview(raw: Any) -> dict:
    """给前端一个 cookie 分析预览."""
    cookies = parse_cookies(raw)
    by_suite: dict[str, int] = {
        "cp": 0, "shop": 0, "niu": 0, "official": 0, "main": 0, "unknown": 0,
    }
    for c in cookies:
        by_suite[classify_suite(c)] += 1
    names = [c.get("name") for c in cookies]
    key_cookies = [n for n in ["userId", "passToken", "kuaishou.web.cp.api_ph",
                               "kuaishou.server.web_st", "kuaishou.server.web.at"]
                   if n in names]
    return {
        "format": detect_format(raw),
        "cookie_count": len(cookies),
        "by_suite": by_suite,
        "user_id": extract_user_id(raw),
        "has_key_cookies": key_cookies,
        "missing_key_cookies": [n for n in ["userId", "passToken",
                                            "kuaishou.web.cp.api_ph"]
                                if n not in names],
        "cookie_names_sample": names[:20],
    }
