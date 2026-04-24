# -*- coding: utf-8 -*-
"""Enhanced MCN client v3.0 -- extends the base libs.mcn_client with
additional MCN verification, invitation, and cloud-cookie management."""

import hashlib
import hmac
import json
import logging
import secrets
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional

import requests

log = logging.getLogger(__name__)

# ★ 2026-04-24 v6 Day 6: 迁到 core/secrets.py
# 老大写变量保留 (向后兼容). 未来可直接 `from core.secrets import get` 读.
try:
    from core.secrets import get as _sec_get, get_hmac_secret, get_mcn_response_secret
    MCN_BASE = "http://mcn.zhongxiangbao.com:88"    # MCN back-office 后台 (不同 host!)
    MCN_USER = _sec_get("KS_CAPTAIN_PHONE")
    MCN_PASS = _sec_get("KS_CAPTAIN_PASSWORD")
    OWNER_CODE = _sec_get("KS_CAPTAIN_OWNER_CODE")
    _HMAC_SECRET = get_hmac_secret()
    _MCN_RESPONSE_SECRET = get_mcn_response_secret()
except Exception:
    # secrets 模块未加载 (极端情况, 如初次部署) → 保历史
    MCN_BASE = "http://mcn.zhongxiangbao.com:88"
    MCN_USER = "REPLACE_WITH_YOUR_PHONE"
    MCN_PASS = "REPLACE_WITH_YOUR_PASSWORD"
    OWNER_CODE = "\u9ec4\u534e"
    _HMAC_SECRET = b"REPLACE_WITH_HMAC_SECRET"
    _MCN_RESPONSE_SECRET = b"REPLACE_WITH_MCN_RESP_SECRET"

TOKEN_FILE = Path(".mcn_token.json")


