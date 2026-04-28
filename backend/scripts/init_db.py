"""初始化 DB — 创建所有表 + seed 内置数据.

用法:
    python -m scripts.init_db                    # 仅建表 (幂等)
    python -m scripts.init_db --seed             # 建表 + 种 admin + 演示卡密 + 权限 + 演示账号
    python -m scripts.init_db --reset --seed     # 清表重来 (危险)
"""
from __future__ import annotations

import argparse
import sys
from datetime import datetime, timedelta, timezone

from sqlalchemy import select

from app.core.db import Base, get_session_factory, init_engine
from app.core.security import generate_license_key, hash_password
from app.models import (
    Account,
    AccountGroup,
    AccountTaskRecord,
    Announcement,
    CollectPool,
    DefaultRolePermission,
    DramaCollectionRecord,
    DramaLinkStatistic,
    FireflyIncome,
    FireflyMember,
    FluorescentIncome,
    FluorescentMember,
    HighIncomeDrama,
    IncomeArchive,
    KsAccount,
    License,
    Organization,
    OrgMember,
    Permission,
    Role,
    RolePermission,
    SparkIncome,
    SparkMember,
    User,
    UserRole,
    ViolationPhoto,
    WalletProfile,
)
from scripts.permissions_data import (
    BUILTIN_ROLES,
    all_perms,
    default_role_perms_map,
)


def create_all():
    eng = init_engine()
    import app.models  # noqa: F401
    Base.metadata.create_all(eng)
    print(f"[init_db] tables created/verified at {eng.url}")


def drop_all():
    eng = init_engine()
    import app.models  # noqa: F401
    Base.metadata.drop_all(eng)
    print(f"[init_db] all tables dropped at {eng.url}")


# ============================================================
# Seed: 权限 + 角色 + 默认权限
# ============================================================

def seed_permissions(db) -> int:
    n = 0
    for code, resource, action, desc, ptype in all_perms():
        existing = db.execute(
            select(Permission).where(Permission.code == code)
        ).scalar_one_or_none()
        if not existing:
            db.add(Permission(
                code=code,
                resource=resource,
                action=action,
                description=f"[{ptype}] {desc}",
            ))
            n += 1
    db.flush()
    return n


def seed_roles(db) -> int:
    """内置 4 角色 (organization_id=NULL = 平台级)."""
    n = 0
    for code, name, level, desc in BUILTIN_ROLES:
        existing = db.execute(
            select(Role).where(Role.code == code).where(Role.organization_id.is_(None))
        ).scalar_one_or_none()
        if not existing:
            db.add(Role(
                organization_id=None,
                code=code,
                name=name,
                description=f"[L{level}] {desc}",
                is_builtin=True,
            ))
            n += 1
    db.flush()
    return n


def seed_default_role_perms(db) -> int:
    """填充 default_role_permissions 表."""
    n = 0
    mapping = default_role_perms_map()
    for role, pairs in mapping.items():
        for ptype, code in pairs:
            existing = db.execute(
                select(DefaultRolePermission)
                .where(DefaultRolePermission.role == role)
                .where(DefaultRolePermission.permission_type == ptype)
                .where(DefaultRolePermission.permission_code == code)
            ).scalar_one_or_none()
            if not existing:
                db.add(DefaultRolePermission(
                    role=role, permission_type=ptype, permission_code=code,
                ))
                n += 1
    db.flush()
    return n


# ============================================================
# Seed: 超管 organization + admin user
# ============================================================

