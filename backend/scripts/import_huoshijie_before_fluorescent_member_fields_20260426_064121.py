"""Import confirmed Huoshijie business data into the KSJuzheng database.

The importer intentionally skips raw Kuaishou link libraries such as
``kuaishou_urls`` and ``spark_drama_info``. Those tables need product decisions
before we wire them into the app.
"""
from __future__ import annotations

import argparse
import json
import os
import secrets
from datetime import date, datetime
from decimal import Decimal
from typing import Any

import pymysql
from sqlalchemy import select

from app.core.crypto import encrypt_str
from app.core.db import Base, get_session_factory, init_engine
from app.core.security import hash_password
from app.models import (
    Account,
    AccountDecisionHistory,
    AccountGroup,
    AccountDiaryEntry,
    AccountStrategyMemory,
    AccountTaskRecord,
    AccountTierTransition,
    Announcement,
    CloudCookieAccount,
    CollectPoolAuthCode,
    CxtUser,
    CxtVideo,
    DefaultRolePermission,
    DramaCollectionRecord,
    DailyPlan,
    DailyPlanItem,
    FireflyIncome,
    FireflyMember,
    FluorescentIncome,
    FluorescentMember,
    HighIncomeDrama,
    IncomeRecord,
    IncomeArchive,
    InvitationRecord,
    KsAccount,
    KuaishouAccountBinding,
    McnAuthorization,
    MatchScoreHistory,
    OrgMember,
    Organization,
    SettlementRecord,
    SparkIncome,
    SparkMember,
    SparkPhoto,
    SparkViolationDrama,
    User,
    UserButtonPermission,
    UserPagePermission,
    ViolationPhoto,
    WalletProfile,
)


DEFAULT_ORG_SOURCE_ID = 1
VALID_ROLES = {"super_admin", "operator", "captain", "normal_user"}


def clip(value: Any, limit: int) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    return text[:limit]


def to_int(value: Any, default: int = 0) -> int:
    if value in (None, ""):
        return default
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def to_bigint(value: Any) -> int | None:
    if value in (None, ""):
        return None
    text = str(value).strip()
    if not text.isdigit():
        return None
    return int(text)


def to_float(value: Any, default: float = 0.0) -> float:
    if value in (None, ""):
        return default
    if isinstance(value, Decimal):
        return float(value)
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def percent_to_rate(value: Any, default: float = 0.8) -> float:
    num = to_float(value, default * 100)
    if num > 1:
        num = num / 100
    return max(0.0, min(num, 1.0))


def as_date(value: Any) -> date | None:
    if isinstance(value, date) and not isinstance(value, datetime):
        return value
    if isinstance(value, datetime):
        return value.date()
    if not value:
        return None
    text = str(value).strip()
    for fmt in ("%Y-%m-%d", "%Y%m%d"):
        try:
            return datetime.strptime(text, fmt).date()
        except ValueError:
            pass
    return None


def month_key(value: date | None) -> str | None:
    return value.strftime("%Y-%m") if value else None


def settlement_status(value: Any) -> str:
    return "settled" if str(value or "").lower() == "settled" else "pending"


def cxt_status(value: Any) -> str:
    return {0: "pending", 1: "active", 2: "disabled"}.get(to_int(value), "pending")


def cxt_platform(value: Any) -> str:
    return {0: "douyin", 1: "kuaishou", 2: "cxt"}.get(to_int(value), "unknown")


def chunks(items: list[Any], size: int = 1000):
    for idx in range(0, len(items), size):
        yield items[idx: idx + size]


def source_conn(args):
    password = args.mysql_password or os.getenv("HUOSHIJIE_MYSQL_PASSWORD")
    if not password:
        raise RuntimeError("Set HUOSHIJIE_MYSQL_PASSWORD or pass --mysql-password")
    return pymysql.connect(
        host=args.mysql_host,
        port=args.mysql_port,
        user=args.mysql_user,
        password=password,
        database=args.mysql_database,
        connect_timeout=10,
        read_timeout=120,
        charset="utf8mb4",
        cursorclass=pymysql.cursors.DictCursor,
    )


def fetch_all(conn, sql: str, params: tuple[Any, ...] = ()) -> list[dict[str, Any]]:
    with conn.cursor() as cur:
        cur.execute(sql, params)
        return list(cur.fetchall())


def count_source(conn) -> dict[str, int]:
    tables = [
        "mcm_organizations",
        "admin_users",
        "account_groups",
        "kuaishou_accounts",
        "ks_account",
        "cloud_cookie_accounts",
        "kuaishou_account_bindings",
        "collect_pool_auth_codes",
        "spark_org_members",
        "spark_members",
        "spark_photos",
        "spark_violation_dramas",
        "firefly_members",
        "fluorescent_members",
        "spark_income",
        "spark_income_archive",
        "firefly_income",
        "fluorescent_income",
        "fluorescent_income_archive",
        "spark_violation_photos",
        "spark_highincome_dramas",
        "drama_collections",
        "task_statistics",
        "system_announcements",
        "user_button_permissions",
        "user_page_permissions",
        "page_permissions",
        "role_default_permissions",
        "cxt_user",
        "cxt_videos",
    ]
    out: dict[str, int] = {}
    with conn.cursor() as cur:
        for table in tables:
            cur.execute(f"SELECT COUNT(*) AS c FROM `{table}`")
            out[table] = int(cur.fetchone()["c"])
    return out


def clear_target(db) -> None:
    models = [
        AccountDecisionHistory,
        AccountStrategyMemory,
        AccountDiaryEntry,
        AccountTierTransition,
        MatchScoreHistory,
        DailyPlanItem,
        DailyPlan,
        SettlementRecord,
        IncomeArchive,
        SparkIncome,
        FireflyIncome,
        FluorescentIncome,
        SparkPhoto,
        SparkViolationDrama,
        SparkMember,
        FireflyMember,
        FluorescentMember,
        OrgMember,
        ViolationPhoto,
        UserButtonPermission,
        UserPagePermission,
        DefaultRolePermission,
        WalletProfile,
        CollectPoolAuthCode,
        KuaishouAccountBinding,
        CloudCookieAccount,
        InvitationRecord,
        McnAuthorization,
        AccountTaskRecord,
        DramaCollectionRecord,
        IncomeRecord,
        Account,
        KsAccount,
        AccountGroup,
        HighIncomeDrama,
        Announcement,
        CxtVideo,
        CxtUser,
    ]
    for model in models:
        db.query(model).delete(synchronize_session=False)
    db.commit()


