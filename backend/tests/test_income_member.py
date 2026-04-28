"""Sprint 2C 测试 — 收益 / 成员 / 违规 / 钱包 / 标结 / 字段脱敏 / member-query 白名单."""
from __future__ import annotations

import pytest
from sqlalchemy import select

from app.core.db import get_session_factory
from app.models import IncomeArchive, User


def login(client, username: str, password: str) -> str:
    r = client.post("/api/client/auth/login",
                    json={"username": username, "password": password})
    assert r.status_code == 200, r.text
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
# 列表 + 4 角色 + 隔离
# ============================================================

def test_org_members_admin_sees(client, admin_token):
    r = client.get("/api/client/org-members", headers=H(admin_token))
    assert r.status_code == 200
    assert r.json()["data"]["pagination"]["total"] >= 1


def test_normal_user_cannot_view_org_members(client, normal_token):
    """org-member:view 不给 normal_user."""
    r = client.get("/api/client/org-members", headers=H(normal_token))
    assert r.status_code == 403


def test_spark_members_operator(client, operator_token):
    r = client.get("/api/client/spark/members", headers=H(operator_token))
    assert r.status_code == 200
    items = r.json()["data"]["items"]
    assert len(items) >= 1


def test_firefly_members_normal(client, normal_token):
    """normal_user 有 firefly:view-monthly, 应能看."""
    r = client.get("/api/client/firefly/members", headers=H(normal_token))
    assert r.status_code == 200


# ============================================================
# 收益列表 + 脱敏
# ============================================================

def test_spark_income_admin(client, admin_token):
    r = client.get("/api/client/spark/income", headers=H(admin_token))
    assert r.status_code == 200
    items = r.json()["data"]["items"]
    assert len(items) >= 5
    # admin 不脱敏
    assert items[0]["commission_rate"] is not None
    assert items[0]["commission_amount"] is not None


def test_spark_income_normal_default_visible(client, normal_token):
    """normal_user 默认 commission_*_visible=True, 应看到字段."""
    r = client.get("/api/client/spark/income", headers=H(normal_token))
    assert r.status_code == 200
    items = r.json()["data"]["items"]
    assert len(items) >= 1
    assert items[0]["commission_rate"] is not None


def test_spark_income_normal_hidden_when_visibility_off(client, admin_token, normal_token):
    """关闭 normal_user 的 commission_amount_visible 后, 字段返 None."""
    Session = get_session_factory()
    with Session() as db:
        nu = db.execute(select(User).where(User.username == "user_demo")).scalar_one()
        nu.commission_amount_visible = False
        nu.total_income_visible = False
        db.commit()

    r = client.get("/api/client/spark/income", headers=H(normal_token))
    assert r.status_code == 200
    items = r.json()["data"]["items"]
    assert len(items) >= 1
    assert items[0]["commission_amount"] is None
    assert items[0]["income_amount"] is None
    # commission_rate 仍 visible
    assert items[0]["commission_rate"] is not None

    # 还原
    with Session() as db:
        nu = db.execute(select(User).where(User.username == "user_demo")).scalar_one()
        nu.commission_amount_visible = True
        nu.total_income_visible = True
        db.commit()


def test_firefly_income_stats(client, admin_token):
    r = client.get("/api/client/firefly/income/stats", headers=H(admin_token))
    assert r.status_code == 200
    s = r.json()["data"]
    assert s["record_count"] == 6
    assert s["settled_amount"] > 0
    assert s["pending_amount"] > 0


def test_fluorescent_income_no_settlement(client, admin_token):
    """荧光是流水, 不应有 settlement_status 过滤逻辑."""
    r = client.get("/api/client/fluorescent/income", headers=H(admin_token))
    assert r.status_code == 200
    items = r.json()["data"]["items"]
    assert len(items) == 4


# ============================================================
# Excel 导入
# ============================================================

def test_spark_income_import(client, operator_token):
    payload = {
        "program_type": "spark",
        "items": [
            {"member_id": 999000001, "task_name": "导入测试1",
             "income_amount": 30.0, "commission_rate": 0.80,
             "commission_amount": 24.0,
             "income_date": "2026-04-15"},
            {"member_id": 999000002, "task_name": "导入测试2",
             "income_amount": 50.0, "commission_rate": 0.80,
             "commission_amount": 40.0,
             "income_date": "2026-04-15"},
        ],
    }
    r = client.post("/api/client/spark/income/import",
                    headers=H(operator_token), json=payload)
    assert r.status_code == 200, r.text
    j = r.json()["data"]
    assert j["inserted"] == 2


def test_normal_user_cannot_import_spark(client, normal_token):
    """spark:import 给 super_admin/operator, 不给 normal."""
    r = client.post(
        "/api/client/spark/income/import",
        headers=H(normal_token),
        json={"program_type": "spark", "items": [
            {"member_id": 1, "income_amount": 1.0}
        ]},
    )
    assert r.status_code == 403


def test_import_program_mismatch_rejected(client, operator_token):
    """endpoint=spark/import 但 program_type=firefly → 422."""
    r = client.post(
        "/api/client/spark/income/import",
        headers=H(operator_token),
        json={"program_type": "firefly", "items": [
            {"member_id": 1, "income_amount": 1.0}
        ]},
    )
    assert r.status_code == 422


# ============================================================
# 归档 + 标结
# ============================================================

