"""Phase 3 测试 — L9 决策 / L10 Agent / L11 记忆 / L12 自愈."""
from __future__ import annotations

import pytest
from sqlalchemy import select

from app.core.db import get_session_factory
from app.models import HealingPlaybook, RuleProposal


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
# L9 候选池 / Plan / Burst / Tier
# ============================================================

def test_candidate_pool_admin(client, admin_token):
    r = client.get("/api/client/ai/candidate-pool", headers=H(admin_token))
    assert r.status_code == 200
    items = r.json()["data"]["items"]
    assert len(items) >= 5
    assert items[0]["composite_score"] >= items[-1]["composite_score"]


def test_candidate_pool_min_score_filter(client, admin_token):
    r = client.get(
        "/api/client/ai/candidate-pool?min_score=70",
        headers=H(admin_token),
    )
    assert r.status_code == 200
    items = r.json()["data"]["items"]
    for it in items:
        assert it["composite_score"] >= 70


def test_normal_user_cannot_view_ai(client, normal_token):
    """ai:read 不给 normal_user."""
    r = client.get("/api/client/ai/candidate-pool", headers=H(normal_token))
    assert r.status_code == 403


def test_daily_plans(client, admin_token):
    r = client.get("/api/client/ai/daily-plans", headers=H(admin_token))
    assert r.status_code == 200
    assert r.json()["data"]["pagination"]["total"] >= 1


def test_plan_items(client, admin_token):
    r = client.get("/api/client/ai/plan-items", headers=H(admin_token))
    assert r.status_code == 200
    items = r.json()["data"]["items"]
    assert len(items) >= 2
    # \u68c0\u67e5 experiment_group 字段
    has_exp = any(it.get("experiment_group") == "A" for it in items)
    assert has_exp


def test_tier_transitions_empty_ok(client, admin_token):
    """seed 没注 tier_transitions, 应返空 list."""
    r = client.get("/api/client/ai/tier-transitions", headers=H(admin_token))
    assert r.status_code == 200


# ============================================================
# L10 Agent
# ============================================================

def test_agents_status(client, admin_token):
    r = client.get("/api/client/ai/agents", headers=H(admin_token))
    assert r.status_code == 200
    s = r.json()["data"]
    # 9 个 agent
    assert len(s) == 9
    # available 状态 (取决于 KS_AUTOMATION_PATH)
    for name in ("strategy_planner", "task_scheduler", "watchdog", "analyzer"):
        assert name in s


def test_agent_runs_history(client, admin_token):
    r = client.get(
        "/api/client/ai/agents/strategy_planner/runs",
        headers=H(admin_token),
    )
    assert r.status_code == 200
    items = r.json()["data"]["items"]
    assert len(items) >= 1
    assert items[0]["agent_name"] == "strategy_planner"


def test_trigger_agent_writes_run(client, admin_token):
    """手动触发 — 应写一条 agent_run (status=running 或 success)."""
    r = client.post(
        "/api/client/ai/agents/watchdog/trigger",
        headers=H(admin_token),
        json={"dry_run": True, "note": "test"},
    )
    assert r.status_code == 200, r.text
    j = r.json()["data"]
    assert j["agent_name"] == "watchdog"
    assert j["trigger_type"] == "manual"
    assert j["status"] in ("running", "success", "failed")


def test_normal_user_cannot_trigger_agent(client, normal_token):
    r = client.post(
        "/api/client/ai/agents/watchdog/trigger",
        headers=H(normal_token),
        json={"dry_run": True},
    )
    assert r.status_code == 403


def test_autopilot_cycles(client, admin_token):
    r = client.get("/api/client/ai/autopilot/cycles", headers=H(admin_token))
    assert r.status_code == 200
    items = r.json()["data"]["items"]
    assert len(items) >= 1


# ============================================================
# L11 记忆
# ============================================================

def test_decision_history(client, admin_token):
    r = client.get(
        "/api/client/ai/memory/decision-history",
        headers=H(admin_token),
    )
    assert r.status_code == 200
    items = r.json()["data"]["items"]
    assert len(items) >= 1
    assert items[0]["verdict"] == "correct"


def test_strategy_memory(client, admin_token):
    r = client.get("/api/client/ai/memory/strategy", headers=H(admin_token))
    assert r.status_code == 200
    items = r.json()["data"]["items"]
    assert len(items) >= 1
    assert items[0]["ai_trust_score"] is not None


def test_strategy_rewards(client, admin_token):
    r = client.get("/api/client/ai/memory/strategy-rewards", headers=H(admin_token))
    assert r.status_code == 200
    items = r.json()["data"]["items"]
    assert len(items) >= 1


def test_research_notes(client, admin_token):
    r = client.get(
        "/api/client/ai/memory/research-notes?approved=true",
        headers=H(admin_token),
    )
    assert r.status_code == 200
    items = r.json()["data"]["items"]
    assert len(items) >= 1
    assert items[0]["approved"] is True


# ============================================================
# L12 自愈
# ============================================================