def seed_admin(db):
    org = db.execute(
        select(Organization).where(Organization.org_code == "SUPER")
    ).scalar_one_or_none()
    if not org:
        org = Organization(
            name="超管平台",
            org_code="SUPER",
            org_type="mcn",
            plan_tier="enterprise",
            max_accounts=99999,
            max_users=999,
        )
        db.add(org)
        db.flush()
        print(f"  超管 org 创建: id={org.id}")

    admin = db.execute(select(User).where(User.username == "admin")).scalar_one_or_none()
    if not admin:
        admin = User(
            organization_id=org.id,
            username="admin",
            password_hash=hash_password("admin"),
            display_name="超级管理员",
            role="super_admin",
            level=100,
            is_active=True,
            is_superadmin=True,
            must_change_pw=True,
        )
        db.add(admin)
        db.flush()
        print(f"  admin 用户创建: id={admin.id}, 默认密码 admin (首次登录强制改)")

    # 旧 Role 表 (Phase 1 沿用) — 关联 admin
    admin_role = db.execute(
        select(Role).where(Role.code == "super_admin").where(Role.organization_id.is_(None))
    ).scalar_one_or_none()
    if admin_role:
        existing = db.execute(
            select(UserRole).where(UserRole.user_id == admin.id)
            .where(UserRole.role_id == admin_role.id)
        ).scalar_one_or_none()
        if not existing:
            db.add(UserRole(user_id=admin.id, role_id=admin_role.id))


def seed_demo_licenses(db):
    """造 3 张演示卡密 (Phase 1 已有, Phase 2 仅在表空时再造)."""
    existing = db.execute(select(License)).first()
    if existing:
        return
    for plan, days in [("basic", 30), ("pro", 90), ("team", 365)]:
        key = generate_license_key()
        L = License(
            license_key=key,
            plan_tier=plan,
            max_accounts={"basic": 10, "pro": 50, "team": 200, "enterprise": 9999}[plan],
            issued_at=datetime.now(timezone.utc),
            expires_at=datetime.now(timezone.utc) + timedelta(days=days),
            status="unused",
        )
        db.add(L)
        print(f"  演示卡密: {key}  plan={plan}  {days} 天")


def seed_demo_org_and_users(db):
    """造一个演示 MCN + 2 个用户 (operator + normal_user) 用于测试 tenant_scope.

    幂等: 已存在则跳过.
    """
    org = db.execute(
        select(Organization).where(Organization.org_code == "DEMO_MCN")
    ).scalar_one_or_none()
    if org:
        return

    org = Organization(
        name="演示 MCN", org_code="DEMO_MCN", org_type="mcn", plan_tier="pro",
        max_accounts=50, max_users=10,
    )
    db.add(org)
    db.flush()
    print(f"  演示 MCN 机构: id={org.id}")

    op = User(
        organization_id=org.id, username="op_demo",
        password_hash=hash_password("demo"),
        display_name="演示团长", role="operator", level=50,
        is_active=True, must_change_pw=False,
    )
    db.add(op)
    db.flush()

    nu = User(
        organization_id=org.id, username="user_demo",
        password_hash=hash_password("demo"),
        display_name="演示队员", role="normal_user", level=10,
        parent_user_id=op.id,
        is_active=True, must_change_pw=False,
    )
    db.add(nu)
    db.flush()
    print(f"  演示 operator (op_demo/demo) id={op.id}, normal_user (user_demo/demo) id={nu.id}")

    # 给 nu 分一个账号
    acc = Account(
        organization_id=org.id,
        assigned_user_id=nu.id,
        kuaishou_id="demo_ks_001",
        real_uid="demo_uid_001",
        nickname="演示快手账号",
        status="active",
        commission_rate=0.80,
        imported_by_user_id=op.id,
        imported_at=datetime.now(timezone.utc),
    )
    db.add(acc)
    db.flush()
    print(f"  演示账号: id={acc.id} 分给 user_demo")

    # 另一个 unassigned, 仅 operator 看得见
    acc2 = Account(
        organization_id=org.id,
        kuaishou_id="demo_ks_002",
        nickname="未分配账号",
        status="active",
        commission_rate=0.80,
    )
    db.add(acc2)
    db.flush()