def test_archive_list(client, admin_token):
    r = client.get("/api/client/archive", headers=H(admin_token))
    assert r.status_code == 200
    items = r.json()["data"]["items"]
    assert len(items) == 3
    types = {it["program_type"] for it in items}
    assert types == {"spark", "firefly", "fluorescent"}


def test_archive_stats(client, admin_token):
    r = client.get("/api/client/archive/stats", headers=H(admin_token))
    assert r.status_code == 200
    s = r.json()["data"]
    assert s["total_count"] == 3
    assert s["settled_count"] >= 1


def test_settle_single_archive(client, operator_token):
    """标结 spark 归档."""
    Session = get_session_factory()
    with Session() as db:
        a = db.execute(
            select(IncomeArchive).where(IncomeArchive.program_type == "spark")
        ).scalar_one()
    aid = a.id

    r = client.put(
        f"/api/client/archive/{aid}/settlement",
        headers=H(operator_token),
        json={"remark": "测试标结"},
    )
    assert r.status_code == 200, r.text
    assert r.json()["data"]["settlement_status"] == "settled"


def test_batch_settle_archive(client, operator_token):
    Session = get_session_factory()
    with Session() as db:
        ids = [a.id for a in db.execute(
            select(IncomeArchive).where(IncomeArchive.settlement_status != "settled")
        ).scalars().all()]
    if not ids:
        pytest.skip("已无 pending 归档可标结")

    r = client.post(
        "/api/client/archive/batch-settlement",
        headers=H(operator_token),
        json={"archive_ids": ids, "remark": "批量结清"},
    )
    assert r.status_code == 200, r.text
    j = r.json()["data"]
    assert j["settled_count"] >= 1


# ============================================================
# Member-Query (★ 强隔离白名单)
# ============================================================

def test_member_query_in_scope(client, operator_token):
    """operator 查 scope 内 UID — 应通过."""
    r = client.post(
        "/api/client/member-query",
        headers=H(operator_token),
        json={"uids": ["887329560"], "program_type": "all"},
    )
    assert r.status_code == 200, r.text
    j = r.json()["data"]
    assert "items" in j
    assert "summary" in j


def test_member_query_out_of_scope_rejected(client, operator_token):
    """operator 查不在 scope 的 UID — 整批 403."""
    r = client.post(
        "/api/client/member-query",
        headers=H(operator_token),
        json={"uids": ["999999999"], "program_type": "all"},
    )
    assert r.status_code == 403
    j = r.json()
    assert j["error"]["code"] == "AUTH_403"


def test_member_query_partial_invalid_rejects_whole(client, operator_token):
    """混入 1 个越权 UID → 整批拒, 不返部分."""
    r = client.post(
        "/api/client/member-query",
        headers=H(operator_token),
        json={"uids": ["887329560", "999999999"], "program_type": "all"},
    )
    assert r.status_code == 403


def test_normal_user_cannot_member_query(client, normal_token):
    """member-query:execute 不给 normal_user."""
    r = client.post(
        "/api/client/member-query",
        headers=H(normal_token),
        json={"uids": ["887329560"]},
    )
    assert r.status_code == 403


# ============================================================
# 违规作品
# ============================================================

def test_list_violations(client, admin_token):
    r = client.get("/api/client/violations", headers=H(admin_token))
    assert r.status_code == 200
    assert r.json()["data"]["pagination"]["total"] >= 1


def test_appeal_violation(client, operator_token):
    r0 = client.get("/api/client/violations", headers=H(operator_token))
    items = r0.json()["data"]["items"]
    if not items:
        pytest.skip("无违规记录")
    vid = items[0]["id"]

    r = client.put(
        f"/api/client/violations/{vid}",
        headers=H(operator_token),
        json={"appeal_status": "submitted",
              "appeal_reason": "测试申诉"},
    )
    assert r.status_code == 200
    assert r.json()["data"]["appeal_status"] == "submitted"


def test_normal_user_cannot_delete_violation(client, normal_token):
    """violation:delete 仅 super_admin."""
    r = client.delete("/api/client/violations/1", headers=H(normal_token))
    assert r.status_code == 403


# ============================================================
# 钱包
# ============================================================

def test_get_my_wallet(client, operator_token):
    r = client.get("/api/client/wallet", headers=H(operator_token))
    assert r.status_code == 200
    w = r.json()["data"]
    assert w["alipay_account"] == "13800138000@example.com"


def test_normal_user_can_get_own_wallet(client, normal_token):
    """每个登录用户都可以拿自己的钱包 (会自动创建空 profile)."""
    r = client.get("/api/client/wallet", headers=H(normal_token))
    assert r.status_code == 200, r.text
    w = r.json()["data"]
    assert w["user_id"] is not None


def test_update_my_wallet(client, operator_token):
    r = client.put(
        "/api/client/wallet",
        headers=H(operator_token),
        json={"alipay_name": "更新后", "real_name": "黄华"},
    )
    assert r.status_code == 200
    assert r.json()["data"]["alipay_name"] == "更新后"


def test_operator_cannot_view_other_wallet(client, operator_token):
    """user:view-wallet-others 仅 super_admin."""
    r = client.get("/api/client/wallet/users/1", headers=H(operator_token))
    assert r.status_code == 403


def test_admin_can_view_other_wallet(client, admin_token):
    Session = get_session_factory()
    with Session() as db:
        op = db.execute(select(User).where(User.username == "op_demo")).scalar_one()
    r = client.get(f"/api/client/wallet/users/{op.id}", headers=H(admin_token))
    assert r.status_code == 200, r.text
