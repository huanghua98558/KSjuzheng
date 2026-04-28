"""测试账号 + 权限 + tenant_scope.

覆盖:
  - 4 角色登录后看到的范围
  - 越权 batch-* 整批拒
  - 权限缺失 → 403
  - reveal cookie 单独审计
"""
from __future__ import annotations

import pytest
from sqlalchemy import select

from app.core.db import get_session_factory
from app.core.security import hash_password
from app.models import (
    Account,
    CloudCookieAccount,
    Organization,
    OperationLog,
    User,
)


# ============================================================
# Helpers
# ============================================================

def login(client, username: str, password: str) -> str:
    r = client.post("/api/client/auth/login",
                    json={"username": username, "password": password})
    assert r.status_code == 200, r.text
    j = r.json()
    assert j["ok"], j
    return j["data"]["token"]


def auth_headers(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


# ============================================================
# Fixtures
# ============================================================

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
# 列表隔离
# ============================================================

def test_admin_sees_all_accounts(client, admin_token):
    r = client.get("/api/client/accounts", headers=auth_headers(admin_token))
    assert r.status_code == 200
    data = r.json()["data"]
    # admin 看全部 (演示有 2 条)
    assert data["pagination"]["total"] >= 2


def test_operator_sees_org_accounts(client, operator_token):
    r = client.get("/api/client/accounts", headers=auth_headers(operator_token))
    assert r.status_code == 200
    data = r.json()["data"]
    # operator 看自己机构内全部 (含 unassigned, 共 2 条)
    assert data["pagination"]["total"] == 2
    org_ids = {item["organization_id"] for item in data["items"]}
    assert len(org_ids) == 1  # 仅 1 个机构


def test_normal_user_sees_only_own(client, normal_token):
    r = client.get("/api/client/accounts", headers=auth_headers(normal_token))
    assert r.status_code == 200
    data = r.json()["data"]
    # normal_user 仅看 assigned_user_id == self (1 条 demo_ks_001)
    assert data["pagination"]["total"] == 1
    assert data["items"][0]["kuaishou_id"] == "demo_ks_001"


# ============================================================
# 越权
# ============================================================

def test_normal_user_cannot_access_user_management(client, normal_token):
    """user:view 权限只给 super_admin/operator."""
    r = client.get("/api/client/users", headers=auth_headers(normal_token))
    assert r.status_code == 403
    assert r.json()["error"]["code"] == "AUTH_403"


def test_operator_can_access_user_management(client, operator_token):
    r = client.get("/api/client/users", headers=auth_headers(operator_token))
    assert r.status_code == 200


def test_normal_user_cannot_create_account(client, normal_token):
    r = client.post(
        "/api/client/accounts",
        headers=auth_headers(normal_token),
        json={"kuaishou_id": "x", "nickname": "y"},
    )
    assert r.status_code == 403


def test_operator_can_create_account(client, operator_token):
    r = client.post(
        "/api/client/accounts",
        headers=auth_headers(operator_token),
        json={"kuaishou_id": "demo_ks_new_001", "nickname": "new"},
    )
    assert r.status_code == 200, r.text
    assert r.json()["ok"]


def test_normal_user_cannot_batch_authorize(client, normal_token):
    """即使 normal_user 直接调 batch-* 端点, 应被 require_perm 拒."""
    r = client.post(
        "/api/client/accounts/batch-authorize",
        headers=auth_headers(normal_token),
        json={"ids": [1]},
    )
    assert r.status_code == 403


def test_operator_batch_authorize_in_scope(client, operator_token):
    Session = get_session_factory()
    with Session() as db:
        ids = [a.id for a in db.execute(
            select(Account).where(Account.organization_id == 2)
        ).scalars().all()]

    r = client.post(
        "/api/client/accounts/batch-authorize",
        headers=auth_headers(operator_token),
        json={"ids": ids},
    )
    assert r.status_code == 200
    j = r.json()
    assert j["ok"]
    assert j["data"]["success_count"] == len(ids)


def test_operator_batch_authorize_out_of_scope_rejected(client, operator_token):
    """operator 试图越权 batch-authorize 一个不存在 ID 整批应拒."""
    # ID 999999 显然不在 operator 范围内
    r = client.post(
        "/api/client/accounts/batch-authorize",
        headers=auth_headers(operator_token),
        json={"ids": [999999]},
    )
    assert r.status_code == 403
    assert r.json()["error"]["code"] == "AUTH_403"


# ============================================================
# Cookie 脱敏 + reveal 审计
# ============================================================

def _create_test_cookie_for_demo_org():
    """直接用 service 注一条 cookie."""
    Session = get_session_factory()
    from app.services.cookie_service import create_cookie
    from app.schemas.account import CloudCookieCreate
    with Session() as db:
        op = db.execute(select(User).where(User.username == "op_demo")).scalar_one()
        c = create_cookie(db, op, CloudCookieCreate(
            uid="test_uid_001",
            nickname="测试 Cookie",
            owner_code="op_demo",
            cookie="userId=987654321; passToken=secrettoken-1234567890abcdef",
        ))
        db.commit()
        return c.id


def test_cloud_cookie_default_masked(client, admin_token):
    """list 接口默认不返明文 cookie."""
    cid = _create_test_cookie_for_demo_org()
    r = client.get("/api/client/cloud-cookies", headers=auth_headers(admin_token))
    assert r.status_code == 200
    items = r.json()["data"]["items"]
    found = next((c for c in items if c["id"] == cid), None)
    assert found is not None
    # cookie_preview 含 ***, 不含原文 passToken
    assert "***" in (found.get("cookie_preview") or "")
    assert "secrettoken" not in str(found)


def test_normal_user_cannot_view_cookies(client, normal_token):
    """normal_user 没 cloud-cookie:view, 直接 403."""
    r = client.get("/api/client/cloud-cookies", headers=auth_headers(normal_token))
    assert r.status_code == 403


def test_operator_cannot_reveal_cookie(client, operator_token):
    """reveal 默认仅 super_admin."""
    cid = _create_test_cookie_for_demo_org()
    r = client.get(
        f"/api/client/cloud-cookies/{cid}/reveal",
        headers=auth_headers(operator_token),
    )
    assert r.status_code == 403


def test_admin_can_reveal_cookie_and_writes_audit(client, admin_token):
    cid = _create_test_cookie_for_demo_org()

    # 调 reveal
    r = client.get(
        f"/api/client/cloud-cookies/{cid}/reveal",
        headers=auth_headers(admin_token),
    )
    assert r.status_code == 200, r.text
    j = r.json()
    assert j["ok"]
    plain = j["data"]["cookie_plaintext"]
    assert "passToken=secrettoken" in plain  # 真明文返回

    # 验证审计表有写
    Session = get_session_factory()
    with Session() as db:
        log = db.execute(
            select(OperationLog)
            .where(OperationLog.action == "reveal")
            .where(OperationLog.module == "cloud-cookie")
            .order_by(OperationLog.id.desc())
            .limit(1)
        ).scalar_one_or_none()
        assert log is not None
        assert log.target_id == str(cid)


# ============================================================
# 写操作产生 operation_log
# ============================================================

def test_create_account_writes_audit(client, operator_token):
    r = client.post(
        "/api/client/accounts",
        headers=auth_headers(operator_token),
        json={"kuaishou_id": "audit_test_001"},
    )
    assert r.status_code == 200
    aid = r.json()["data"]["id"]

    Session = get_session_factory()
    with Session() as db:
        log = db.execute(
            select(OperationLog)
            .where(OperationLog.module == "account")
            .where(OperationLog.action == "create")
            .where(OperationLog.target_id == str(aid))
        ).scalar_one_or_none()
        assert log is not None
        assert log.user_id is not None
        assert log.trace_id is not None


# ============================================================
# 机构隔离
# ============================================================

def test_operator_cannot_create_org(client, operator_token):
    r = client.post(
        "/api/client/organizations",
        headers=auth_headers(operator_token),
        json={"name": "盗窃机构", "org_code": "HACK"},
    )
    assert r.status_code == 403


def test_admin_can_create_org(client, admin_token):
    r = client.post(
        "/api/client/organizations",
        headers=auth_headers(admin_token),
        json={"name": "新机构", "org_code": "NEW_ORG_001", "plan_tier": "pro"},
    )
    assert r.status_code == 200, r.text


# ============================================================
# 用户管理
# ============================================================

def test_operator_can_create_normal_user(client, operator_token):
    r = client.post(
        "/api/client/users",
        headers=auth_headers(operator_token),
        json={
            "username": "test_subordinate_001",
            "password": "abc123",
            "role": "normal_user",
            "commission_rate": 0.7,
        },
    )
    assert r.status_code == 200, r.text


def test_operator_cannot_create_super_admin(client, operator_token):
    """schema 层 422 (role enum 不含 super_admin) 或 service 层 403 都算拒绝."""
    r = client.post(
        "/api/client/users",
        headers=auth_headers(operator_token),
        json={
            "username": "fake_admin",
            "password": "abc123",
            "role": "super_admin",
        },
    )
    assert r.status_code in (403, 422)