def seed_demo_content(db):
    """Sprint 2B: 演示内容数据 (CollectPool / HighIncome / TaskRecords)."""
    org = db.execute(
        select(Organization).where(Organization.org_code == "DEMO_MCN")
    ).scalar_one_or_none()
    if not org:
        return

    # 收藏池演示 — 跳过若已存在
    existing = db.execute(
        select(CollectPool).where(CollectPool.organization_id == org.id).limit(1)
    ).scalar_one_or_none()
    if existing:
        return

    print("[seed] 收藏池 + 高转化 + 任务记录...")
    samples = [
        ("仙尊下山", "https://www.kuaishou.com/f/X-abc001", "kuaishou", "huanghua888"),
        ("陆总今天要离婚", "https://www.kuaishou.com/f/X-abc002", "kuaishou", "huanghua888"),
        ("财源滚滚小厨神", "https://www.kuaishou.com/f/X-abc003", "kuaishou", "huanghua888"),
        ("望夫成龙", "https://djvod.ndcimgs.com/bs3/.../abc004.mp4", "kuaishou", "huanghua888"),
        ("空 URL 测试", "", "kuaishou", "huanghua888"),  # 触发异常 url_empty
        ("中文 URL 测试", "https://www.example.com/视频.mp4", "kuaishou", "huanghua888"),  # chinese
    ]
    from app.services.collect_pool_service import detect_abnormal
    for name, url, plat, ac in samples:
        ab = detect_abnormal(url)
        db.add(CollectPool(
            organization_id=org.id,
            drama_name=name, drama_url=url or "(empty)",
            platform=plat, auth_code=ac,
            status="abnormal" if ab else "active",
            abnormal_reason=ab,
        ))
    db.flush()
    print(f"          + 6 条收藏池")

    # 高转化 (2 条)
    db.add(HighIncomeDrama(
        organization_id=org.id, drama_name="财源滚滚小厨神",
        source_program="firefly", income_amount=1234.56,
        notes="演示: 30 天 ¥1234 收益, AI 推荐",
    ))
    db.add(HighIncomeDrama(
        organization_id=org.id, drama_name="望夫成龙",
        source_program="manual", income_amount=88.0,
        notes="演示: 手动加入",
    ))
    db.flush()
    print(f"          + 2 条高转化")

    # 任务记录 — 模拟 acc1 的任务 (10 条, 8 成功 2 失败)
    acc = db.execute(
        select(Account).where(Account.kuaishou_id == "demo_ks_001")
    ).scalar_one_or_none()
    if acc:
        from datetime import timedelta
        now = datetime.now(timezone.utc)
        for i in range(10):
            db.add(AccountTaskRecord(
                account_id=acc.id,
                organization_id=org.id,
                task_type="publish",
                drama_name="仙尊下山" if i < 6 else "陆总今天要离婚",
                success=(i not in (3, 7)),  # 第 3 和 7 失败
                duration_ms=2500 + i * 100,
                error_message=None if i not in (3, 7) else "模拟失败: cookie expired",
                created_at=now - timedelta(hours=i * 6),
            ))
        db.flush()
        print(f"          + 10 条任务记录 (8 成功 / 2 失败)")