def ensure_target_schema(engine) -> None:
    """Keep additive schema changes safe for deployed SQLite databases."""
    if engine.dialect.name != "sqlite":
        return
    with engine.begin() as conn:
        cols = {row[1] for row in conn.exec_driver_sql("PRAGMA table_info(default_role_permissions)").fetchall()}
        if "granted" not in cols:
            conn.exec_driver_sql(
                "ALTER TABLE default_role_permissions ADD COLUMN granted INTEGER NOT NULL DEFAULT 1"
            )


def bulk_insert(db, name: str, objects: list[Any], batch_size: int = 1000) -> int:
    total = 0
    for batch in chunks(objects, batch_size):
        db.bulk_save_objects(batch)
        db.commit()
        total += len(batch)
    print(f"[import] {name}: {total}")
    return total


def import_organizations(db, rows: list[dict[str, Any]]) -> dict[int, int]:
    org_map: dict[int, int] = {}
    for row in rows:
        source_id = int(row["id"])
        code = f"HSJ_{source_id}"
        org = db.execute(
            select(Organization).where(Organization.org_code == code)
        ).scalar_one_or_none()
        settings = {
            "source": "huoshijie",
            "source_id": source_id,
            "source_org_code": row.get("org_code"),
            "include_video_collaboration": bool(row.get("include_video_collaboration", 1)),
        }
        if not org:
            org = Organization(
                name=clip(row.get("org_name"), 200) or f"Huoshijie Org {source_id}",
                org_code=code,
                org_type="mcn",
                plan_tier="enterprise",
                max_accounts=999999,
                max_users=99999,
            )
            db.add(org)
            db.flush()
        org.name = clip(row.get("org_name"), 200) or org.name
        org.is_active = bool(row.get("is_active", 1))
        org.notes = clip(row.get("description"), 1000)
        org.settings_json = json.dumps(settings, ensure_ascii=False)
        org.deleted_at = None
        org.created_at = row.get("created_at") or org.created_at
        org.updated_at = row.get("updated_at") or org.updated_at
        org_map[source_id] = org.id
    db.commit()
    print(f"[import] organizations: {len(org_map)}")
    return org_map


def import_users(
    db,
    rows: list[dict[str, Any]],
    org_map: dict[int, int],
) -> dict[int, int]:
    user_map: dict[int, int] = {}
    imported_plain = os.getenv("HUOSHIJIE_IMPORTED_USER_PASSWORD") or secrets.token_urlsafe(32)
    imported_hash = hash_password(imported_plain)
    fallback_org = org_map.get(DEFAULT_ORG_SOURCE_ID)
    parent_links: list[tuple[int, int | None]] = []

    for row in rows:
        source_id = int(row["id"])
        source_username = clip(row.get("username"), 50)
        if source_username == "admin":
            username = f"hsj_admin_{source_id}"
        else:
            username = source_username or f"hsj_user_{source_id}"
        org_id = org_map.get(to_int(row.get("organization_access")), fallback_org)
        if not org_id:
            continue
        role = str(row.get("role") or "normal_user")
        if role not in VALID_ROLES:
            role = "normal_user"
        existing = db.execute(select(User).where(User.username == username)).scalar_one_or_none()
        if not existing:
            existing = User(
                organization_id=org_id,
                username=username,
                password_hash=imported_hash,
                must_change_pw=True,
            )
            db.add(existing)
            db.flush()
        else:
            existing.password_hash = imported_hash
            existing.must_change_pw = True
        existing.organization_id = org_id
        existing.display_name = clip(row.get("nickname"), 100) or username
        existing.avatar_url = clip(row.get("avatar"), 500)
        existing.email = clip(row.get("email"), 200)
        existing.phone = clip(row.get("phone"), 32)
        existing.role = role
        existing.level = {"super_admin": 100, "operator": 50, "captain": 30}.get(role, 10)
        existing.is_superadmin = role == "super_admin"
        existing.is_active = bool(row.get("is_active", 1))
        existing.commission_rate = percent_to_rate(row.get("commission_rate"), 1.0)
        existing.commission_rate_visible = bool(row.get("commission_rate_visible", 0))
        existing.commission_amount_visible = bool(row.get("commission_amount_visible", 0))
        existing.total_income_visible = bool(row.get("total_income_visible", 0))
        existing.account_quota = None if row.get("quota") == -1 else row.get("quota")
        existing.last_login_at = row.get("last_login")
        existing.deleted_at = None
        existing.created_at = row.get("created_at") or existing.created_at
        existing.updated_at = row.get("updated_at") or existing.updated_at
        user_map[source_id] = existing.id
        parent_links.append((existing.id, row.get("parent_user_id")))

    db.flush()
    for target_id, source_parent_id in parent_links:
        target_parent_id = user_map.get(to_int(source_parent_id))
        if target_parent_id:
            user = db.get(User, target_id)
            if user:
                user.parent_user_id = target_parent_id
    active_ids = set(user_map.values())
    if active_ids:
        stale_users = db.execute(
            select(User).where(
                User.username != "admin",
                ~User.id.in_(active_ids),
                User.deleted_at.is_(None),
            )
        ).scalars().all()
        now = datetime.utcnow()
        for stale_user in stale_users:
            stale_user.is_active = False
            stale_user.deleted_at = now
    db.commit()
    restore_local_admin(db)
    print(f"[import] users: {len(user_map)}")
    return user_map


