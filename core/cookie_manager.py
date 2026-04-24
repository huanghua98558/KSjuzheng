# -*- coding: utf-8 -*-
"""Cookie validation and management for the 13 matrix Kuaishou accounts.

Scope: Kuaishou Creator Platform (cp.kuaishou.com) cookies for the matrix
accounts that publish videos. NOT to be confused with the MCN back-office
Bearer Token (that lives in .mcn_token.json and is handled by mcn_client).

Stored cookie JSON (top level, 7 cookie suites):
    cookies[]          — generic www.kuaishou.com cookies
    creator_cookie     — cp.kuaishou.com suite (publish, data, banner_task)
    shop_cookie        — kwaixiaodian.com (e-commerce)
    niu_cookie         — niu.e.kuaishou.com
    official_cookie    — official domain
    login_time         — ISO timestamp
    user_info          — profile dict
    login_method       — how it was logged in
"""

import json
import logging
from typing import Any

import requests

log = logging.getLogger(__name__)

# Validation endpoint: POST banner/list without __NS_sig3.
# Empirically confirmed to return ``result=1`` on a valid creator_cookie
# session and non-1 / error on stale/missing cookies. No api_ph or signature
# required, unlike the normal banner-task flow.
_VALIDATE_URL = (
    "https://cp.kuaishou.com/rest/cp/works/v2/video/pc/relation/banner/list"
)

_DEFAULT_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
    "Origin": "https://cp.kuaishou.com",
    "Referer": "https://cp.kuaishou.com/",
    "Content-Type": "application/json",
}

# Which top-level key matches which domain.
_DOMAIN_TO_KEY = {
    "cp": "creator_cookie",
    "shop": "shop_cookie",
    "niu": "niu_cookie",
    "official": "official_cookie",
}


def _cookies_array_to_str(cookie_list: list) -> str:
    """Convert a ``[{name, value}, ...]`` list to ``'k1=v1; k2=v2'`` format."""
    if not isinstance(cookie_list, list):
        return ""
    return "; ".join(
        f"{c['name']}={c['value']}"
        for c in cookie_list
        if isinstance(c, dict) and "name" in c and "value" in c
    )