def seed_demo_income(db):
    """Sprint 2C: 演示收益 / 成员 / 违规 / 钱包数据."""
    org = db.execute(
        select(Organization).where(Organization.org_code == "DEMO_MCN")
    ).scalar_one_or_none()
    if not org:
        return

    existing = db.execute(
        select(SparkMember).where(SparkMember.organization_id == org.id).limit(1)
    ).scalar_one_or_none()
    if existing:
        return

    print("[seed] 收益 + 成员 + 违规 + 钱包...")

    acc = db.execute(
        select(Account).where(Account.kuaishou_id == "demo_ks_001")
    ).scalar_one_or_none()
    acc_id = acc.id if acc else None
    member_id = 887329560
    if acc:
        acc.real_uid = "887329560"  # 让 member-query 能命中

    db.add(OrgMember(
        organization_id=org.id, member_id=member_id, account_id=acc_id,
        nickname="百洁短剧工厂", fans_count=3200, broker_name="演示经纪人",
        cooperation_type="独家", mcn_level="A级",
        renewal_status="active",
    ))
    db.add(SparkMember(
        organization_id=org.id, member_id=member_id, account_id=acc_id,
        nickname="百洁短剧工厂", fans_count=3200, broker_name="演示经纪人",
        task_count=8, hidden=False, first_release_id="release_001",
    ))
    db.add(FireflyMember(
        organization_id=org.id, member_id=member_id, account_id=acc_id,
        nickname="百洁短剧工厂", fans_count=3200, broker_name="演示经纪人",
        total_amount=345.67, org_task_num=5, hidden=False,
    ))
    db.add(FluorescentMember(
        organization_id=org.id, member_id=member_id, account_id=acc_id,
        nickname="百洁短剧工厂", fans_count=3200, broker_name="演示经纪人",
        total_amount=88.5, org_task_num=2,
    ))

    from datetime import timedelta
    today = datetime.now(timezone.utc).date()

    for i in range(5):
        db.add(SparkIncome(
            organization_id=org.id, member_id=member_id, account_id=acc_id,
            task_id=f"spark_{i:03d}", task_name=f"星火任务 {i}",
            income_amount=10.0 + i * 5,
            commission_rate=0.80,
            commission_amount=(10.0 + i * 5) * 0.80,
            start_date=today - timedelta(days=20 + i),
            end_date=today - timedelta(days=10 + i),
            settlement_status="settled" if i < 3 else "pending",
            archived_year_month=(today - timedelta(days=20 + i)).strftime("%Y-%m"),
        ))

    for i in range(6):
        amt = 50.0 + i * 12.5
        db.add(FireflyIncome(
            organization_id=org.id, member_id=member_id, account_id=acc_id,
            task_id=f"firefly_{i:03d}", task_name=f"萤光任务 {i}",
            income_amount=amt,
            commission_rate=0.80, commission_amount=amt * 0.80,
            income_date=today - timedelta(days=i * 3),
            settlement_status="settled" if i < 4 else "pending",
            archived_year_month=(today - timedelta(days=i * 3)).strftime("%Y-%m"),
        ))

    for i in range(4):
        db.add(FluorescentIncome(
            organization_id=org.id, member_id=member_id, account_id=acc_id,
            task_id=f"fluor_{i:03d}", task_name=f"荧光任务 {i}",
            income_amount=5.0 + i,
            total_amount=5.0 + i,
            org_task_num=1,
            income_date=today - timedelta(days=i),
        ))

    y, m = today.year, today.month
    db.add(IncomeArchive(
        organization_id=org.id, program_type="spark",
        year=y, month=m, member_id=member_id, account_id=acc_id,
        total_amount=80.0, commission_rate=0.80, commission_amount=64.0,
        settlement_status="pending",
    ))
    db.add(IncomeArchive(
        organization_id=org.id, program_type="firefly",
        year=y, month=m, member_id=member_id, account_id=acc_id,
        total_amount=345.67, commission_rate=0.80, commission_amount=276.54,
        settlement_status="settled",
        archived_at=datetime.now(timezone.utc),
    ))
    db.add(IncomeArchive(
        organization_id=org.id, program_type="fluorescent",
        year=y, month=m, member_id=member_id, account_id=acc_id,
        total_amount=23.5, commission_rate=None, commission_amount=None,
        settlement_status="pending",
    ))

    db.add(ViolationPhoto(
        organization_id=org.id, account_id=acc_id,
        work_id="demo_work_001", uid="887329560",
        thumbnail="https://example.com/thumb_001.jpg",
        description="演示违规作品",
        business_type="firefly",
        violation_reason="本作品在目前公司库存中已存在等物料高度类似",
        view_count=12345, like_count=567,
        appeal_status="submitted",
        appeal_reason="作品为原创, 申诉一下",
        published_at=datetime.now(timezone.utc) - timedelta(days=2),
        detected_at=datetime.now(timezone.utc) - timedelta(hours=5),
    ))

    op = db.execute(
        select(User).where(User.username == "op_demo")
    ).scalar_one_or_none()
    if op:
        existing_w = db.execute(
            select(WalletProfile).where(WalletProfile.user_id == op.id)
        ).scalar_one_or_none()
        if not existing_w:
            db.add(WalletProfile(
                user_id=op.id,
                real_name="演示团长",
                alipay_name="演示团长",
                alipay_account="13800138000@example.com",
                notes="演示数据",
            ))

    db.flush()
    print(f"          + 1 OrgMember + 3 program member + 15 收益条目"
          " + 3 归档 + 1 违规 + 1 钱包")