def restore_local_admin(db) -> None:
    super_org = db.execute(
        select(Organization).where(Organization.org_code == "SUPER")
    ).scalar_one_or_none()
    admin = db.execute(select(User).where(User.username == "admin")).scalar_one_or_none()
    if not super_org or not admin:
        return
    admin.organization_id = super_org.id
    admin.role = "super_admin"
    admin.is_superadmin = True
    admin.is_active = True
    db.commit()


def import_wallets(db, user_rows: list[dict[str, Any]], user_map: dict[int, int]) -> None:
    objects: list[WalletProfile] = []
    for row in user_rows:
        info = row.get("alipay_info")
        if not info:
            continue
        try:
            data = json.loads(info)
        except (TypeError, json.JSONDecodeError):
            continue
        user_id = user_map.get(int(row["id"]))
        if not user_id:
            continue
        objects.append(
            WalletProfile(
                user_id=user_id,
                real_name=clip(data.get("name"), 100),
                alipay_name=clip(data.get("name"), 100),
                alipay_account=clip(data.get("account"), 100),
                notes="Imported from huoshijie admin_users.alipay_info",
            )
        )
    bulk_insert(db, "wallet_profiles", objects)


def import_permissions(db, conn, user_map: dict[int, int]) -> None:
    button_objects: list[UserButtonPermission] = []
    seen_buttons: set[tuple[int, str]] = set()
    for row in fetch_all(conn, "SELECT * FROM user_button_permissions"):
        user_id = user_map.get(to_int(row.get("user_id")))
        code = clip(row.get("button_key"), 100)
        if not user_id or not code or (user_id, code) in seen_buttons:
            continue
        seen_buttons.add((user_id, code))
        button_objects.append(
            UserButtonPermission(
                user_id=user_id,
                permission_code=code,
                granted=1 if to_int(row.get("is_allowed"), 1) else 0,
            )
        )
    bulk_insert(db, "user_button_permissions", button_objects)

    page_objects: list[UserPagePermission] = []
    seen_pages: set[tuple[int, str]] = set()
    for row in fetch_all(conn, "SELECT * FROM user_page_permissions"):
        user_id = user_map.get(to_int(row.get("user_id")))
        code = clip(row.get("page_key"), 100)
        if not user_id or not code or (user_id, code) in seen_pages:
            continue
        seen_pages.add((user_id, code))
        page_objects.append(
            UserPagePermission(
                user_id=user_id,
                permission_code=code,
                granted=1 if to_int(row.get("is_allowed"), 1) else 0,
            )
        )
    for row in fetch_all(conn, "SELECT * FROM page_permissions"):
        user_id = user_map.get(to_int(row.get("user_id")))
        code = clip(row.get("page_key"), 100)
        if not user_id or not code or (user_id, code) in seen_pages:
            continue
        seen_pages.add((user_id, code))
        page_objects.append(
            UserPagePermission(
                user_id=user_id,
                permission_code=code,
                granted=1 if to_int(row.get("is_allowed"), 1) else 0,
            )
        )
    bulk_insert(db, "user_page_permissions", page_objects)

    default_objects: list[DefaultRolePermission] = []
    seen_defaults: set[tuple[str, str, str]] = set()
    for row in fetch_all(conn, "SELECT * FROM role_default_permissions"):
        role = clip(row.get("role"), 20)
        perm_type = clip(row.get("perm_type"), 50)
        code = clip(row.get("perm_key"), 100)
        key = (role or "", perm_type or "", code or "")
        if not role or not perm_type or not code or key in seen_defaults:
            continue
        seen_defaults.add(key)
        default_objects.append(
            DefaultRolePermission(
                role=role,
                permission_type=perm_type,
                permission_code=code,
                granted=1 if to_int(row.get("is_allowed"), 1) else 0,
            )
        )
    bulk_insert(db, "default_role_permissions", default_objects)


def import_groups(
    db,
    rows: list[dict[str, Any]],
    user_map: dict[int, int],
    default_org_id: int,
) -> dict[int, int]:
    objects: list[AccountGroup] = []
    for row in rows:
        owner_id = user_map.get(to_int(row.get("owner_id")))
        org_id = db.get(User, owner_id).organization_id if owner_id else default_org_id
        objects.append(
            AccountGroup(
                organization_id=org_id,
                owner_user_id=owner_id,
                name=clip(row.get("group_name"), 100) or f"Group {row['id']}",
                color=clip(row.get("color"), 20),
                created_at=row.get("created_at"),
                updated_at=row.get("updated_at"),
            )
        )
    bulk_insert(db, "account_groups", objects)

    group_map: dict[int, int] = {}
    target_rows = db.execute(select(AccountGroup)).scalars().all()
    by_key = {(g.owner_user_id, g.name): g.id for g in target_rows}
    for row in rows:
        owner_id = user_map.get(to_int(row.get("owner_id")))
        name = clip(row.get("group_name"), 100) or f"Group {row['id']}"
        group_map[int(row["id"])] = by_key.get((owner_id, name))
    return {k: v for k, v in group_map.items() if v}


def account_status(row: dict[str, Any]) -> str:
    if row.get("is_blacklisted"):
        return "disabled"
    raw = str(row.get("account_status") or "normal")
    return "disabled" if raw in {"suspended", "disabled"} else "active"