class CookieManager:
    """Validate and manage Kuaishou CP cookies for the 13 matrix accounts."""

    def __init__(self, db_manager):
        self.db = db_manager

    # ------------------------------------------------------------------
    # Cookie extraction
    # ------------------------------------------------------------------

    def _load_cookie_json(self, account_id: int) -> dict:
        """Read and parse the raw cookie JSON blob for one account."""
        raw = self.db.get_account_cookies(account_id)
        if not raw:
            return {}
        if isinstance(raw, str):
            try:
                return json.loads(raw)
            except json.JSONDecodeError:
                return {}
        if isinstance(raw, dict):
            return raw
        if isinstance(raw, list):
            return {"cookies": raw}
        return {}

    def get_cookie_string(self, account_id: int, domain: str = "cp") -> str:
        """Return a ``Cookie:`` header string for the given target domain.

        Parameters
        ----------
        account_id : int
            Primary key from ``device_accounts.id``.
        domain : str
            One of ``'cp'`` (cp.kuaishou.com - default, for publish/data),
            ``'shop'``, ``'niu'``, ``'official'``, ``'main'`` (cookies[] only),
            or ``'all'`` (every suite merged, later keys win duplicates).

        Returns
        -------
        str
            ``"k1=v1; k2=v2"`` string, empty on failure.
        """
        try:
            data = self._load_cookie_json(account_id)
            if not data:
                return ""

            # List (old format) -> wrap as cookies[]
            if isinstance(data, list):
                return _cookies_array_to_str(data)

            if domain == "all":
                parts = []
                for key in ("creator_cookie", "shop_cookie", "niu_cookie", "official_cookie"):
                    if data.get(key):
                        parts.append(str(data[key]))
                main = _cookies_array_to_str(data.get("cookies") or [])
                if main:
                    parts.append(main)
                return "; ".join(p for p in parts if p)

            if domain == "main":
                return _cookies_array_to_str(data.get("cookies") or [])

            # cp/shop/niu/official
            key = _DOMAIN_TO_KEY.get(domain)
            if not key:
                log.warning("[CookieManager] Unknown domain=%s, falling back to 'cp'", domain)
                key = "creator_cookie"

            suite = data.get(key)
            if suite:
                return str(suite)

            # Fallback to cookies[] if the specific suite is missing.
            fallback = _cookies_array_to_str(data.get("cookies") or [])
            if fallback:
                log.debug(
                    "[CookieManager] account=%s domain=%s suite missing, using cookies[]",
                    account_id, domain,
                )
                return fallback

            return ""
        except Exception as exc:
            log.error("[CookieManager] get_cookie_string(account=%s, domain=%s) failed: %s",
                      account_id, domain, exc)
            return ""

    def get_api_ph(self, account_id: int) -> str:
        """Extract ``kuaishou.web.cp.api_ph`` from the stored cookie suite.

        The value can live either in ``cookies[]`` (as a dict) or be embedded
        directly in the ``creator_cookie`` string as ``kuaishou.web.cp.api_ph=...``.
        """
        try:
            data = self._load_cookie_json(account_id)
            if not data:
                return ""

            # 1. Prefer cookies[] list lookup.
            cookie_list = data.get("cookies") if isinstance(data, dict) else data
            if isinstance(cookie_list, list):
                for c in cookie_list:
                    if isinstance(c, dict) and c.get("name") == "kuaishou.web.cp.api_ph":
                        return c["value"]

            # 2. Fallback: parse creator_cookie string.
            creator = (data.get("creator_cookie") if isinstance(data, dict) else "") or ""
            for pair in creator.split(";"):
                pair = pair.strip()
                if pair.startswith("kuaishou.web.cp.api_ph="):
                    return pair.split("=", 1)[1]

            return ""
        except Exception as exc:
            log.error("[CookieManager] get_api_ph failed for account %s: %s", account_id, exc)
            return ""

    # ------------------------------------------------------------------
    # Validation
    # ------------------------------------------------------------------

    def validate_cookie(self, account_id: int) -> bool:
        """Test whether the cp.kuaishou.com cookie is still valid.

        Hits POST ``banner/list`` without signature. Empirically confirmed
        to respond ``result=1`` when the session is valid and non-1 when
        the cookie is stale. Cookie-only, no ``api_ph`` / ``__NS_sig3``.

        Side effect: on success, updates ``cookie_last_success_at`` in DB.
        """
        cookie_str = self.get_cookie_string(account_id, domain="cp")
        if not cookie_str:
            log.warning("[CookieManager] No cp cookie for account %s", account_id)
            return False

        headers = {**_DEFAULT_HEADERS, "Cookie": cookie_str}
        payload = {"type": 10, "title": "", "cursor": ""}
        try:
            resp = requests.post(_VALIDATE_URL, headers=headers, json=payload, timeout=10)
            try:
                data = resp.json()
            except (json.JSONDecodeError, ValueError):
                log.error("[CookieManager] account=%s non-JSON response (status=%d): %s",
                          account_id, resp.status_code, resp.text[:200])
                return False

            valid = data.get("result") == 1
            log.info(
                "[CookieManager] account=%s valid=%s result=%s msg=%s",
                account_id, valid, data.get("result"),
                data.get("error_msg") or data.get("message", ""),
            )
            if valid and hasattr(self.db, "mark_cookie_success"):
                try:
                    self.db.mark_cookie_success(account_id)
                except Exception as exc:
                    log.debug("[CookieManager] mark_cookie_success failed: %s", exc)
            return valid
        except requests.RequestException as exc:
            log.error("[CookieManager] Network error validating account %s: %s", account_id, exc)
            return False

    def validate_all_accounts(self) -> dict[str, bool]:
        """Validate cookies for every ``logged_in`` matrix account.

        Returns
        -------
        dict[str, bool]
            Mapping of ``account_name -> is_valid``.
        """
        results: dict[str, bool] = {}
        try:
            accounts = self.db.get_logged_in_accounts()
        except Exception as exc:
            log.error("[CookieManager] Failed to fetch accounts: %s", exc)
            return results

        for acct in accounts:
            account_id = acct.get("id")
            account_name = acct.get("account_name", str(account_id))
            try:
                results[account_name] = self.validate_cookie(account_id)
            except Exception as exc:
                log.error("[CookieManager] Error validating %s: %s", account_name, exc)
                results[account_name] = False

        valid_count = sum(1 for v in results.values() if v)
        log.info(
            "[CookieManager] Validation complete: %d/%d valid",
            valid_count, len(results),
        )
        return results