def seed_demo_announcements(db):
    """Sprint 2D: 演示公告 + 加密 Cookie."""
    existing = db.execute(select(Announcement).limit(1)).scalar_one_or_none()
    if existing:
        return

    print("[seed] 公告 + 加密 Cookie...")

    db.add(Announcement(
        organization_id=None, title="平台维护通知",
        content="本周日凌晨 2:00-4:00 例行维护. 期间服务可能短暂不可用.",
        level="warning", pinned=True, active=True,
    ))
    db.add(Announcement(
        organization_id=None, title="新版本上线",
        content="后端 v0.1.0 已上线, 含 Phase 1 + Sprint 2A/B/C/D.",
        level="info", pinned=False, active=True,
    ))
    org = db.execute(
        select(Organization).where(Organization.org_code == "DEMO_MCN")
    ).scalar_one_or_none()
    if org:
        db.add(Announcement(
            organization_id=org.id,
            title="DEMO_MCN 内部公告",
            content="演示机构内部公告 - 仅本机构成员可见.",
            level="info", pinned=False, active=True,
        ))
    db.flush()

    # 加密一条 Cookie 演示 (AES-GCM 真加密)
    from app.core.crypto import encrypt_str
    from app.models import CloudCookieAccount, Account
    if org:
        acc = db.execute(
            select(Account).where(Account.kuaishou_id == "demo_ks_001")
        ).scalar_one_or_none()
        existing_cc = db.execute(
            select(CloudCookieAccount).where(
                CloudCookieAccount.organization_id == org.id
            ).limit(1)
        ).scalar_one_or_none()
        if not existing_cc:
            plain = ("userId=887329560; passToken=secret-eyJxxxxxxxxxxxx-abc123; "
                     "kuaishou.web.cp.api_st=abcdef; ksz_session=xyz789")
            ct, iv, tag, preview = encrypt_str(plain)
            db.add(CloudCookieAccount(
                organization_id=org.id,
                account_id=acc.id if acc else None,
                uid="887329560", nickname="演示快手账号",
                owner_code="huanghua888",
                cookie_ciphertext=ct, cookie_iv=iv, cookie_tag=tag,
                cookie_preview=preview,
                login_status="valid",
                imported_by_user_id=None,
            ))
            db.flush()

    print("          + 3 公告 + 1 加密 Cookie")


