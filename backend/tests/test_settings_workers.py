"""Sprint 2D 测试 — AES-GCM / 公告 / 系统配置 / Worker."""
from __future__ import annotations

import pytest
from sqlalchemy import select

from app.core.crypto import HAS_CRYPTO, decrypt_str, encrypt_str
from app.core.db import get_session_factory
from app.models import CloudCookieAccount


def login(client, username: str, password: str) -> str:
    r = client.post("/api/client/auth/login",
                    json={"username": username, "password": password})
    assert r.status_code == 200
    return r.json()["data"]["token"]


def H(t: str) -> dict:
    return {"Authorization": f"Bearer {t}"}


@pytest.fixture
def admin_token(client):
    return login(client, "admin", "admin")


@pytest.fixture
def operator_token(client):
    return login(client, "op_demo", "demo")


@pytest.fixture
def normal_token(client):
    return login(client, "user_demo", "demo")


# ============================================================
# AES-GCM 真加密
# ============================================================

def test_has_crypto_installed():
    assert HAS_CRYPTO is True, "cryptography 必须装上, 否则 Cookie 仅 base64"


def test_aes_gcm_round_trip():
    plain = "userId=887329560; passToken=secret-very-long-password-1234567890"
    ct, iv, tag, preview = encrypt_str(plain)
    assert len(iv) == 12
    assert len(tag) == 16
    assert plain.encode() not in ct  # 明文不出现在密文
    back = decrypt_str(ct, iv, tag)
    assert back == plain
    assert "***" in preview


def test_aes_gcm_iv_random():
    """同 plain 加密 2 次, iv 应不同 (即 ciphertext 也不同)."""
    plain = "test cookie"
    ct1, iv1, _, _ = encrypt_str(plain)
    ct2, iv2, _, _ = encrypt_str(plain)
    assert iv1 != iv2
    assert ct1 != ct2


def test_aes_gcm_tamper_detected():
    """改 1 byte ciphertext, decrypt 应失败."""
    from cryptography.exceptions import InvalidTag
    plain = "tamper test"
    ct, iv, tag, _ = encrypt_str(plain)
    bad_ct = bytes([ct[0] ^ 0xff]) + ct[1:]
    with pytest.raises(InvalidTag):
        decrypt_str(bad_ct, iv, tag)


def test_seeded_cookie_decrypts_via_reveal(client, admin_token):
    """seed 的 cookie 用 reveal 端点应能拿真明文."""
    Session = get_session_factory()
    with Session() as db:
        c = db.execute(
            select(CloudCookieAccount).where(CloudCookieAccount.uid == "887329560").limit(1)
        ).scalar_one_or_none()
    assert c is not None, "seed 应有加密 Cookie"

    r = client.get(f"/api/client/cloud-cookies/{c.id}/reveal", headers=H(admin_token))
    assert r.status_code == 200, r.text
    plain = r.json()["data"]["cookie_plaintext"]
    assert "passToken=secret-eyJxxxxxxxxxxxx" in plain


# ============================================================
# 公告
# ============================================================

def test_list_announcements_admin(client, admin_token):
    r = client.get("/api/client/announcements", headers=H(admin_token))
    assert r.status_code == 200
    items = r.json()["data"]["items"]
    assert len(items) >= 3


def test_announcements_active_endpoint(client, normal_token):
    """所有用户都能看 /active (无 require_perm)."""
    r = client.get("/api/client/announcements/active", headers=H(normal_token))
    assert r.status_code == 200, r.text
    items = r.json()["data"]
    assert isinstance(items, list)
    assert len(items) >= 1
    # 第一条应 pinned (维护通知)
    assert items[0]["pinned"] is True


def test_normal_cant_create_announcement(client, normal_token):
    r = client.post("/api/client/announcements", headers=H(normal_token),
                    json={"title": "x", "content": "y"})
    assert r.status_code == 403


def test_operator_create_org_announcement(client, operator_token):
    r = client.post(
        "/api/client/announcements",
        headers=H(operator_token),
        json={"title": "演示团队公告", "content": "本周冲业绩!", "level": "info"},
    )
    assert r.status_code == 200, r.text
    a = r.json()["data"]
    # operator 不可发全平台公告 - service 自动改成 organization_id=本机构
    assert a["organization_id"] is not None


def test_operator_cant_modify_global_announcement(client, operator_token):
    """全平台公告 (organization_id=None) 仅 super_admin 可改."""
    r0 = client.get("/api/client/announcements", headers=H(operator_token))
    items = r0.json()["data"]["items"]
    global_ann = next((a for a in items if a["organization_id"] is None), None)
    if not global_ann:
        pytest.skip("无全平台公告")

    r = client.put(
        f"/api/client/announcements/{global_ann['id']}",
        headers=H(operator_token),
        json={"title": "操你"},
    )
    assert r.status_code == 403


# ============================================================
# 系统配置
# ============================================================

def test_settings_basic_admin(client, admin_token):
    r = client.get("/api/client/settings/basic", headers=H(admin_token))
    assert r.status_code == 200
    s = r.json()["data"]
    assert s["app_name"] == "KSJuzheng-Backend"
    assert s["has_crypto"] is True
    assert "***" in s["db_url_masked"] or s["db_url_masked"].startswith("sqlite")


def test_settings_basic_operator_403(client, operator_token):
    """settings:view-basic 仅 super_admin."""
    r = client.get("/api/client/settings/basic", headers=H(operator_token))
    assert r.status_code == 403


def test_settings_about_anyone(client, normal_token):
    r = client.get("/api/client/settings/about", headers=H(normal_token))
    assert r.status_code == 200
    info = r.json()["data"]
    assert info["name"] == "KSJuzheng-Backend"


def test_role_defaults_admin(client, admin_token):
    r = client.get("/api/client/settings/role-defaults", headers=H(admin_token))
    assert r.status_code == 200, r.text
    s = r.json()["data"]
    assert "items" in s
    assert "role_summary" in s
    assert s["role_summary"].get("super_admin", {}).get("page", 0) >= 20


def test_role_defaults_update_invalidates_cache(client, admin_token):
    r = client.put(
        "/api/client/settings/role-defaults",
        headers=H(admin_token),
        json={
            "role": "captain",
            "page_codes": ["dashboard:view", "account:view"],
            "button_codes": ["account:edit"],
        },
    )
    assert r.status_code == 200, r.text
    j = r.json()["data"]
    assert j["page_count"] == 2
    assert j["button_count"] == 1


# ============================================================
# Worker
# ============================================================

def test_worker_status_admin(client, admin_token):
    r = client.get("/api/client/workers/status", headers=H(admin_token))
    assert r.status_code == 200
    s = r.json()["data"]
    # test 模式下 running 可能是 False (不启 scheduler)
    assert "jobs" in s
    assert "aggregate_drama_stats" in s["jobs"]


def test_worker_unknown_trigger_404(client, admin_token):
    r = client.post(
        "/api/client/workers/unknown_job/trigger",
        headers=H(admin_token),
    )
    # test 模式下 scheduler 没启, trigger_now 直接返 False → 404
    assert r.status_code == 404
