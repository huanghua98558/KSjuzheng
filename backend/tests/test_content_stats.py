"""Sprint 2B 测试 — 收藏池 / 高转化 / Dashboard 聚合 / 收藏记录."""
from __future__ import annotations

import pytest

from app.core.db import get_session_factory


def login(client, username: str, password: str) -> str:
    r = client.post("/api/client/auth/login",
                    json={"username": username, "password": password})
    assert r.status_code == 200, r.text
    return r.json()["data"]["token"]


def H(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


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
# CollectPool — 异常 URL 自动检测
# ============================================================

def test_list_collect_pool_admin_sees_all(client, admin_token):
    r = client.get("/api/client/collect-pool", headers=H(admin_token))
    assert r.status_code == 200
    j = r.json()
    assert j["ok"]
    assert j["data"]["pagination"]["total"] >= 6


def test_collect_pool_seed_marks_abnormal(client, admin_token):
    """seed 中的 '空 URL' 和 '中文 URL' 应被标 abnormal."""
    r = client.get("/api/client/collect-pool?status=abnormal", headers=H(admin_token))
    assert r.status_code == 200
    items = r.json()["data"]["items"]
    reasons = {it.get("abnormal_reason") for it in items}
    assert "url_empty" in reasons or "chinese_in_url" in reasons


def test_normal_user_cannot_view_collect_pool(client, normal_token):
    """collect-pool:view 给 super_admin/operator/captain, 不给 normal_user."""
    r = client.get("/api/client/collect-pool", headers=H(normal_token))
    assert r.status_code == 403


def test_create_collect_pool_url_dedup(client, operator_token):
    payload = {"drama_name": "去重测试", "drama_url": "https://www.kuaishou.com/f/dedup_001"}
    r1 = client.post("/api/client/collect-pool", headers=H(operator_token), json=payload)
    assert r1.status_code == 200, r1.text

    # 第二次同 URL 应 conflict
    r2 = client.post("/api/client/collect-pool", headers=H(operator_token), json=payload)
    assert r2.status_code == 409
    assert r2.json()["error"]["code"] == "CONFLICT_409"


def test_batch_import_collect_pool(client, operator_token):
    """用唯一前缀 batch_uniq_xxx, 避免和其他测试 URL 冲突.

    空 URL 已被 Pydantic schema 在 422 阻挡, 这里只验 inserted + duplicate 路径.
    """
    items = {
        "items": [
            {"drama_name": f"批量{i}",
             "drama_url": f"https://www.kuaishou.com/f/batch_uniq_{i:03d}",
             "auth_code": "test_batch_import"}
            for i in range(20)
        ] + [
            {"drama_name": "批量重复",
             "drama_url": "https://www.kuaishou.com/f/batch_uniq_001",
             "auth_code": "test_batch_import"},
        ]
    }
    r = client.post("/api/client/collect-pool/batch-import",
                    headers=H(operator_token), json=items)
    assert r.status_code == 200, r.text
    j = r.json()["data"]
    assert j["inserted"] == 20
    assert j["skipped_duplicate"] == 1


def test_batch_import_empty_url_rejected_at_schema(client, operator_token):
    """空 URL 被 Pydantic schema 拒在 422."""
    r = client.post(
        "/api/client/collect-pool/batch-import",
        headers=H(operator_token),
        json={"items": [{"drama_name": "x", "drama_url": ""}]},
    )
    assert r.status_code == 422
    assert r.json()["error"]["code"] == "VALIDATION_422"


def test_deduplicate_and_copy(client, operator_token):
    """去重复制: 把 huanghua888 的链接复制到新 auth_code."""
    r = client.post(
        "/api/client/collect-pool/deduplicate-and-copy",
        headers=H(operator_token),
        json={"source_auth_code": "huanghua888",
              "target_auth_code": "test_target_001",
              "keep_source": True},
    )
    assert r.status_code == 200, r.text
    j = r.json()["data"]
    assert j["inserted"] >= 1


# ============================================================
# HighIncomeDramas
# ============================================================

def test_list_high_income(client, admin_token):
    r = client.get("/api/client/high-income-dramas", headers=H(admin_token))
    assert r.status_code == 200
    items = r.json()["data"]["items"]
    names = {it["drama_name"] for it in items}
    assert "财源滚滚小厨神" in names


def test_create_high_income_dedup(client, operator_token):
    r1 = client.post(
        "/api/client/high-income-dramas",
        headers=H(operator_token),
        json={"drama_name": "新高转化剧", "income_amount": 999.0},
    )
    assert r1.status_code == 200

    # 重复 → conflict
    r2 = client.post(
        "/api/client/high-income-dramas",
        headers=H(operator_token),
        json={"drama_name": "新高转化剧"},
    )
    assert r2.status_code == 409


def test_high_income_links_to_collect_pool(client, admin_token):
    """点 '查看链接' 跳到 collect_pool 同名剧的所有链接."""
    # 找 '财源滚滚小厨神' 的 hid
    r = client.get(
        "/api/client/high-income-dramas?keyword=财源",
        headers=H(admin_token),
    )
    items = r.json()["data"]["items"]
    assert len(items) >= 1
    hid = items[0]["id"]

    r2 = client.get(
        f"/api/client/high-income-dramas/{hid}/links",
        headers=H(admin_token),
    )
    assert r2.status_code == 200
    links = r2.json()["data"]
    assert isinstance(links, list)
    # seed 加了 "财源滚滚小厨神" 一条 collect_pool, 应找到
    assert len(links) >= 1


# ============================================================
# Statistics overview
# ============================================================

def test_overview_admin(client, admin_token):
    r = client.get("/api/client/statistics/overview", headers=H(admin_token))
    assert r.status_code == 200, r.text
    o = r.json()["data"]
    assert o["total_accounts"] >= 2
    assert o["total_executions"] >= 10  # seed 10 条
    assert "trend_7d" in o
    assert "success_ratio_30d" in o


def test_overview_operator_scope(client, operator_token):
    r = client.get("/api/client/statistics/overview", headers=H(operator_token))
    assert r.status_code == 200
    o = r.json()["data"]
    # DEMO_MCN 内: seed 给 2 条, 之前 Sprint 2A 测试可能加了几个 (仍同 org)
    assert o["total_accounts"] >= 2
    assert o["total_executions"] >= 10


def test_overview_normal_user_sees_only_own(client, normal_token):
    r = client.get("/api/client/statistics/overview", headers=H(normal_token))
    assert r.status_code == 200
    o = r.json()["data"]
    assert o["total_accounts"] == 1
    # 仅自己的账号 (demo_ks_001) 的 10 条
    assert o["total_executions"] == 10


def test_today_card(client, admin_token):
    r = client.get("/api/client/statistics/today-cards", headers=H(admin_token))
    assert r.status_code == 200
    o = r.json()["data"]
    assert "total_accounts" in o
    assert "today_executions" in o
    assert "avg_duration_ms" in o


def test_executions_list(client, admin_token):
    r = client.get(
        "/api/client/statistics/executions",
        headers=H(admin_token),
    )
    assert r.status_code == 200
    j = r.json()["data"]
    assert "items" in j
    assert "pagination" in j


def test_drama_links_aggregation(client, admin_token):
    """先触发 rebuild, 再查 drama-links 应有数据."""
    r0 = client.post("/api/client/statistics/drama-links/rebuild",
                     headers=H(admin_token))
    assert r0.status_code == 200
    rebuilt = r0.json()["data"]["rebuilt_groups"]
    assert rebuilt >= 1  # 仙尊下山 + 陆总 = 2 组

    r = client.get("/api/client/statistics/drama-links",
                   headers=H(admin_token))
    assert r.status_code == 200
    items = r.json()["data"]["items"]
    assert len(items) >= 1
    # 检查 success_rate 字段存在 + 取值合法
    for it in items:
        assert "success_rate" in it
        assert 0.0 <= it["success_rate"] <= 1.0


# ============================================================
# 权限
# ============================================================

def test_operator_cannot_clear_drama_links(client, operator_token):
    """clear 仅 super_admin."""
    r = client.post("/api/client/statistics/drama-links/clear",
                    headers=H(operator_token))
    assert r.status_code == 403


def test_admin_can_clear_drama_links(client, admin_token):
    # 先 rebuild 才有可清空的
    client.post("/api/client/statistics/drama-links/rebuild", headers=H(admin_token))
    r = client.post("/api/client/statistics/drama-links/clear",
                    headers=H(admin_token))
    assert r.status_code == 200, r.text
    assert r.json()["data"]["deleted"] >= 1
