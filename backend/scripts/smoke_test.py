"""端到端冒烟测试 — 不需要外部 server, 用 TestClient 直接打.

测试场景:
  1. /healthz
  2. /api/client/system/ping
  3. /api/client/auth/login (admin / admin)
  4. /api/client/auth/me  (带 token)
  5. /api/client/auth/heartbeat
  6. /api/client/auth/refresh
  7. /api/client/auth/activate (用演示卡密)
"""
from __future__ import annotations

import json
import sys
from datetime import datetime

from fastapi.testclient import TestClient


def main():
    # 把 bendi 加到 sys.path
    from pathlib import Path
    bendi = Path(__file__).resolve().parent.parent
    sys.path.insert(0, str(bendi))

    # init DB if not yet
    from app.core.db import init_engine, get_session_factory
    from app.models import License, User
    from sqlalchemy import select

    init_engine()

    # 确保 DB 已经建表 + seed
    from scripts.init_db import create_all, seed_permissions, seed_roles, seed_admin, seed_demo_licenses
    create_all()
    Session = get_session_factory()
    with Session() as db:
        # check admin
        admin = db.execute(select(User).where(User.username == "admin")).scalar_one_or_none()
        if not admin:
            print("[seed] missing admin, seeding...")
            seed_permissions(db)
            seed_roles(db)
            seed_admin(db)
            seed_demo_licenses(db)
            db.commit()

    from app.main import app
    client = TestClient(app)

    failures = []

    def check(name: str, ok: bool, detail: str = ""):
        mark = "✓" if ok else "✗"
        print(f"  {mark} {name}  {detail}")
        if not ok:
            failures.append((name, detail))

    print("\n=== /healthz ===")
    r = client.get("/healthz")
    check("healthz status", r.status_code == 200, f"http={r.status_code}")
    check("healthz payload", r.json().get("status") == "ok")

    print("\n=== /api/client/system/ping ===")
    r = client.get("/api/client/system/ping")
    check("ping status", r.status_code == 200)
    j = r.json()
    check("ping envelope.ok", j.get("ok") is True)
    check("ping data.name", "name" in (j.get("data") or {}))
    check("ping meta.trace_id", len(j.get("meta", {}).get("trace_id", "")) >= 1)

    print("\n=== /api/client/auth/login (admin/admin) ===")
    r = client.post(
        "/api/client/auth/login",
        json={"username": "admin", "password": "admin"},
    )
    check("login status", r.status_code == 200, f"http={r.status_code}")
    j = r.json()
    check("login ok", j.get("ok") is True, f"err={j.get('error')}")
    token = (j.get("data") or {}).get("token")
    refresh_token = (j.get("data") or {}).get("refresh_token")
    check("login token", isinstance(token, str) and len(token) > 50)

    print("\n=== /api/client/auth/me ===")
    r = client.get("/api/client/auth/me", headers={"Authorization": f"Bearer {token}"})
    check("me status", r.status_code == 200)
    j = r.json()
    check("me.username == admin", (j.get("data") or {}).get("username") == "admin")

    print("\n=== /api/client/auth/me without token (expect 401) ===")
    r = client.get("/api/client/auth/me")
    check("me 401", r.status_code == 401)
    j = r.json()
    check("me 401 envelope.ok=false", j.get("ok") is False)
    check("me 401 error.code=AUTH_401", j.get("error", {}).get("code") == "AUTH_401")

    print("\n=== /api/client/auth/heartbeat ===")
    r = client.post(
        "/api/client/auth/heartbeat",
        headers={"Authorization": f"Bearer {token}"},
        json={"fingerprint": None},
    )
    check("heartbeat status", r.status_code == 200)
    j = r.json()
    check("heartbeat license_status",
          (j.get("data") or {}).get("license_status") in ("active", "expiring_soon"))

    print("\n=== /api/client/auth/refresh ===")
    r = client.post(
        "/api/client/auth/refresh",
        json={"refresh_token": refresh_token},
    )
    check("refresh status", r.status_code == 200)
    j = r.json()
    new_token = (j.get("data") or {}).get("token")
    check("refresh new_token", isinstance(new_token, str) and new_token != token)

    print("\n=== /api/client/auth/activate (用演示卡密) ===")
    # 找一张 unused (取首张)
    with Session() as db:
        L = db.execute(
            select(License).where(License.status == "unused").limit(1)
        ).scalar_one_or_none()
    if L:
        fake_fp = "a" * 64
        r = client.post(
            "/api/client/auth/activate",
            json={
                "license_key": L.license_key,
                "phone": "13800138000",
                "fingerprint": fake_fp,
                "client_version": "1.0.0",
                "os_info": "Windows 10",
            },
        )
        check("activate status", r.status_code == 200, f"http={r.status_code}")
        j = r.json()
        check("activate ok", j.get("ok") is True, f"err={j.get('error')}")
        data = j.get("data") or {}
        check("activate token", "token" in data)
        check("activate plan_tier", data.get("plan_tier") in ("basic", "pro", "team"))
        check("activate user.phone", (data.get("user") or {}).get("phone") == "13800138000")
        check("activate initial_password",
              isinstance(data.get("initial_password"), str)
              and len(data.get("initial_password")) == 12)

        # 重激活同卡 + 同指纹 → 应该成功 (idempotent)
        r2 = client.post(
            "/api/client/auth/activate",
            json={
                "license_key": L.license_key,
                "phone": "13800138000",
                "fingerprint": fake_fp,
            },
        )
        check("activate reactivate status", r2.status_code == 200)
        check("activate reactivate ok", r2.json().get("ok") is True)

        # 不同指纹激活 → AUTH_498
        r3 = client.post(
            "/api/client/auth/activate",
            json={
                "license_key": L.license_key,
                "phone": "13900139000",
                "fingerprint": "b" * 64,
            },
        )
        check("activate other-fp 498",
              r3.status_code == 498 and r3.json().get("error", {}).get("code") == "AUTH_498")
    else:
        print("  (跳过 activate — 无演示卡密)")

    print(f"\n=== 完成: 通过 {6 - len(failures) > 0} ===")
    if failures:
        print(f"❌ 失败 {len(failures)} 项:")
        for n, d in failures:
            print(f"  - {n}: {d}")
        sys.exit(1)
    print("✅ 全部通过")


if __name__ == "__main__":
    main()