def import_accounts(
    db,
    rows: list[dict[str, Any]],
    org_map: dict[int, int],
    user_map: dict[int, int],
    group_map: dict[int, int],
) -> None:
    fallback_org = org_map.get(DEFAULT_ORG_SOURCE_ID)
    objects: list[Account] = []
    for row in rows:
        org_id = org_map.get(to_int(row.get("organization_id")), fallback_org)
        if not org_id:
            continue
        remark = {
            "source": "huoshijie.kuaishou_accounts",
            "source_id": row.get("id"),
            "platform": row.get("platform"),
            "contract_status": row.get("contract_status"),
            "org_note": row.get("org_note"),
            "phone_number": row.get("phone_number"),
            "real_name": row.get("real_name"),
            "blacklist_reason": row.get("blacklist_reason"),
            "status_note": row.get("status_note"),
        }
        objects.append(
            Account(
                organization_id=org_id,
                assigned_user_id=user_map.get(to_int(row.get("owner_id"))),
                group_id=group_map.get(to_int(row.get("group_id"))),
                kuaishou_id=clip(row.get("uid"), 64),
                real_uid=clip(row.get("uid_real") or row.get("uid"), 32),
                nickname=clip(row.get("nickname"), 100),
                status=account_status(row),
                mcn_status="authorized" if row.get("is_mcm_member") else "unauthorized",
                sign_status=clip(row.get("contract_status"), 20),
                commission_rate=percent_to_rate(row.get("commission_rate")),
                device_serial=clip(row.get("device_serial"), 64),
                remark=json.dumps(remark, ensure_ascii=False),
                imported_at=row.get("created_at"),
                created_at=row.get("created_at"),
                updated_at=row.get("updated_at"),
            )
        )
    bulk_insert(db, "accounts", objects)


def account_maps(db) -> tuple[dict[str, int], dict[str, int], dict[str, int]]:
    uid_map: dict[str, int] = {}
    real_uid_map: dict[str, int] = {}
    org_by_uid: dict[str, int] = {}
    for acc in db.execute(select(Account)).scalars():
        if acc.kuaishou_id:
            uid_map[acc.kuaishou_id] = acc.id
            org_by_uid[acc.kuaishou_id] = acc.organization_id
        if acc.real_uid:
            real_uid_map[acc.real_uid] = acc.id
            org_by_uid[acc.real_uid] = acc.organization_id
    return uid_map, real_uid_map, org_by_uid


def import_ks_accounts(db, rows: list[dict[str, Any]], org_id: int) -> None:
    objects: list[KsAccount] = []
    seen: set[str] = set()
    for row in rows:
        uid = clip(row.get("uid"), 32)
        if not uid or uid in seen:
            continue
        seen.add(uid)
        objects.append(
            KsAccount(
                organization_id=org_id,
                account_name=clip(row.get("username"), 100),
                kuaishou_uid=uid,
                device_code=clip(row.get("device_num"), 64),
            )
        )
    bulk_insert(db, "ks_accounts", objects)


def import_cookies(
    db,
    rows: list[dict[str, Any]],
    org_map: dict[int, int],
    user_map: dict[int, int],
) -> None:
    objects: list[CloudCookieAccount] = []
    default_org = org_map.get(DEFAULT_ORG_SOURCE_ID)
    for row in rows:
        owner_raw = row.get("owner_code")
        owner_user_id = user_map.get(to_int(owner_raw))
        org_id = db.get(User, owner_user_id).organization_id if owner_user_id else default_org
        if not org_id:
            continue
        plain = str(row.get("cookies") or "")
        ciphertext = iv = tag = None
        preview = None
        if plain:
            ciphertext, iv, tag, preview = encrypt_str(plain)
        objects.append(
            CloudCookieAccount(
                organization_id=org_id,
                assigned_user_id=owner_user_id,
                uid=clip(row.get("kuaishou_uid") or row.get("account_id"), 32),
                nickname=clip(row.get("account_name") or row.get("kuaishou_name"), 100),
                owner_code=clip(owner_raw, 50),
                cookie_ciphertext=ciphertext,
                cookie_iv=iv,
                cookie_tag=tag,
                cookie_preview=preview,
                login_status="valid"
                if row.get("login_status") == "logged_in"
                else "expired",
                last_success_at=row.get("login_time"),
                imported_by_user_id=owner_user_id,
                created_at=row.get("created_at"),
                updated_at=row.get("updated_at"),
            )
        )
    bulk_insert(db, "cloud_cookie_accounts", objects)


def import_bindings(db, rows: list[dict[str, Any]], uid_map: dict[str, int], real_uid_map: dict[str, int]) -> None:
    users_by_name = {
        (user.username or "").strip(): user.id
        for user in db.execute(select(User)).scalars().all()
        if user.username
    }
    objects: list[KuaishouAccountBinding] = []
    for row in rows:
        kuaishou_id = clip(row.get("kuaishou_id"), 50)
        machine_id = clip(row.get("machine_id"), 100)
        operator_account = clip(row.get("operator_account"), 100)
        if not kuaishou_id or not machine_id or not operator_account:
            continue
        objects.append(
            KuaishouAccountBinding(
                source_id=to_int(row.get("id")),
                account_id=uid_map.get(kuaishou_id) or real_uid_map.get(kuaishou_id),
                user_id=users_by_name.get(operator_account.strip()),
                kuaishou_id=kuaishou_id,
                machine_id=machine_id,
                operator_account=operator_account,
                bind_time=row.get("bind_time"),
                last_used_time=row.get("last_used_time"),
                status=clip(row.get("status"), 20) or "active",
                remark=clip(row.get("remark"), 255),
                created_at=row.get("bind_time"),
                updated_at=row.get("last_used_time") or row.get("bind_time"),
            )
        )
    bulk_insert(db, "kuaishou_account_bindings", objects)


def import_collect_pool_auth_codes(db, rows: list[dict[str, Any]], user_map: dict[int, int]) -> None:
    objects: list[CollectPoolAuthCode] = []
    seen: set[str] = set()
    for row in rows:
        auth_code = clip(row.get("auth_code"), 100)
        if not auth_code or auth_code in seen:
            continue
        seen.add(auth_code)
        objects.append(
            CollectPoolAuthCode(
                auth_code=auth_code,
                name=clip(row.get("name"), 100),
                is_active=bool(to_int(row.get("is_active"), 1)),
                expire_at=row.get("expire_at"),
                created_by_user_id=user_map.get(to_int(row.get("created_by"))),
                created_at=row.get("created_at"),
                updated_at=row.get("updated_at"),
            )
        )
    bulk_insert(db, "collect_pool_auth_codes", objects)