def test_playbook_list(client, admin_token):
    r = client.get("/api/client/ai/healing/playbook", headers=H(admin_token))
    assert r.status_code == 200
    items = r.json()["data"]["items"]
    assert len(items) == 12  # seed 12 \u6761
    codes = {it["code"] for it in items}
    assert "cookie_invalid" in codes
    assert "kuaishou_auth_expired_109" in codes


def test_healing_diagnoses(client, admin_token):
    r = client.get("/api/client/ai/healing/diagnoses", headers=H(admin_token))
    assert r.status_code == 200
    items = r.json()["data"]["items"]
    assert len(items) >= 1


def test_rule_proposal_decide_approved_creates_playbook(client, admin_token):
    """\u6279\u51c6\u4e00\u6761 LLM \u63d0\u8bae \u2192 \u81ea\u52a8\u6dfb\u52a0\u5230 healing_playbook."""
    Session = get_session_factory()
    # 直接插一条 pending proposal
    with Session() as db:
        p = RuleProposal(
            organization_id=None,
            proposed_code="test_proposed_rule_001",
            symptom_pattern=r"test_pattern",
            remedy_action="MANUAL_REVIEW",
            params_json='{}',
            rationale="\u6d4b\u8bd5\u63d0\u8bae",
            sample_count=5,
            llm_confidence=0.85,
            status="pending",
        )
        db.add(p)
        db.commit()
        pid = p.id

    r = client.put(
        f"/api/client/ai/healing/rule-proposals/{pid}/decide",
        headers=H(admin_token),
        json={"decision": "approved", "note": "\u6d4b\u8bd5\u6279\u51c6"},
    )
    assert r.status_code == 200, r.text
    assert r.json()["data"]["status"] == "approved"

    # \u9a8c\u8bc1 playbook \u65b0\u589e\u4e86
    with Session() as db:
        pb = db.execute(
            select(HealingPlaybook).where(HealingPlaybook.code == "test_proposed_rule_001")
        ).scalar_one_or_none()
        assert pb is not None
        assert pb.proposed_by == "llm"
        assert pb.enabled is True


def test_rule_proposal_decide_rejected(client, admin_token):
    Session = get_session_factory()
    with Session() as db:
        p = RuleProposal(
            organization_id=None, proposed_code="reject_test_001",
            symptom_pattern="x", remedy_action="x",
            status="pending", llm_confidence=0.3,
        )
        db.add(p)
        db.commit()
        pid = p.id

    r = client.put(
        f"/api/client/ai/healing/rule-proposals/{pid}/decide",
        headers=H(admin_token),
        json={"decision": "rejected"},
    )
    assert r.status_code == 200
    assert r.json()["data"]["status"] == "rejected"

    # \u4e0d\u5e94\u521b\u5efa playbook
    with Session() as db:
        pb = db.execute(
            select(HealingPlaybook).where(HealingPlaybook.code == "reject_test_001")
        ).scalar_one_or_none()
        assert pb is None


def test_rule_proposal_decide_already_decided_409(client, admin_token):
    """\u91cd\u590d\u51b3\u7b56 \u2192 409."""
    Session = get_session_factory()
    with Session() as db:
        p = RuleProposal(
            organization_id=None, proposed_code="conflict_test_001",
            symptom_pattern="x", remedy_action="x",
            status="approved",  # 已决策
        )
        db.add(p)
        db.commit()
        pid = p.id

    r = client.put(
        f"/api/client/ai/healing/rule-proposals/{pid}/decide",
        headers=H(admin_token),
        json={"decision": "approved"},
    )
    assert r.status_code == 409


def test_normal_user_cannot_decide_rule(client, normal_token):
    r = client.put(
        "/api/client/ai/healing/rule-proposals/1/decide",
        headers=H(normal_token),
        json={"decision": "approved"},
    )
    assert r.status_code == 403


# ============================================================
# 周记审批
# ============================================================

def test_approve_diary_writes_field(client, admin_token):
    """假装存一条 diary, 然后 approve."""
    Session = get_session_factory()
    from app.models import AccountDiaryEntry
    from datetime import date as _date
    from app.models import Account
    with Session() as db:
        acc = db.execute(
            select(Account).where(Account.kuaishou_id == "demo_ks_001")
        ).scalar_one_or_none()
        if not acc:
            pytest.skip("无 demo 账号")
        d = AccountDiaryEntry(
            account_id=acc.id, organization_id=acc.organization_id,
            week_start=_date(2026, 4, 21), week_end=_date(2026, 4, 27),
            summary="本周表现稳定",
            performance_review="发布 5 次, 4 成 1 失败",
            lessons_learned="kirin_mode6 适配较好",
            next_week_strategy="继续主推 kirin_mode6",
        )
        db.add(d)
        db.commit()
        did = d.id

    r = client.put(
        f"/api/client/ai/memory/diary/{did}/approve",
        headers=H(admin_token),
        json={"approved": True, "note": "\u770b\u8d77\u6765\u5408\u7406"},
    )
    assert r.status_code == 200, r.text
    assert r.json()["data"]["approved"] is True