class MCNClient:
    """Full-featured MCN management client.

    Includes every method from ``libs.mcn_client.MCNClient`` plus
    enhanced endpoints for MCN verification, direct invitations,
    invitation records, and cloud-cookie CRUD.
    """

    def __init__(
        self,
        base: str = MCN_BASE,
        username: str = MCN_USER,
        password: str = MCN_PASS,
        owner_code: str = OWNER_CODE,
    ):
        self.base = base.rstrip("/")
        self.username = username
        self.password = password
        self.owner_code = owner_code
        self._token: Optional[str] = None
        self._token_exp: Optional[datetime] = None
        self._sess = requests.Session()
        self._sess.headers.update({
            "Content-Type": "application/json",
            "Accept": "application/json",
        })

    # ==================================================================
    # Authentication
    # ==================================================================

    @staticmethod
    def verify_credentials(username: str, password: str,
                           base: str = MCN_BASE, timeout: int = 10) -> dict:
        """无状态 credential 校验 (dashboard 登录用, 不污染 captain token 缓存).

        成功 → 返回 MCN user dict:
          {id, nickname, role, commission_rate, username, owner_code, ...}
        失败 → raise RuntimeError

        注意: 不写磁盘缓存, 不改 _token. 纯校验.
        """
        import requests as _req
        sess = _req.Session()
        sess.headers.update({
            "Content-Type": "application/json",
            "Accept": "application/json",
        })
        r = sess.post(
            f"{base.rstrip('/')}/api/auth/login",
            json={"username": username, "password": password},
            timeout=timeout,
        )
        if r.status_code != 200:
            raise RuntimeError(f"MCN login HTTP {r.status_code}: {r.text[:200]}")
        d = r.json()
        if not d.get("success"):
            raise RuntimeError(f"MCN login rejected: {d.get('message') or d}")
        data = d.get("data", {})
        user = data.get("user", {})
        if not user:
            raise RuntimeError(f"MCN login missing user info: {d}")
        # 也把 token + expires 暴露出去, 让调用方可选缓存
        user["_mcn_token"] = data.get("token", "")
        user["_mcn_expires_at"] = data.get("expires_at", "")
        return user

    def login(self, force: bool = False) -> str:
        if not force and self._token and self._token_exp:
            if datetime.now() < self._token_exp - timedelta(minutes=30):
                return self._token

        # Try cached token from disk
        if not force and TOKEN_FILE.exists():
            try:
                cached = json.loads(TOKEN_FILE.read_text(encoding="utf-8"))
                exp = datetime.fromisoformat(cached["expires_at"].replace("Z", ""))
                if datetime.now() < exp - timedelta(minutes=30):
                    self._token = cached["token"]
                    self._token_exp = exp
                    self._sess.headers["Authorization"] = f"Bearer {self._token}"
                    log.info("[MCN] Token cache valid, expires %s", exp.strftime("%m-%d %H:%M"))
                    return self._token
            except Exception:
                pass

        log.info("[MCN] Logging in...")
        r = self._sess.post(
            f"{self.base}/api/auth/login",
            json={"username": self.username, "password": self.password},
            timeout=10,
        )
        r.raise_for_status()
        d = r.json()
        if not d.get("success"):
            raise RuntimeError(f"Login failed: {d}")

        token = d["data"]["token"]
        exp = d["data"]["expires_at"]
        user = d["data"]["user"]
        self._token = token
        self._token_exp = datetime.fromisoformat(exp.replace("Z", ""))
        self._sess.headers["Authorization"] = f"Bearer {token}"
        TOKEN_FILE.write_text(
            json.dumps({"token": token, "expires_at": exp, "user": user}, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        log.info(
            "[MCN] Login OK: %s (%s) commission=%s%%",
            user["nickname"], user["role"], user["commission_rate"],
        )
        return token

    # ==================================================================
    # HTTP helpers
    # ==================================================================

    def _get(self, path: str, params: Optional[dict] = None):
        self.login()
        r = self._sess.get(f"{self.base}{path}", params=params, timeout=15)
        if r.status_code == 401:
            self.login(force=True)
            r = self._sess.get(f"{self.base}{path}", params=params, timeout=15)
        r.raise_for_status()
        return r.json()

    def _put(self, path: str, data: dict):
        self.login()
        r = self._sess.put(f"{self.base}{path}", json=data, timeout=15)
        if r.status_code == 401:
            self.login(force=True)
            r = self._sess.put(f"{self.base}{path}", json=data, timeout=15)
        r.raise_for_status()
        return r.json()

    def _post(self, path: str, data: dict):
        self.login()
        r = self._sess.post(f"{self.base}{path}", json=data, timeout=15)
        if r.status_code == 401:
            self.login(force=True)
            r = self._sess.post(f"{self.base}{path}", json=data, timeout=15)
        r.raise_for_status()
        return r.json()

    # ==================================================================
    # Account / Cookie management (from libs)
    # ==================================================================

    def get_my_accounts(self, page_size: int = 100) -> list[dict]:
        all_accounts: list[dict] = []
        page = 1
        while True:
            d = self._get(
                "/api/cloud-cookies",
                params={"owner_code": self.owner_code, "page": page, "pageSize": page_size},
            )
            batch = d.get("data", [])
            all_accounts.extend(batch)
            total = d.get("pagination", {}).get("total", len(all_accounts))
            if len(all_accounts) >= total or not batch:
                break
            page += 1
        log.info("[MCN] Total accounts: %d", len(all_accounts))
        return all_accounts

    def get_cookie_by_uid(self, uid) -> Optional[str]:
        for a in self.get_my_accounts():
            if str(a.get("kuaishou_uid", "")) == str(uid):
                return a.get("cookies")
        return None

    def update_cookie(self, account_id: int, new_cookie: str, kuaishou_name: str = "", remark: str = "") -> bool:
        payload: dict = {"cookies": new_cookie, "login_status": "logged_in"}
        if kuaishou_name:
            payload["kuaishou_name"] = kuaishou_name
        if remark:
            payload["remark"] = remark
        r = self._put(f"/api/cloud-cookies/{account_id}", payload)
        ok = r.get("success", False)
        log.info("[MCN] Cookie update %s: ID=%s", "OK" if ok else "FAIL", account_id)
        return ok

    def update_publish_stats(self, account_id: int, success: int = 0, fail: int = 0) -> bool:
        accounts = self.get_my_accounts()
        target = next((a for a in accounts if a["id"] == account_id), None)
        if not target:
            return False
        return self._put(f"/api/cloud-cookies/{account_id}", {
            "success_count": target.get("success_count", 0) + success,
            "fail_count": target.get("fail_count", 0) + fail,
        }).get("success", False)

    def get_all_operators(self) -> list[dict]:
        return self._get("/api/cloud-cookies/owner-codes").get("data", [])

    def batch_transfer_accounts(self, account_ids: list[int], new_owner_code: str) -> dict:
        return self._post("/api/cloud-cookies/batch-update-owner", {
            "ids": account_ids,
            "owner_code": new_owner_code,
        })

    # ==================================================================
    # Revenue data (from libs)
    # ==================================================================

    def get_firefly_members(self) -> dict:
        d = self._get("/api/firefly/members", params={"page": 1, "pageSize": 100})
        members = d.get("data", [])
        fans = sum(m.get("fans_count", 0) for m in members)
        income = sum(float(m.get("total_amount", 0)) for m in members)
        active = sum(1 for m in members if float(m.get("total_amount", 0)) > 0)
        log.info("[Firefly] %d members, fans=%d, income=%.2f", len(members), fans, income)
        return {
            "members": members,
            "total": d.get("total", 0),
            "total_fans": fans,
            "total_income": income,
            "active": active,
        }

    def get_firefly_income(self) -> dict:
        return self._get("/api/firefly/income", params={"page": 1, "pageSize": 100})

    def get_spark_members(self) -> dict:
        d = self._get("/api/spark/members", params={"page": 1, "pageSize": 100})
        return {"members": d.get("data", []), "total": d.get("total", 0)}

    def get_permissions(self) -> dict:
        return self._get("/api/auth/my-page-permissions")

    # ==================================================================
    # Kuaishou API cookie test (from libs)
    # ==================================================================

    def test_kuaishou_api(self, uid) -> dict:
        cookie = self.get_cookie_by_uid(uid)
        if not cookie:
            return {"success": False, "error": "Cookie not found"}
        headers = {
            "Cookie": cookie,
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/120.0.0.0 Safari/537.36"
            ),
            "Referer": "https://cp.kuaishou.com/",
            "Accept": "application/json",
        }
        for url in [
            "https://cp.kuaishou.com/rest/n/user/info",
            "https://cp.kuaishou.com/api/user/info",
        ]:
            try:
                r = requests.get(url, headers=headers, timeout=10)
                d = r.json()
                if d.get("result") == 1:
                    uinfo = d.get("user") or d.get("data") or {}
                    log.info("[Test] Cookie valid: %s", uinfo.get("name", uid))
                    return {"success": True, "uid": uid, "user_info": uinfo}
                return {"success": False, "uid": uid, "result": d.get("result"), "raw": d}
            except Exception:
                continue
        return {"success": False, "error": "All endpoints timed out"}

    # ==================================================================
    # Daily sync report (from libs)
    # ==================================================================

    def daily_sync(self) -> dict:
        log.info("[MCN] Daily sync: %s", datetime.now().strftime("%Y-%m-%d %H:%M"))
        accounts = self.get_my_accounts()
        logged_in = [a for a in accounts if a.get("login_status") == "logged_in"]
        api_ready = [a for a in logged_in if a.get("cookies")]
        no_device = [a for a in accounts if a.get("device_serial") == "no_device"]
        expiring: list[dict] = []
        for a in accounts:
            upd = a.get("updated_at", "")
            if upd:
                try:
                    days = (datetime.now() - datetime.fromisoformat(upd.replace("Z", ""))).days
                    if days > 25:
                        expiring.append({"name": a["account_name"], "uid": a["kuaishou_uid"], "days": days})
                except Exception:
                    pass
        firefly = self.get_firefly_members()
        spark = self.get_spark_members()
        report = {
            "timestamp": datetime.now().isoformat(),
            "owner": self.owner_code,
            "accounts": {
                "total": len(accounts),
                "logged_in": len(logged_in),
                "api_ready": len(api_ready),
                "no_device": len(no_device),
            },
            "cookie_health": {
                "ok": len(accounts) - len(expiring),
                "expiring_soon": len(expiring),
                "detail": expiring,
            },
            "firefly": {
                "members": firefly["total"],
                "total_fans": firefly["total_fans"],
                "total_income": firefly["total_income"],
                "active": firefly["active"],
            },
            "spark": {"members": spark["total"]},
        }
        acc = report["accounts"]
        ff = report["firefly"]
        ck = report["cookie_health"]
        print(f"\n{'---' * 17}")
        print(f"MCN Daily  {datetime.now().strftime('%Y-%m-%d')}")
        print(f"{'---' * 17}")
        print(
            f"Accounts: {acc['total']} | logged_in={acc['logged_in']} "
            f"| api_ready={acc['api_ready']} | no_device={acc['no_device']}"
        )
        print(
            f"Firefly: {ff['members']} members | fans={ff['total_fans']:,} "
            f"| income={ff['total_income']:.2f}"
        )
        if ck["expiring_soon"]:
            print(f"Cookie warning: {ck['expiring_soon']} accounts >25 days since update")
        print(f"{'---' * 17}\n")
        return report

    # ==================================================================
    # MCN binding check (CRITICAL: no binding = no revenue)
    # ==================================================================

    def get_all_bound_members(self) -> dict:
        """Get ALL members bound to our MCN (firefly + spark).

        Returns dict keyed by BOTH numeric member_id AND member_name:
            {member_id: {plan, name, ...}, member_name: {plan, name, ...}}
        This allows matching by either UID format or account name.
        """
        bound = {}

        # Firefly members
        try:
            ff = self.get_firefly_members()
            for m in ff.get("members", []):
                uid = str(m.get("member_id", m.get("userId", m.get("memberId", ""))))
                name = m.get("member_name", m.get("memberName", m.get("name", "")))
                info = {
                    "plan": "firefly",
                    "name": name,
                    "member_id": uid,
                    "fans": m.get("fans_count", 0),
                    "income": float(m.get("total_amount", 0)),
                    "status": "bound",
                }
                if uid:
                    bound[uid] = info
                if name:
                    bound[name] = info
        except Exception as exc:
            log.warning("[MCN] Failed to get firefly members: %s", exc)

        # Spark members
        try:
            sp = self.get_spark_members()
            for m in sp.get("members", []):
                uid = str(m.get("member_id", m.get("userId", m.get("memberId", ""))))
                name = m.get("member_name", m.get("memberName", m.get("name", "")))
                info = {
                    "plan": "spark",
                    "name": name,
                    "member_id": uid,
                    "status": "bound",
                }
                if uid and uid not in bound:
                    bound[uid] = info
                if name and name not in bound:
                    bound[name] = info
        except Exception as exc:
            log.warning("[MCN] Failed to get spark members: %s", exc)

        log.info("[MCN] Total bound members: %d entries (by id+name)", len(bound))
        return bound

    def check_account_bound(self, kuaishou_uid: str, account_name: str = "") -> dict:
        """Check if a specific account is bound to our MCN.

        Matches by numeric member_id, encrypted uid, OR account_name.

        Returns:
            {"bound": True/False, "plan": "firefly"/"spark"/None, "name": str, "member_id": str}

        CRITICAL: If bound=False, DO NOT publish — revenue won't come to us.
        """
        bound = self.get_all_bound_members()

        # Try matching by uid variants AND account name
        candidates = [kuaishou_uid, str(kuaishou_uid)]
        if account_name:
            candidates.append(account_name)

        for key in candidates:
            if key and key in bound:
                info = bound[key]
                log.info(
                    "[MCN] Account %s IS BOUND: plan=%s, member_id=%s",
                    account_name or kuaishou_uid, info["plan"], info.get("member_id", "?"),
                )
                return {"bound": True, "plan": info["plan"], "name": info["name"], "member_id": info.get("member_id", "")}

        log.warning("[MCN] Account %s (uid=%s) is NOT BOUND to our MCN!", account_name, kuaishou_uid)
        return {"bound": False, "plan": None, "name": "", "member_id": ""}

    def check_all_accounts_binding(self, db_manager) -> dict:
        """Check MCN binding status for ALL accounts in database.

        Matches by numeric member_id, encrypted uid, AND account_name.

        Returns:
            {account_name: {"uid": str, "bound": bool, "plan": str, "member_id": str}}
        """
        bound_members = self.get_all_bound_members()

        accounts = db_manager.get_logged_in_accounts()
        results = {}

        for acc in accounts:
            name = acc["account_name"]
            uid = acc.get("kuaishou_uid", "")
            # Try matching by uid, numeric uid, or account name
            is_bound = False
            plan = None
            member_id = ""
            for key in [uid, str(uid), name]:
                if key and key in bound_members:
                    is_bound = True
                    plan = bound_members[key].get("plan")
                    member_id = bound_members[key].get("member_id", "")
                    break

            results[name] = {"uid": uid, "bound": is_bound, "plan": plan, "member_id": member_id}
            status = f"BOUND({plan}, id={member_id})" if is_bound else "NOT BOUND"
            log.info("[MCN] %s (uid=%s): %s", name, uid, status)

        bound_count = sum(1 for v in results.values() if v["bound"])
        unbound_count = len(results) - bound_count
        log.info("[MCN] Binding summary: %d bound, %d NOT bound / %d total", bound_count, unbound_count, len(results))

        if unbound_count > 0:
            log.warning(
                "[MCN] UNBOUND accounts: %s",
                [k for k, v in results.items() if not v["bound"]],
            )

        return results

    # ==================================================================
    # MCN verification (signature-based)
    # ==================================================================

    @staticmethod
    def _generate_signature(uid: str, timestamp: str, nonce: str) -> str:
        """HMAC-SHA256 signature using the double-secret scheme.

        Captured behavior (Frida 2026-04-17):
            message   = f"{uid}:{timestamp}:{nonce}:{secret}"
            signature = HMAC_SHA256(key=secret, msg=message).hexdigest()
        """
        secret_str = _HMAC_SECRET.decode("utf-8")
        message = f"{uid}:{timestamp}:{nonce}:{secret_str}"
        return hmac.new(_HMAC_SECRET, message.encode("utf-8"), hashlib.sha256).hexdigest()

    def verify_mcn(self, uid: str, plan_mode: str = "firefly") -> dict:
        """Verify an account's MCN membership status.

        Parameters
        ----------
        uid : str
            Kuaishou user ID.
        plan_mode : str
            Plan type, e.g. ``"firefly"`` or ``"spark"``.

        Returns
        -------
        dict
            Server response with verification result.
        """
        timestamp = str(int(time.time()))
        nonce = secrets.token_hex(16)
        signature = self._generate_signature(uid, timestamp, nonce)

        payload = {
            "uid": uid,
            "timestamp": timestamp,
            "signature": signature,
            "nonce": nonce,
            "client_id": "kuaishou_control_v1",
            "plan_mode": plan_mode,
        }
        log.info("[MCN] verify_mcn uid=%s plan=%s", uid, plan_mode)
        # NOTE: /api/mcn/verify lives on a different host than the main MCN
        # back-office. Confirmed via Frida trace 2026-04-17 — the real URL
        # is http://im.zhongxiangbao.com:8000/api/mcn/verify.
        try:
            resp = self._sess.post(
                "http://im.zhongxiangbao.com:8000/api/mcn/verify",
                json=payload,
                timeout=15,
            )
            resp.raise_for_status()
            data = resp.json()
            log.info("[MCN] verify_mcn result: %s", data.get("success", "unknown"))
            return data
        except requests.RequestException as exc:
            log.error("[MCN] verify_mcn failed: %s", exc)
            return {"success": False, "error": str(exc)}

    # ==================================================================
    # NEW: Direct invitation
    # ==================================================================

    def direct_invite(
        self,
        user_id: str,
        phone_number: str,
        note: str,
        contract_month: int = 36,
        organization_id: int = 10,
    ) -> dict:
        """Send a direct MCN invitation to a creator.

        Parameters
        ----------
        user_id : str
            Target Kuaishou user ID.
        phone_number : str
            Creator's phone number.
        note : str
            Invitation message / note.
        contract_month : int
            Contract duration in months (default 36).
        organization_id : int
            MCN organization ID (default 10).

        Returns
        -------
        dict
            Server response.
        """
        payload = {
            "user_id": user_id,
            "phone_number": phone_number,
            "note": note,
            "contract_month": contract_month,
            "organization_id": organization_id,
        }
        log.info("[MCN] direct_invite user=%s phone=%s***", user_id, phone_number[:3])
        try:
            r = self._post("/api/accounts/direct-invite", payload)
            try:
                from core.event_bus import emit_event
                emit_event(
                    "mcn.invite_sent" if r.get("success") else "mcn.invite_fail",
                    entity_type="account", entity_id=str(user_id),
                    payload={"phone": phone_number[:3] + "***",
                             "contract_month": contract_month,
                             "response": r},
                    level="info" if r.get("success") else "warn",
                    source_module="mcn_client",
                )
            except Exception:
                pass
            return r
        except requests.RequestException as exc:
            log.error("[MCN] direct_invite failed: %s", exc)
            try:
                from core.event_bus import emit_event
                emit_event(
                    "mcn.invite_fail",
                    entity_type="account", entity_id=str(user_id),
                    payload={"error": str(exc)},
                    level="error", source_module="mcn_client",
                )
            except Exception:
                pass
            return {"success": False, "error": str(exc)}

    # ==================================================================
    # NEW: Invitation records
    # ==================================================================

    def get_invitation_records(self, user_id: str) -> list[dict]:
        """Retrieve invitation records for a given user.

        Parameters
        ----------
        user_id : str
            Kuaishou user ID whose invitation history to fetch.

        Returns
        -------
        list[dict]
            List of invitation record dicts.
        """
        log.info("[MCN] get_invitation_records user=%s", user_id)
        try:
            resp = self._post("/api/accounts/invitation-records", {"user_id": user_id})
            return resp.get("data", [])
        except requests.RequestException as exc:
            log.error("[MCN] get_invitation_records failed: %s", exc)
            return []

    # ==================================================================
    # NEW: Cloud cookie management
    # ==================================================================

    def get_cloud_cookies(self, owner_code: Optional[str] = None) -> list[dict]:
        """Fetch cloud-stored cookies, optionally filtered by owner.

        Parameters
        ----------
        owner_code : str, optional
            Filter by owner code. Defaults to ``self.owner_code``.

        Returns
        -------
        list[dict]
            List of cloud cookie records.
        """
        code = owner_code or self.owner_code
        log.info("[MCN] get_cloud_cookies owner=%s", code)
        try:
            return self._get("/api/cloud-cookies", params={"owner_code": code, "page": 1, "pageSize": 200}).get("data", [])
        except requests.RequestException as exc:
            log.error("[MCN] get_cloud_cookies failed: %s", exc)
            return []

    def update_cloud_cookie(self, cookie_id: int, cookie_data: dict) -> dict:
        """Update a specific cloud cookie record.

        Parameters
        ----------
        cookie_id : int
            The ID of the cloud cookie record to update.
        cookie_data : dict
            Fields to update (e.g. ``cookies``, ``login_status``,
            ``kuaishou_name``, ``remark``).

        Returns
        -------
        dict
            Server response.
        """
        log.info("[MCN] update_cloud_cookie id=%s keys=%s", cookie_id, list(cookie_data.keys()))
        try:
            return self._put(f"/api/cloud-cookies/{cookie_id}", cookie_data)
        except requests.RequestException as exc:
            log.error("[MCN] update_cloud_cookie failed: %s", exc)
            return {"success": False, "error": str(exc)}


# ==================================================================
# CLI entry point (same as libs version)
# ==================================================================

if __name__ == "__main__":
    import sys

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s", datefmt="%H:%M:%S")
    client = MCNClient()
    cmd = sys.argv[1] if len(sys.argv) > 1 else "daily"

    if cmd == "login":
        token = client.login(force=True)
        print(f"Token OK: {token[:40]}...")

    elif cmd == "accounts":
        for a in client.get_my_accounts():
            dev = (
                "NoDevice-API"
                if a["device_serial"] == "no_device"
                else ("Web" if str(a["device_serial"]).startswith("web_") else "Phone")
            )
            print(f"[{dev}] {a['account_name']:<25} UID={a['kuaishou_uid']:<20} status={a.get('login_status', '?')}")

    elif cmd == "income":
        ff = client.get_firefly_members()
        print(f"\nFirefly members ({ff['total']}):")
        for m in sorted(ff["members"], key=lambda x: x.get("fans_count", 0), reverse=True):
            print(f"  {m['member_name']:<25} fans={m.get('fans_count', 0):>8,}  income={float(m.get('total_amount', 0)):>8.2f}")

    elif cmd == "test":
        uid = sys.argv[2] if len(sys.argv) > 2 else None
        if uid:
            print(json.dumps(client.test_kuaishou_api(uid), ensure_ascii=False, indent=2))
        else:
            for a in client.get_my_accounts():
                r = client.test_kuaishou_api(a["kuaishou_uid"])
                mark = "OK" if r["success"] else "FAIL"
                print(f"[{mark}] {a['account_name']:<25} UID={a['kuaishou_uid']}")
                time.sleep(0.5)

    elif cmd == "verify":
        uid = sys.argv[2] if len(sys.argv) > 2 else None
        if uid:
            print(json.dumps(client.verify_mcn(uid), ensure_ascii=False, indent=2))
        else:
            print("Usage: mcn_client.py verify <uid>")

    elif cmd == "operators":
        for op in sorted(client.get_all_operators(), key=lambda x: x["count"], reverse=True):
            mark = " <-- you" if op["owner_code"] == OWNER_CODE else ""
            print(f"{op['owner_code']:<20} {op['count']:>4} accounts{mark}")

    else:
        report = client.daily_sync()
        print(json.dumps(report, ensure_ascii=False, indent=2))