def import_org_members(
    db,
    rows: list[dict[str, Any]],
    org_map: dict[int, int],
    real_uid_map: dict[str, int],
) -> None:
    objects: list[OrgMember] = []
    for row in rows:
        source_org = to_int(row.get("org_id"), DEFAULT_ORG_SOURCE_ID)
        org_id = org_map.get(source_org)
        member_id = to_bigint(row.get("member_id"))
        if not org_id or member_id is None:
            continue
        objects.append(
            OrgMember(
                organization_id=org_id,
                member_id=member_id,
                account_id=real_uid_map.get(str(member_id)),
                nickname=clip(row.get("member_name"), 100),
                avatar=clip(row.get("member_head"), 500),
                fans_count=to_int(row.get("fans_count")),
                broker_name=clip(row.get("broker_name"), 100),
                cooperation_type=clip(row.get("agreement_types"), 50),
                content_category=clip(row.get("content_category"), 50),
                mcn_level=clip(row.get("mcn_grade"), 50),
                renewal_status="active"
                if to_int(row.get("contract_renew_status")) == 8
                else "pending",
                contract_expires_at=as_date(row.get("contract_expire_date")),
                synced_at=row.get("updated_at"),
                created_at=row.get("created_at"),
                updated_at=row.get("updated_at"),
            )
        )
    bulk_insert(db, "org_members", objects)


def import_program_members(
    db,
    spark_rows,
    firefly_rows,
    fluorescent_rows,
    org_map,
    real_uid_map,
    org_by_uid,
) -> None:
    default_org = org_map.get(DEFAULT_ORG_SOURCE_ID)
    spark_objects: list[SparkMember] = []
    for row in spark_rows:
        member_id = to_bigint(row.get("member_id"))
        org_id = org_map.get(to_int(row.get("org_id"), DEFAULT_ORG_SOURCE_ID))
        if member_id is None or not org_id:
            continue
        spark_objects.append(
            SparkMember(
                organization_id=org_id,
                member_id=member_id,
                account_id=real_uid_map.get(str(member_id)),
                nickname=clip(row.get("member_name"), 100),
                fans_count=to_int(row.get("fans_count")),
                broker_name=clip(row.get("broker_name"), 100),
                task_count=to_int(row.get("org_task_num")),
                hidden=False,
                synced_at=row.get("updated_at"),
                created_at=row.get("created_at"),
                updated_at=row.get("updated_at"),
            )
        )
    bulk_insert(db, "spark_members", spark_objects)

    firefly_objects: list[FireflyMember] = []
    for row in firefly_rows:
        member_id = to_bigint(row.get("author_id"))
        if member_id is None:
            continue
        org_id = org_by_uid.get(str(member_id), default_org)
        if not org_id:
            continue
        firefly_objects.append(
            FireflyMember(
                organization_id=org_id,
                member_id=member_id,
                account_id=real_uid_map.get(str(member_id)),
                nickname=clip(row.get("author_name"), 100),
                total_amount=to_float(row.get("total_income")),
                org_task_num=to_int(row.get("record_count")),
                hidden=False,
                synced_at=row.get("updated_at"),
                created_at=row.get("created_at"),
                updated_at=row.get("updated_at"),
            )
        )
    bulk_insert(db, "firefly_members", firefly_objects)

    fluor_objects: list[FluorescentMember] = []
    for row in fluorescent_rows:
        member_id = to_bigint(row.get("member_id"))
        org_id = org_map.get(to_int(row.get("org_id"), DEFAULT_ORG_SOURCE_ID))
        if member_id is None or not org_id:
            continue
        fluor_objects.append(
            FluorescentMember(
                organization_id=org_id,
                member_id=member_id,
                account_id=real_uid_map.get(str(member_id)),
                nickname=clip(row.get("member_name"), 100),
                fans_count=to_int(row.get("fans_count")),
                broker_name=clip(row.get("broker_name"), 100),
                total_amount=to_float(row.get("total_amount")),
                org_task_num=to_int(row.get("org_task_num")),
                synced_at=row.get("updated_at"),
                created_at=row.get("created_at"),
                updated_at=row.get("updated_at"),
            )
        )
    bulk_insert(db, "fluorescent_members", fluor_objects)


def import_spark_photos(
    db,
    rows: list[dict[str, Any]],
    org_map: dict[int, int],
    real_uid_map: dict[str, int],
) -> None:
    objects: list[SparkPhoto] = []
    default_org = org_map.get(DEFAULT_ORG_SOURCE_ID)
    for row in rows:
        photo_id = clip(row.get("photo_id"), 50)
        if not photo_id:
            continue
        member_id = to_bigint(row.get("member_id"))
        org_id = org_map.get(to_int(row.get("org_id"), DEFAULT_ORG_SOURCE_ID), default_org)
        objects.append(
            SparkPhoto(
                source_id=to_bigint(row.get("id")),
                organization_id=org_id,
                account_id=real_uid_map.get(str(member_id)) if member_id is not None else None,
                photo_id=photo_id,
                member_id=member_id,
                member_name=clip(row.get("member_name"), 100),
                title=clip(row.get("title"), 500),
                view_count=to_int(row.get("view_count")),
                like_count=to_int(row.get("like_count")),
                comment_count=to_int(row.get("comment_count")),
                duration=clip(row.get("duration"), 20),
                publish_time=to_bigint(row.get("publish_time")),
                publish_date=row.get("publish_date"),
                cover_url=clip(row.get("cover_url"), 500),
                play_url=clip(row.get("play_url"), 500),
                avatar_url=clip(row.get("avatar_url"), 500),
                created_at=row.get("created_at"),
                updated_at=row.get("updated_at"),
            )
        )
    bulk_insert(db, "spark_photos", objects)


