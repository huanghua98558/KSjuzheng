# -*- coding: utf-8 -*-
"""MCN business persistence layer.

Syncs the three audit trails we need for revenue-attribution / invitation
tracking:

    mcn_account_bindings   <- /api/cloud-cookies  (my captain-owned accounts)
    mcn_invitations        <- POST /api/accounts/direct-invite (local cert)
                              + /api/accounts/invitation-records (poll status)
    mcn_income_snapshots   <- /api/firefly/members + /api/firefly-external/income

All writes are idempotent (ON CONFLICT UPDATE), so the same snapshot script
can run hourly/daily without duplicating rows.
"""

from __future__ import annotations

import json
import logging
from datetime import date, datetime
from typing import Any

import requests

from core.mcn_client import MCN_BASE, MCNClient

log = logging.getLogger(__name__)


class MCNBusiness:
    """High-level MCN business operations with persistence."""

    def __init__(self, db_manager, mcn_client: MCNClient | None = None):
        self.db = db_manager
        self.mcn = mcn_client or MCNClient()
        self._token: str | None = None

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _headers(self) -> dict:
        if not self._token:
            self._token = self.mcn.login()
        return {
            "Authorization": f"Bearer {self._token}",
            "Accept": "application/json",
            "Content-Type": "application/json",
        }

    def _get(self, path: str, params: dict | None = None) -> dict:
        resp = requests.get(f"{MCN_BASE}{path}", headers=self._headers(),
                            params=params, timeout=10)
        return resp.json()

    def _post(self, path: str, body: dict | None = None) -> dict:
        resp = requests.post(f"{MCN_BASE}{path}", headers=self._headers(),
                             json=body, timeout=10)
        return resp.json()

    # ==================================================================
    # 1. Account bindings — /api/cloud-cookies
    # ==================================================================

    def sync_account_bindings(self) -> int:
        """Pull every captain-owned account from cloud-cookies → local table."""
        all_items: list[dict] = []
        page = 1
        while True:
            j = self._get("/api/cloud-cookies", {"page": page, "pageSize": 50})
            if not j.get("success"):
                log.error("[MCNBusiness] cloud-cookies page=%d failed: %s", page, j)
                break
            items = j.get("data") or []
            all_items.extend(items)
            # Pagination check: if we got < pageSize, we're done.
            if len(items) < 50:
                break
            page += 1

        synced = 0
        for it in all_items:
            uid = str(it.get("kuaishou_uid") or "")
            if not uid:
                continue
            # Find the firefly commission_rate for this account (cross-ref members)
            try:
                self.db.conn.execute(
                    """INSERT INTO mcn_account_bindings
                         (kuaishou_uid, account_name, member_id, owner_code,
                          commission_rate, plan_type, bound_at, last_verified_at,
                          raw_snapshot_json)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                       ON CONFLICT(kuaishou_uid) DO UPDATE SET
                         account_name = excluded.account_name,
                         member_id = excluded.member_id,
                         owner_code = excluded.owner_code,
                         last_verified_at = excluded.last_verified_at,
                         raw_snapshot_json = excluded.raw_snapshot_json""",
                    (
                        uid,
                        it.get("account_name") or it.get("kuaishou_name") or "",
                        int(uid) if uid.isdigit() else None,
                        it.get("owner_code") or "",
                        None,  # commission_rate filled by sync_members below
                        "firefly",  # default; overwritten by sync_members
                        it.get("created_at"),
                        datetime.now().isoformat(),
                        json.dumps(it, ensure_ascii=False),
                    ),
                )
                synced += 1
            except Exception as exc:
                log.error("[MCNBusiness] sync_account_bindings uid=%s: %s", uid, exc)
        self.db.conn.commit()
        log.info("[MCNBusiness] sync_account_bindings: %d rows", synced)
        try:
            from core.event_bus import emit_event
            emit_event(
                "mcn.bindings_synced",
                entity_type="mcn", entity_id="batch",
                payload={"synced_count": synced, "total_fetched": len(all_items)},
                source_module="mcn_business",
            )
        except Exception:
            pass
        return synced

    def sync_bindings_from_fluorescent(self) -> int:
        """★ 2026-04-22 §30: 从 MCN fluorescent_members (MySQL 直连) 拉本地账号绑定.

        背景: cloud-cookies 只列 captain-owned, 漏掉别的 captain 邀的账号.
        Fluorescent_members 是 MCN 全量实时成员表, 按 member_id=numeric_uid 查,
        拿所有真实已签账号 (不管谁邀的).

        流程:
          1. 本地 device_accounts.numeric_uid 列表
          2. MCN MySQL 查 fluorescent_members WHERE member_id IN (...)
          3. upsert mcn_account_bindings
        """
        import pymysql
        rows = self.db.conn.execute(
            "SELECT numeric_uid, account_name FROM device_accounts WHERE numeric_uid IS NOT NULL"
        ).fetchall()
        if not rows:
            log.info("[MCNBusiness] sync_from_fluorescent: no local accounts")
            return 0
        uid_list = [str(r[0]) for r in rows]
        name_map = {str(r[0]): r[1] for r in rows}

        # ★ 2026-04-24 v6 Day 6: 迁到 core/secrets.py
        try:
            from core.secrets import get_mcn_mysql_config
            mcn_cfg = get_mcn_mysql_config()
            # 覆盖默认 timeout (这里业务需要更长)
            mcn_cfg["connect_timeout"] = 10
            mcn_cfg["read_timeout"] = 30
        except Exception:
            mcn_cfg = dict(
                host="im.zhongxiangbao.com", port=3306,
                user="shortju", password="REPLACE_WITH_MCN_MYSQL_PASSWORD",
                database="shortju", charset="utf8mb4",
                connect_timeout=10, read_timeout=30,
            )
        try:
            conn = pymysql.connect(**mcn_cfg)
            cur = conn.cursor(pymysql.cursors.DictCursor)
            ph = ",".join(["%s"] * len(uid_list))
            cur.execute(
                f"""SELECT member_id, member_name, org_id, org_task_num,
                           total_amount, created_at, updated_at
                    FROM fluorescent_members WHERE member_id IN ({ph})""",
                uid_list,
            )
            fluo_rows = cur.fetchall()
            cur.close(); conn.close()
        except Exception as e:
            log.error("[MCNBusiness] sync_from_fluorescent MCN query failed: %s", e)
            return 0

        synced = 0
        for fr in fluo_rows:
            uid = str(fr["member_id"])
            try:
                self.db.conn.execute(
                    """INSERT INTO mcn_account_bindings
                         (kuaishou_uid, account_name, member_id, owner_code,
                          commission_rate, plan_type, bound_at, last_verified_at,
                          raw_snapshot_json)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                       ON CONFLICT(kuaishou_uid) DO UPDATE SET
                         account_name = excluded.account_name,
                         member_id = excluded.member_id,
                         last_verified_at = excluded.last_verified_at,
                         raw_snapshot_json = excluded.raw_snapshot_json""",
                    (
                        uid,
                        name_map.get(uid) or fr.get("member_name") or "",
                        int(uid) if uid.isdigit() else None,
                        "",
                        None,
                        "firefly",
                        str(fr.get("created_at") or ""),
                        datetime.now().isoformat(),
                        json.dumps({
                            "source": "fluorescent_members",
                            "member_name": fr.get("member_name"),
                            "org_id": fr.get("org_id"),
                            "org_task_num": fr.get("org_task_num"),
                            "total_amount": float(fr.get("total_amount") or 0),
                        }, ensure_ascii=False, default=str),
                    ),
                )
                synced += 1
            except Exception as e:
                log.error("[MCNBusiness] sync_from_fluorescent uid=%s: %s", uid, e)
        self.db.conn.commit()
        log.info("[MCNBusiness] sync_from_fluorescent: %d rows (from %d local accounts)",
                  synced, len(uid_list))
        return synced

    def sync_members(self) -> int:
        """Overlay firefly member info (commission_rate, fans_count) on bindings."""
        j = self._get("/api/firefly/members", {"page": 1, "page_size": 50})
        if not j.get("success"):
            log.error("[MCNBusiness] firefly/members failed: %s", j)
            return 0
        members = j.get("data") or []
        updated = 0
        for m in members:
            uid = str(m.get("member_id") or "")
            if not uid:
                continue
            try:
                self.db.conn.execute(
                    """UPDATE mcn_account_bindings SET
                         commission_rate = ?, plan_type = 'firefly',
                         member_id = ?,
                         last_verified_at = ?
                       WHERE kuaishou_uid = ?""",
                    (
                        float(m.get("user_commission_rate") or 0),
                        int(uid),
                        datetime.now().isoformat(),
                        uid,
                    ),
                )
                updated += 1
            except Exception as exc:
                log.error("[MCNBusiness] sync_members member=%s: %s", uid, exc)
        self.db.conn.commit()
        log.info("[MCNBusiness] sync_members: %d updated", updated)
        return updated

    # ==================================================================
    # 2. Invitations — local non-repudiation
    # ==================================================================

    def invite_and_persist(
        self,
        target_uid: str,
        phone: str,
        note: str = "",
        contract_month: int = 36,
        organization_id: int = 10,
    ) -> dict:
        """Send direct-invite and record a locally-auditable snapshot."""
        body = {
            "user_id": target_uid,
            "phone_number": phone,
            "phone_country_code": "+86",
            "note": note or f"{self.mcn.owner_code}-{self.mcn.username}",
            "auth_code": self.mcn.username,
            "contract_month": contract_month,
            "organization_id": organization_id,
        }
        resp = self._post("/api/accounts/direct-invite", body)
        invited_at = datetime.now().isoformat()
        try:
            self.db.conn.execute(
                """INSERT INTO mcn_invitations
                     (target_kuaishou_uid, target_phone, note, auth_code,
                      contract_month, organization_id,
                      invite_request_json, invite_response_json,
                      invited_at, server_timestamp, signed_status)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'pending')
                   ON CONFLICT(target_kuaishou_uid, auth_code) DO UPDATE SET
                     invite_request_json = excluded.invite_request_json,
                     invite_response_json = excluded.invite_response_json,
                     invited_at = excluded.invited_at""",
                (
                    target_uid, phone, body["note"], self.mcn.username,
                    contract_month, organization_id,
                    json.dumps(body, ensure_ascii=False),
                    json.dumps(resp, ensure_ascii=False),
                    invited_at,
                    str(resp.get("data", {}).get("currentTime", "")),
                ),
            )
            self.db.conn.commit()
        except Exception as exc:
            log.error("[MCNBusiness] invite_and_persist write failed: %s", exc)
        return resp

    def poll_invitation_status(self, target_uid: str) -> dict:
        """Check invitation status via invitation-records, update local row."""
        resp = self._post(
            "/api/accounts/invitation-records",
            {"user_id": target_uid, "auth_code": self.mcn.username},
        )
        # Server returns a list of records; pull latest
        records = resp.get("data") or []
        if not records:
            return resp
        latest = records[0]
        status_code = latest.get("recordProcessStatus")
        status_desc = latest.get("recordProcessStatusDesc") or ""
        signed = status_code == 104  # 104 = 邀约成功 per captured trace
        try:
            self.db.conn.execute(
                """UPDATE mcn_invitations SET
                     signed_status = ?,
                     signed_at = CASE WHEN ? THEN datetime('now','localtime') ELSE signed_at END,
                     member_id = ?,
                     last_polled_at = datetime('now','localtime')
                   WHERE target_kuaishou_uid = ? AND auth_code = ?""",
                (
                    "signed" if signed else status_desc,
                    signed,
                    latest.get("memberId"),
                    target_uid, self.mcn.username,
                ),
            )
            self.db.conn.commit()
        except Exception as exc:
            log.error("[MCNBusiness] poll_invitation_status write failed: %s", exc)
        return resp

    # ==================================================================
    # 3. Daily income snapshot
    # ==================================================================

    def snapshot_daily_income(
        self,
        start_date: str | None = None,
        end_date: str | None = None,
    ) -> int:
        """Record today's income per firefly member.

        Queries members list + per-member income, writes one snapshot row
        per (snapshot_date, member_id).
        """
        if start_date is None:
            start_date = date.today().replace(day=1).isoformat()
        if end_date is None:
            # End of month (30 is safe enough for monthly snapshot)
            d = date.today()
            end_date = d.replace(day=28).isoformat()

        # 1. Get member list
        j = self._get("/api/firefly/members", {"page": 1, "page_size": 50})
        members = j.get("data") or []

        today = date.today().isoformat()
        written = 0
        for m in members:
            member_id = m.get("member_id")
            if not member_id:
                continue
            # 2. Per-member income
            body = {
                "member_id": member_id,
                "start_date": start_date,
                "end_date": end_date,
                "page": 1,
                "count": 100,
                "org_id": m.get("org_id", 10),
                "auth_code": self.mcn.username,
            }
            income_resp = self._post("/api/firefly-external/income", body)
            total_amount = float(m.get("total_amount") or 0)
            commission_rate = float(m.get("user_commission_rate") or 0)
            commission_amount = total_amount * commission_rate / 100.0

            try:
                self.db.conn.execute(
                    """INSERT INTO mcn_income_snapshots
                         (snapshot_date, member_id, kuaishou_uid,
                          total_amount, commission_amount, commission_rate,
                          raw_response_json, captured_at)
                       VALUES (?, ?, ?, ?, ?, ?, ?, datetime('now','localtime'))
                       ON CONFLICT(snapshot_date, member_id) DO UPDATE SET
                         total_amount = excluded.total_amount,
                         commission_amount = excluded.commission_amount,
                         commission_rate = excluded.commission_rate,
                         raw_response_json = excluded.raw_response_json,
                         captured_at = excluded.captured_at""",
                    (
                        today, member_id, str(member_id),
                        total_amount, commission_amount, commission_rate,
                        json.dumps({"member": m, "income": income_resp}, ensure_ascii=False),
                    ),
                )
                written += 1
            except Exception as exc:
                log.error("[MCNBusiness] snapshot income member=%s: %s", member_id, exc)
        self.db.conn.commit()
        log.info("[MCNBusiness] snapshot_daily_income: %d rows", written)
        return written