def seed_demo_phase3(db):
    """Phase 3: 自愈 playbook + 演示候选池 + agent_run + decision history."""
    from app.models import (
        AccountDecisionHistory,
        AccountStrategyMemory,
        AgentRun,
        AutopilotCycle,
        DailyCandidatePool,
        DailyPlan,
        DailyPlanItem,
        HealingDiagnosis,
        HealingPlaybook,
        ResearchNote,
        StrategyReward,
    )
    import uuid as _uuid
    from datetime import timedelta

    existing = db.execute(select(HealingPlaybook).limit(1)).scalar_one_or_none()
    if existing:
        return

    print("[seed] Phase 3 演示 (playbook + candidate-pool + agents + memory)...")

    playbooks = [
        ("cookie_invalid", "Cookie 失效 → 重登",
         r"cookie.{0,30}(invalid|expired|401)", "COOKIE_REFRESH", 0.92),
        ("rate_limited_429", "限流 → 24h 冷却",
         r"\b429\b|rate.?limit", "COOLDOWN_DRAMA", 0.85),
        ("sig3_signature_error", "sig3 错 → 6h 冷却",
         r"__NS_sig3|sig3.?invalid|result=500002", "COOLDOWN_DRAMA", 0.7),
        ("video_hls_download_fail", "HLS 下载失败 → 重采集",
         r"hls.?download.?fail|m3u8.{0,20}timeout", "RECOLLECT_VIDEO", 0.8),
        ("task_stuck_running_1h", "task running > 1h → 重排",
         r"stuck|timeout.{0,10}1h", "ENQUEUE_RETRY", 0.75),
        ("mcn_verify_failed", "MCN HMAC 失败 → 刷 token",
         r"mcn.?verify.?fail|hmac.{0,20}mismatch", "REFRESH_MCN_TOKEN", 0.85),
        ("kuaishou_auth_expired_109", "result=109 登录过期 → 刷 cookie",
         r'"result":\s*109|sid=kuaishou\.web\.cp\.api', "REFRESH_KUAISHOU_COOKIE", 0.9),
        ("kuaishou_short_link_rate_limited", "短链 result=2 限流 → 30min 冷却",
         r"share_page_result_2|kuaishou\.com/f/.+result=2", "COOLDOWN_DRAMA", 0.85),
        ("mcn_blacklist_hit", "黑名单命中 → 拦截 plan_item",
         r"drama_blacklist.{0,20}status=active", "BLOCK_PLAN_ITEM", 0.95),
        ("account_violation_burst", "24h 累计 ≥ 3 条违规 → 冻结账号",
         r"violation_count.{0,20}>=.{0,5}3", "ENQUEUE_FREEZE_ACCOUNT", 0.9),
        ("kuaishou_business_80004", "80004 作者变现权限 → 提示手工授权",
         r"\bresult.{0,5}80004", "MANUAL_REVIEW", 1.0),
        ("upload_token_expired", "upload token 过期 → 重申请",
         r"upload.?token.?expired|token.{0,20}invalid", "RETRY_UPLOAD_TOKEN", 0.8),
    ]
    for code, desc, pat, action, conf in playbooks:
        db.add(HealingPlaybook(
            code=code, description=desc, symptom_pattern=pat,
            remedy_action=action, confidence=conf,
            enabled=True, proposed_by="seed",
        ))
    db.flush()
    print(f"          + 12 playbook 规则")

    org = db.execute(
        select(Organization).where(Organization.org_code == "DEMO_MCN")
    ).scalar_one_or_none()
    if not org:
        return

    today = datetime.now(timezone.utc).date()

    samples = [
        ("仙尊下山", 80, 50, "today", "none", 88.5),
        ("陆总今天要离婚", 75, 45, "today", "none", 92.0),
        ("财源滚滚小厨神", 70, 40, "within_48h", "none", 78.5),
        ("望夫成龙", 60, 30, "within_48h", "flagged", 65.0),
        ("黑名单示例", 45, 20, "legacy", "restricted", 30.0),
    ]
    for name, fr, ur, tier, vio, comp in samples:
        db.add(DailyCandidatePool(
            pool_date=today, organization_id=org.id, drama_name=name,
            score_freshness=fr, score_url_ready=ur, score_commission=15.0,
            score_heat=8.0, score_matrix=10.0, score_penalty=0.0,
            composite_score=comp, freshness_tier=tier, violation_status=vio,
            status="pending",
        ))
    db.flush()

    plan = DailyPlan(
        organization_id=org.id, plan_date=today,
        summary="演示计划", total_items=2, finished_items=0, status="active",
    )
    db.add(plan)
    db.flush()

    acc = db.execute(
        select(Account).where(Account.kuaishou_id == "demo_ks_001")
    ).scalar_one_or_none()
    if acc:
        db.add(DailyPlanItem(
            plan_id=plan.id, organization_id=org.id, account_id=acc.id,
            drama_name="仙尊下山", recipe="kirin_mode6",
            image_mode="qitian_art", priority=70, status="pending",
            sched_at=datetime.now(timezone.utc) + timedelta(hours=1),
        ))
        db.add(DailyPlanItem(
            plan_id=plan.id, organization_id=org.id, account_id=acc.id,
            drama_name="陆总今天要离婚", recipe="zhizun_mode5_pipeline",
            image_mode="random_shapes", priority=80, status="pending",
            sched_at=datetime.now(timezone.utc) + timedelta(hours=2),
            experiment_group="A",
        ))

    cycle = AutopilotCycle(
        cycle_id=1, organization_id=org.id,
        started_at=datetime.now(timezone.utc) - timedelta(minutes=5),
        finished_at=datetime.now(timezone.utc) - timedelta(minutes=4),
        duration_ms=2300, status="ok",
        steps_executed=14, steps_skipped=2,
    )
    db.add(cycle)

    run = AgentRun(
        run_id=_uuid.uuid4().hex, agent_name="strategy_planner",
        organization_id=org.id, trigger_type="schedule",
        started_at=datetime.now(timezone.utc) - timedelta(minutes=5),
        finished_at=datetime.now(timezone.utc) - timedelta(minutes=4, seconds=58),
        duration_ms=2000, status="success",
        output_json='{"plan_id": 1, "items": 2}',
    )
    db.add(run)

    db.add(HealingDiagnosis(
        organization_id=org.id, playbook_code="cookie_invalid",
        severity="medium", summary="演示账号 cookie 错",
        target_type="account", target_id="1",
        auto_resolved=False,
        detected_at=datetime.now(timezone.utc),
    ))

    if acc:
        db.add(AccountDecisionHistory(
            account_id=acc.id, organization_id=org.id,
            drama_name="仙尊下山", recipe="kirin_mode6",
            image_mode="qitian_art",
            hypothesis="该剧在该账号历史表现不错, 预期 ¥5",
            expected_income=5.0, expected_views=20000, confidence=0.7,
            actual_income=4.5, actual_views=18000,
            verdict="correct",
            decided_at=datetime.now(timezone.utc) - timedelta(days=1),
            verdicted_at=datetime.now(timezone.utc),
        ))
        db.add(AccountStrategyMemory(
            account_id=acc.id, organization_id=org.id,
            total_decisions=10, correct_count=7,
            over_optimistic_count=2, wrong_count=1,
            ai_trust_score=0.7, income_7d=15.0, income_30d=88.5,
            preferred_recipes='{"kirin_mode6": 0.85, "zhizun_mode5": 0.6}',
        ))

    db.add(StrategyReward(
        organization_id=org.id, account_tier="testing",
        recipe="kirin_mode6", image_mode="qitian_art",
        total_trials=20, total_reward=120.5, avg_reward=6.025,
    ))

    db.add(ResearchNote(
        organization_id=None,
        note_key="2026-04-22_§27_A",
        topic="MCN 架构决策",
        content="用户架构铁令: MCN 主路, 本地备份",
        confidence=1.0, approved=True, source="human",
    ))

    db.flush()
    print("          + 5 candidate pool + 1 plan + 2 items + 1 cycle + "
          "1 agent_run + 1 diagnosis + 1 decision + 1 strategy memory")