def import_spark_violation_dramas(
    db,
    rows: list[dict[str, Any]],
    org_map: dict[int, int],
) -> None:
    objects: list[SparkViolationDrama] = []
    default_org = org_map.get(DEFAULT_ORG_SOURCE_ID)
    for row in rows:
        title = clip(row.get("drama_title"), 200)
        org_id = org_map.get(to_int(row.get("org_id"), DEFAULT_ORG_SOURCE_ID), default_org)
        if not title or not org_id:
            continue
        objects.append(
            SparkViolationDrama(
                source_id=to_int(row.get("id")),
                organization_id=org_id,
                drama_title=title,
                source_photo_id=clip(row.get("source_photo_id"), 50),
                source_caption=row.get("source_caption"),
                user_id=to_bigint(row.get("user_id")),
                username=clip(row.get("username"), 100),
                violation_count=to_int(row.get("violation_count"), 1),
                last_violation_time=to_bigint(row.get("last_violation_time")),
                last_violation_date=row.get("last_violation_date"),
                sub_biz=clip(row.get("sub_biz"), 50),
                status_desc=clip(row.get("status_desc"), 50),
                reason=row.get("reason"),
                media_url=row.get("media_url"),
                thumb_url=row.get("thumb_url"),
                broker_name=clip(row.get("broker_name"), 100),
                is_blacklisted=bool(to_int(row.get("is_blacklisted"))),
                blacklisted_at=row.get("blacklisted_at"),
                created_at=row.get("created_at"),
                updated_at=row.get("updated_at"),
            )
        )
    bulk_insert(db, "spark_violation_dramas", objects)


def import_income(
    db,
    conn,
    org_map,
    real_uid_map,
    org_by_uid,
) -> None:
    spark_rows = fetch_all(conn, "SELECT * FROM spark_income")
    spark_objects: list[SparkIncome] = []
    for row in spark_rows:
        member_id = to_bigint(row.get("member_id"))
        org_id = org_map.get(to_int(row.get("org_id"), DEFAULT_ORG_SOURCE_ID))
        if member_id is None or not org_id:
            continue
        start = as_date(row.get("start_date"))
        amount = to_float(row.get("income"))
        spark_objects.append(
            SparkIncome(
                organization_id=org_id,
                member_id=member_id,
                account_id=real_uid_map.get(str(member_id)),
                task_id=clip(row.get("task_id"), 64),
                task_name=clip(row.get("task_name"), 200),
                income_amount=amount,
                commission_rate=1.0,
                commission_amount=amount,
                start_date=start,
                end_date=as_date(row.get("end_date")),
                settlement_status="pending",
                archived_year_month=month_key(start),
                created_at=row.get("created_at"),
                updated_at=row.get("updated_at"),
            )
        )
    bulk_insert(db, "spark_income", spark_objects)

    default_org = org_map.get(DEFAULT_ORG_SOURCE_ID)
    firefly_rows = fetch_all(conn, "SELECT * FROM firefly_income")
    firefly_objects: list[FireflyIncome] = []
    for row in firefly_rows:
        member_id = to_bigint(row.get("author_id"))
        if member_id is None:
            continue
        org_id = org_by_uid.get(str(member_id), default_org)
        if not org_id:
            continue
        income_date = as_date(row.get("income_date"))
        amount = to_float(row.get("settlement_amount"))
        rate = percent_to_rate(row.get("commission_rate"), 1.0)
        firefly_objects.append(
            FireflyIncome(
                organization_id=org_id,
                member_id=member_id,
                account_id=real_uid_map.get(str(member_id)),
                task_id=clip(row.get("video_id"), 64),
                task_name=clip(row.get("task_name"), 200),
                income_amount=amount,
                commission_rate=rate,
                commission_amount=to_float(row.get("commission_amount"), amount * rate),
                income_date=income_date,
                settlement_status=settlement_status(row.get("settlement_status")),
                archived_year_month=month_key(income_date),
                created_at=row.get("created_at"),
                updated_at=row.get("updated_at"),
            )
        )
    bulk_insert(db, "firefly_income", firefly_objects)

    fluorescent_rows = fetch_all(conn, "SELECT * FROM fluorescent_income")
    fluor_objects: list[FluorescentIncome] = []
    for row in fluorescent_rows:
        member_id = to_bigint(row.get("member_id"))
        org_id = org_map.get(to_int(row.get("org_id"), DEFAULT_ORG_SOURCE_ID))
        if member_id is None or not org_id:
            continue
        amount = to_float(row.get("income"))
        fluor_objects.append(
            FluorescentIncome(
                organization_id=org_id,
                member_id=member_id,
                account_id=real_uid_map.get(str(member_id)),
                task_id=clip(row.get("task_id"), 64),
                task_name=clip(row.get("task_name"), 200),
                income_amount=amount,
                total_amount=amount,
                org_task_num=1,
                income_date=as_date(row.get("task_start_time")),
                created_at=row.get("created_at"),
                updated_at=row.get("updated_at"),
            )
        )
    bulk_insert(db, "fluorescent_income", fluor_objects)


def import_archives(db, conn, org_map, real_uid_map) -> None:
    objects: list[IncomeArchive] = []
    seen: set[tuple[int, str, int, int, int]] = set()
    for program, table in [
        ("spark", "spark_income_archive"),
        ("fluorescent", "fluorescent_income_archive"),
    ]:
        rows = fetch_all(conn, f"SELECT * FROM {table}")
        for row in rows:
            member_id = to_bigint(row.get("member_id"))
            org_id = org_map.get(to_int(row.get("org_id"), DEFAULT_ORG_SOURCE_ID))
            year = to_int(row.get("archive_year"))
            month = to_int(row.get("archive_month"))
            if member_id is None or not org_id or not year or not month:
                continue
            key = (org_id, program, year, month, member_id)
            if key in seen:
                continue
            seen.add(key)
            amount = to_float(row.get("total_amount"))
            rate = percent_to_rate(row.get("commission_rate"), 1.0)
            objects.append(
                IncomeArchive(
                    organization_id=org_id,
                    program_type=program,
                    year=year,
                    month=month,
                    member_id=member_id,
                    account_id=real_uid_map.get(str(member_id)),
                    total_amount=amount,
                    commission_rate=rate,
                    commission_amount=to_float(row.get("commission_amount"), amount * rate),
                    settlement_status=settlement_status(row.get("settlement_status")),
                    archived_at=row.get("archived_at"),
                )
            )
    bulk_insert(db, "income_archives", objects)


