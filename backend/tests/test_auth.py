"""认证端点测试."""
from __future__ import annotations

import pytest
from sqlalchemy import select

from app.core.db import get_session_factory
from app.models import License


@pytest.fixture()
def admin_token(client):
    r = client.post(
        "/api/client/auth/login",
        json={"username": "admin", "password": "admin"},
    )
    assert r.status_code == 200
    j = r.json()
    assert j["ok"] is True
    return j["data"]["token"], j["data"]["refresh_token"]


def test_healthz(client):
    r = client.get("/healthz")
    assert r.status_code == 200
    assert r.json()["status"] == "ok"


def test_ping_envelope(client):
    r = client.get("/api/client/system/ping")
    j = r.json()
    assert j["ok"] is True
    assert "data" in j and "name" in j["data"]
    assert "meta" in j and len(j["meta"]["trace_id"]) >= 1


def test_login_wrong_password(client):
    r = client.post(
        "/api/client/auth/login",
        json={"username": "admin", "password": "wrong"},
    )
    assert r.status_code == 401
    j = r.json()
    assert j["ok"] is False
    assert j["error"]["code"] == "AUTH_401"


def test_login_ok(client, admin_token):
    token, _ = admin_token
    assert isinstance(token, str) and len(token) > 50


def test_me_with_token(client, admin_token):
    token, _ = admin_token
    r = client.get("/api/client/auth/me", headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 200
    assert r.json()["data"]["username"] == "admin"


def test_me_without_token_401(client):
    r = client.get("/api/client/auth/me")
    assert r.status_code == 401
    assert r.json()["error"]["code"] == "AUTH_401"


def test_heartbeat(client, admin_token):
    token, _ = admin_token
    r = client.post(
        "/api/client/auth/heartbeat",
        json={"fingerprint": None},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert r.status_code == 200
    assert r.json()["data"]["license_status"] in ("active", "expiring_soon")


def test_refresh(client, admin_token):
    token, refresh_token = admin_token
    r = client.post(
        "/api/client/auth/refresh",
        json={"refresh_token": refresh_token},
    )
    assert r.status_code == 200
    new_token = r.json()["data"]["token"]
    assert isinstance(new_token, str)
    assert new_token != token


def test_activate_with_demo_license(client):
    Session = get_session_factory()
    with Session() as db:
        L = db.execute(select(License).where(License.status == "unused").limit(1)).scalar_one_or_none()
    assert L is not None, "需要先 seed_demo_licenses"

    r = client.post(
        "/api/client/auth/activate",
        json={
            "license_key": L.license_key,
            "phone": "13800138001",
            "fingerprint": "a" * 64,
            "client_version": "1.0.0",
            "os_info": "Windows 10",
        },
    )
    assert r.status_code == 200
    data = r.json()["data"]
    assert "token" in data
    assert data["plan_tier"] in ("basic", "pro", "team")
    assert data["initial_password"] and len(data["initial_password"]) == 12


def test_activate_other_fingerprint_498(client):
    Session = get_session_factory()
    with Session() as db:
        L = db.execute(
            select(License).where(License.status == "unused").limit(1)
        ).scalar_one_or_none()
    assert L is not None

    # 第一次激活
    fp1 = "1" * 64
    r1 = client.post(
        "/api/client/auth/activate",
        json={
            "license_key": L.license_key,
            "phone": "13900139001",
            "fingerprint": fp1,
        },
    )
    assert r1.status_code == 200

    # 不同指纹再激活 → 498
    r2 = client.post(
        "/api/client/auth/activate",
        json={
            "license_key": L.license_key,
            "phone": "13700137001",
            "fingerprint": "9" * 64,
        },
    )
    assert r2.status_code == 498
    assert r2.json()["error"]["code"] == "AUTH_498"

    # 同指纹再激活 → 200 (idempotent)
    r3 = client.post(
        "/api/client/auth/activate",
        json={
            "license_key": L.license_key,
            "phone": "13900139001",
            "fingerprint": fp1,
        },
    )
    assert r3.status_code == 200


def test_logout_revokes_sessions(client, admin_token):
    token, refresh = admin_token
    r = client.post(
        "/api/client/auth/logout",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert r.status_code == 200
    assert r.json()["data"]["logged_out"] is True

    # logout 后 refresh 应失败
    r2 = client.post("/api/client/auth/refresh", json={"refresh_token": refresh})
    assert r2.status_code == 401


def test_validation_error(client):
    """缺字段 → 422 + VALIDATION_422."""
    r = client.post("/api/client/auth/login", json={})
    assert r.status_code == 422
    assert r.json()["error"]["code"] == "VALIDATION_422"