# ============================================================
# main
# ============================================================

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--reset", action="store_true", help="先 drop 所有表 (危险)")
    ap.add_argument("--seed", action="store_true", help="种全套 seed")
    args = ap.parse_args()

    if args.reset:
        ans = input("⚠ 将删除所有表数据! 输 'yes' 确认: ")
        if ans.strip().lower() != "yes":
            print("取消")
            sys.exit(1)
        drop_all()

    create_all()

    if args.seed:
        Session = get_session_factory()
        with Session() as db:
            print("[seed] permissions...")
            n = seed_permissions(db)
            print(f"          + {n} 条新权限点")

            print("[seed] roles...")
            n = seed_roles(db)
            print(f"          + {n} 个新角色")

            print("[seed] default_role_permissions...")
            n = seed_default_role_perms(db)
            print(f"          + {n} 条角色默认权限映射")

            print("[seed] admin (super_admin / 'admin' / 默认密码 'admin')...")
            seed_admin(db)

            print("[seed] demo licenses...")
            seed_demo_licenses(db)

            print("[seed] demo org + users + accounts...")
            seed_demo_org_and_users(db)

            print("[seed] demo content (collect-pool / high-income / task-records)...")
            seed_demo_content(db)

            print("[seed] demo income (members / income / archive / violation / wallet)...")
            seed_demo_income(db)

            print("[seed] demo announcements + 加密 Cookie...")
            seed_demo_announcements(db)

            print("[seed] demo phase3 (playbook + ai memory)...")
            seed_demo_phase3(db)

            db.commit()
        print("[seed] done")

    print("=== init_db OK ===")


if __name__ == "__main__":
    main()