def import_violations(db, rows, org_map, real_uid_map) -> None:
    objects: list[ViolationPhoto] = []
    seen: set[tuple[int, str]] = set()
    for row in rows:
        org_id = org_map.get(to_int(row.get("org_id"), DEFAULT_ORG_SOURCE_ID))
        work_id = clip(row.get("photo_id"), 64)
        if not org_id or not work_id or (org_id, work_id) in seen:
            continue
        seen.add((org_id, work_id))
        uid = clip(row.get("user_id"), 32)
        reason = "\n".join(
            x for x in [str(row.get("reason") or ""), str(row.get("suggestion") or "")]
            if x
        )
        objects.append(
            ViolationPhoto(
                organization_id=org_id,
                account_id=real_uid_map.get(uid or ""),
                work_id=work_id,
                uid=uid,
                thumbnail=clip(row.get("thumb_url"), 500),
                description=row.get("caption"),
                business_type=clip(row.get("sub_biz"), 50),
                violation_reason=reason or None,
                view_count=to_int(row.get("view_count")),
                like_count=to_int(row.get("like_count")),
                appeal_status=clip(row.get("appeal_status_desc") or row.get("status_desc"), 20),
                appeal_reason=row.get("appeal_detail"),
                published_at=row.get("publish_date"),
                detected_at=row.get("updated_at") or row.get("created_at"),
                created_at=row.get("created_at"),
                updated_at=row.get("updated_at"),
            )
        )
    bulk_insert(db, "violation_photos", objects)


def import_high_income(db, rows, default_org_id: int) -> None:
    objects: list[HighIncomeDrama] = []
    seen: set[str] = set()
    for row in rows:
        title = clip(row.get("title"), 200)
        if not title or title in seen:
            continue
        seen.add(title)
        objects.append(
            HighIncomeDrama(
                organization_id=default_org_id,
                drama_name=title,
                source_program="manual",
                notes="Imported from huoshijie.spark_highincome_dramas",
                created_at=row.get("created_at"),
                updated_at=row.get("created_at"),
            )
        )
    bulk_insert(db, "high_income_dramas", objects)


def import_drama_collection_rollups(db, conn, org_map, uid_map) -> None:
    rows = fetch_all(
        conn,
        """
        SELECT
            COALESCE(ka.organization_id, %s) AS source_org_id,
            dc.kuaishou_uid,
            MAX(dc.kuaishou_name) AS kuaishou_name,
            COUNT(*) AS total_count,
            SUM(CASE WHEN dc.plan_mode='spark' THEN 1 ELSE 0 END) AS spark_count,
            SUM(CASE WHEN dc.plan_mode='firefly' THEN 1 ELSE 0 END) AS firefly_count,
            SUM(CASE WHEN dc.plan_mode='fluorescent' THEN 1 ELSE 0 END) AS fluorescent_count,
            MAX(dc.collected_at) AS last_collected_at
        FROM drama_collections dc
        LEFT JOIN kuaishou_accounts ka ON ka.uid = dc.kuaishou_uid
        GROUP BY source_org_id, dc.kuaishou_uid
        """,
        (DEFAULT_ORG_SOURCE_ID,),
    )
    objects: list[DramaCollectionRecord] = []
    for row in rows:
        org_id = org_map.get(to_int(row.get("source_org_id"), DEFAULT_ORG_SOURCE_ID))
        uid = clip(row.get("kuaishou_uid"), 32)
        if not org_id or not uid:
            continue
        objects.append(
            DramaCollectionRecord(
                organization_id=org_id,
                account_id=uid_map.get(uid),
                account_uid=uid,
                account_name=clip(row.get("kuaishou_name"), 100),
                total_count=to_int(row.get("total_count")),
                spark_count=to_int(row.get("spark_count")),
                firefly_count=to_int(row.get("firefly_count")),
                fluorescent_count=to_int(row.get("fluorescent_count")),
                last_collected_at=row.get("last_collected_at"),
            )
        )
    bulk_insert(db, "drama_collection_records", objects)


def import_task_statistics(db, rows, uid_map, org_by_uid) -> None:
    objects: list[AccountTaskRecord] = []
    for row in rows:
        uid = str(row.get("uid") or "")
        account_id = uid_map.get(uid)
        org_id = org_by_uid.get(uid)
        if not account_id or not org_id:
            continue
        objects.append(
            AccountTaskRecord(
                account_id=account_id,
                organization_id=org_id,
                task_type=clip(row.get("task_type"), 32) or "unknown",
                drama_name=clip(row.get("drama_name"), 200),
                success=str(row.get("status") or "").lower() == "success",
                duration_ms=to_int(row.get("duration")) * 1000,
                error_message=row.get("error_message"),
                created_at=row.get("created_at") or row.get("start_time"),
                updated_at=row.get("end_time") or row.get("created_at"),
            )
        )
    bulk_insert(db, "account_task_records", objects)


def import_announcements(db, rows) -> None:
    objects: list[Announcement] = []
    for row in rows:
        priority = to_int(row.get("priority"))
        objects.append(
            Announcement(
                organization_id=None,
                title=clip(row.get("title"), 200) or "Untitled",
                content=str(row.get("content") or ""),
                level="warning" if priority >= 2 else "info",
                pinned=priority > 0,
                active=bool(row.get("is_enabled", 1)),
                created_at=row.get("created_at"),
                updated_at=row.get("updated_at"),
            )
        )
    bulk_insert(db, "announcements", objects)


def import_cxt(db, conn, org_map, user_rows, user_map) -> None:
    default_org = org_map.get(DEFAULT_ORG_SOURCE_ID)
    auth_to_org: dict[str, int] = {}
    for row in user_rows:
        target_id = user_map.get(int(row["id"]))
        if not target_id:
            continue
        target = db.get(User, target_id)
        if not target:
            continue
        for key in (row.get("username"), row.get("default_auth_code")):
            text = clip(key, 50)
            if text:
                auth_to_org[text] = target.organization_id

    users = fetch_all(conn, "SELECT * FROM cxt_user")
    user_objects: list[CxtUser] = []
    for row in users:
        uid = clip(row.get("uid"), 64)
        if not uid:
            continue
        org_id = auth_to_org.get(str(row.get("auth_code") or ""), default_org)
        if not org_id:
            continue
        user_objects.append(
            CxtUser(
                organization_id=org_id,
                platform_uid=uid,
                username=clip(row.get("note") or row.get("uid"), 100),
                auth_code=clip(row.get("auth_code"), 50),
                note=clip(row.get("note"), 200),
                status=cxt_status(row.get("status")),
            )
        )
    bulk_insert(db, "cxt_users", user_objects)

    videos = fetch_all(conn, "SELECT * FROM cxt_videos")
    video_objects: list[CxtVideo] = []
    seen_videos: set[tuple[str, str]] = set()
    for row in videos:
        platform = cxt_platform(row.get("platform"))
        aweme_id = clip(row.get("aweme_id"), 100)
        dedupe_key = (platform, aweme_id or "")
        if aweme_id and dedupe_key in seen_videos:
            continue
        seen_videos.add(dedupe_key)
        video_objects.append(
            CxtVideo(
                organization_id=default_org,
                title=clip(row.get("title"), 500),
                author=clip(row.get("author"), 100),
                sec_user_id=clip(row.get("sec_user_id"), 200),
                aweme_id=aweme_id,
                description=row.get("description"),
                video_url=row.get("video_url"),
                cover_url=row.get("cover_url"),
                duration=row.get("duration"),
                comment_count=to_int(row.get("comment_count")),
                collect_count=to_int(row.get("collect_count")),
                recommend_count=to_int(row.get("recommend_count")),
                share_count=to_int(row.get("share_count")),
                play_count=to_int(row.get("play_count")),
                digg_count=to_int(row.get("digg_count")),
                platform=platform,
                status="active",
                created_at=row.get("created_at"),
                updated_at=row.get("created_at"),
            )
        )
    bulk_insert(db, "cxt_videos", video_objects)


def run_import(args) -> None:
    engine = init_engine()
    Base.metadata.create_all(engine)
    ensure_target_schema(engine)
    Session = get_session_factory()
    conn = source_conn(args)
    try:
        counts = count_source(conn)
        print("[source-counts]", json.dumps(counts, ensure_ascii=False, indent=2))
        if not args.apply:
            print("[dry-run] pass --apply to write target database")
            return

        with Session() as db:
            if args.replace:
                clear_target(db)

            org_rows = fetch_all(conn, "SELECT * FROM mcm_organizations")
            user_rows = fetch_all(conn, "SELECT * FROM admin_users")
            org_map = import_organizations(db, org_rows)
            fallback_org_id = org_map[DEFAULT_ORG_SOURCE_ID]
            user_map = import_users(db, user_rows, org_map)
            import_permissions(db, conn, user_map)
            import_wallets(db, user_rows, user_map)
            group_rows = fetch_all(conn, "SELECT * FROM account_groups")
            group_map = import_groups(db, group_rows, user_map, fallback_org_id)

            account_rows = fetch_all(conn, "SELECT * FROM kuaishou_accounts")
            import_accounts(db, account_rows, org_map, user_map, group_map)
            uid_map, real_uid_map, org_by_uid = account_maps(db)

            import_ks_accounts(db, fetch_all(conn, "SELECT * FROM ks_account"), fallback_org_id)
            import_cookies(db, fetch_all(conn, "SELECT * FROM cloud_cookie_accounts"), org_map, user_map)
            import_bindings(
                db,
                fetch_all(conn, "SELECT * FROM kuaishou_account_bindings"),
                uid_map,
                real_uid_map,
            )
            import_collect_pool_auth_codes(
                db,
                fetch_all(conn, "SELECT * FROM collect_pool_auth_codes"),
                user_map,
            )
            import_org_members(
                db,
                fetch_all(conn, "SELECT * FROM spark_org_members"),
                org_map,
                real_uid_map,
            )
            import_program_members(
                db,
                fetch_all(conn, "SELECT * FROM spark_members"),
                fetch_all(conn, "SELECT * FROM firefly_members"),
                fetch_all(conn, "SELECT * FROM fluorescent_members"),
                org_map,
                real_uid_map,
                org_by_uid,
            )
            import_spark_photos(db, fetch_all(conn, "SELECT * FROM spark_photos"), org_map, real_uid_map)
            import_income(db, conn, org_map, real_uid_map, org_by_uid)
            import_archives(db, conn, org_map, real_uid_map)
            import_violations(
                db,
                fetch_all(conn, "SELECT * FROM spark_violation_photos"),
                org_map,
                real_uid_map,
            )
            import_spark_violation_dramas(
                db,
                fetch_all(conn, "SELECT * FROM spark_violation_dramas"),
                org_map,
            )
            import_high_income(
                db,
                fetch_all(conn, "SELECT * FROM spark_highincome_dramas"),
                fallback_org_id,
            )
            import_drama_collection_rollups(db, conn, org_map, uid_map)
            import_task_statistics(db, fetch_all(conn, "SELECT * FROM task_statistics"), uid_map, org_by_uid)
            import_announcements(db, fetch_all(conn, "SELECT * FROM system_announcements"))
            import_cxt(db, conn, org_map, user_rows, user_map)

        print("[import] done")
    finally:
        conn.close()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--mysql-host", default=os.getenv("HUOSHIJIE_MYSQL_HOST", "10.5.0.12"))
    parser.add_argument("--mysql-port", type=int, default=int(os.getenv("HUOSHIJIE_MYSQL_PORT", "3306")))
    parser.add_argument("--mysql-user", default=os.getenv("HUOSHIJIE_MYSQL_USER", "xhy_app"))
    parser.add_argument("--mysql-password", default=None)
    parser.add_argument("--mysql-database", default=os.getenv("HUOSHIJIE_MYSQL_DATABASE", "huoshijie"))
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--replace", action="store_true")
    return parser.parse_args()


if __name__ == "__main__":
    run_import(parse_args())
