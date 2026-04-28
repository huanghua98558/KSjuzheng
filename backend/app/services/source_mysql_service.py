from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any

from sqlalchemy import text
from sqlalchemy.orm import Session


ROLE_LEVELS = {
    "super_admin": 100,
    "operator": 50,
    "captain": 30,
    "normal_user": 10,
}


def is_source_mysql(db: Session) -> bool:
    bind = db.get_bind()
    return bind is not None and bind.dialect.name.lower().startswith("mysql")


def _role_level(role: str | None) -> int:
    return ROLE_LEVELS.get(str(role or "normal_user"), 10)


def _rate_to_fraction(value: Any) -> float:
    if value in (None, ""):
        return 1.0
    try:
        num = float(value)
    except (TypeError, ValueError):
        return 1.0
    return num / 100 if num > 1 else num


def _truthy(value: Any, default: bool = False) -> bool:
    if value is None:
        return default
    return bool(int(value)) if isinstance(value, (int, bool)) else str(value).strip().lower() in {"1", "true", "yes", "y"}


@dataclass
class SourceUser:
    id: int
    username: str
    password_hash: str
    phone: str | None
    email: str | None
    display_name: str | None
    role: str
    parent_user_id: int | None
    organization_id: int
    commission_rate: float
    commission_rate_visible: bool
    commission_amount_visible: bool
    total_income_visible: bool
    account_quota: int | None
    is_active: bool
    is_superadmin: bool
    must_change_pw: bool
    last_login_at: datetime | None
    last_login_ip: str | None
    failed_login_count: int
    locked_until: datetime | None
    created_at: datetime | None
    updated_at: datetime | None
    avatar_url: str | None
    default_auth_code: str | None = None
    deleted_at: datetime | None = None

    @property
    def level(self) -> int:
        return _role_level(self.role)


@dataclass
class SourceOrganization:
    id: int
    name: str
    org_code: str | None
    is_active: bool
    created_at: datetime | None
    updated_at: datetime | None
    notes: str | None
    org_type: str = "mcn"
    contact_name: str | None = None
    contact_phone: str | None = None
    contact_email: str | None = None
    plan_tier: str = "enterprise"
    max_accounts: int = 999999
    max_users: int = 99999
    deleted_at: datetime | None = None


@dataclass
class SourceAccount:
    id: int
    organization_id: int
    assigned_user_id: int | None
    group_id: int | None
    kuaishou_id: str | None
    real_uid: str | None
    nickname: str | None
    status: str
    mcn_status: str | None
    sign_status: str | None
    commission_rate: float
    device_serial: str | None
    remark: str | None
    created_at: datetime | None
    updated_at: datetime | None
    deleted_at: datetime | None = None


@dataclass
class SourceGroup:
    id: int
    organization_id: int | None
    owner_user_id: int | None
    name: str
    color: str | None
    created_at: datetime | None
    updated_at: datetime | None


@dataclass
class SourceKsAccount:
    id: int
    kuaishou_uid: str | None
    account_name: str | None
    device_code: str | None
    organization_id: int | None
    created_at: datetime | None


def _row_to_user(row: Any) -> SourceUser:
    quota = row["quota"]
    quota_value = None if quota in (-1, "-1", None) else int(quota)
    role = str(row["role"] or "normal_user")
    return SourceUser(
        id=int(row["id"]),
        username=str(row["username"]),
        password_hash=str(row["password_hash"]),
        phone=row["phone"],
        email=row["email"],
        display_name=row["nickname"] or row["username"],
        role=role,
        parent_user_id=row["parent_user_id"],
        organization_id=int(row["organization_access"] or 1),
        commission_rate=_rate_to_fraction(row["commission_rate"]),
        commission_rate_visible=_truthy(row["commission_rate_visible"]),
        commission_amount_visible=_truthy(row["commission_amount_visible"]),
        total_income_visible=_truthy(row["total_income_visible"]),
        account_quota=quota_value,
        is_active=_truthy(row["is_active"], True),
        is_superadmin=role == "super_admin",
        must_change_pw=False,
        last_login_at=row["last_login"],
        last_login_ip=None,
        failed_login_count=0,
        locked_until=None,
        created_at=row["created_at"],
        updated_at=row["updated_at"],
        avatar_url=row["avatar"],
        default_auth_code=row.get("default_auth_code"),
    )


def _row_to_org(row: Any) -> SourceOrganization:
    return SourceOrganization(
        id=int(row["id"]),
        name=str(row["org_name"]),
        org_code=row["org_code"],
        is_active=_truthy(row["is_active"], True),
        created_at=row["created_at"],
        updated_at=row["updated_at"],
        notes=row["description"],
    )


def _row_to_account(row: Any) -> SourceAccount:
    account_status = str(row["account_status"] or "normal")
    mcn_status = "authorized" if _truthy(row["is_mcm_member"]) else None
    remark = row["org_note"] or row["status_note"] or row["blacklist_reason"]
    return SourceAccount(
        id=int(row["id"]),
        organization_id=int(row["organization_id"] or 1),
        assigned_user_id=row["owner_id"],
        group_id=row["group_id"],
        kuaishou_id=row["uid"],
        real_uid=row["uid_real"] or row["uid"],
        nickname=row["nickname"],
        status=account_status,
        mcn_status=mcn_status,
        sign_status=row["contract_status"],
        commission_rate=_rate_to_fraction(row["commission_rate"]),
        device_serial=row["device_serial"],
        remark=remark,
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )


def _row_to_group(row: Any) -> SourceGroup:
    return SourceGroup(
        id=int(row["id"]),
        organization_id=row["organization_id"],
        owner_user_id=row["owner_id"],
        name=str(row["group_name"]),
        color=row["color"],
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )


def _row_to_ks_account(row: Any) -> SourceKsAccount:
    return SourceKsAccount(
        id=int(row["id"]),
        kuaishou_uid=row["uid_real"] or row["uid"],
        account_name=row["username"],
        device_code=row["device_num"],
        organization_id=row["organization_id"],
        created_at=None,
    )


def get_user_by_id(db: Session, user_id: int) -> SourceUser | None:
    row = db.execute(
        text(
            """
            SELECT *
            FROM admin_users
            WHERE id = :user_id
            LIMIT 1
            """
        ),
        {"user_id": user_id},
    ).mappings().first()
    return _row_to_user(row) if row else None


def create_user(db: Session, payload: dict[str, Any]) -> SourceUser:
    db.execute(
        text(
            """
            INSERT INTO admin_users
            (
                username, password_hash, password_salt, nickname, role, is_active,
                avatar, email, phone, default_auth_code, user_level, quota,
                parent_user_id, commission_rate, commission_rate_visible,
                commission_amount_visible, total_income_visible, organization_access
            )
            VALUES
            (
                :username, :password_hash, :password_salt, :nickname, :role, :is_active,
                :avatar, :email, :phone, :default_auth_code, :user_level, :quota,
                :parent_user_id, :commission_rate, :commission_rate_visible,
                :commission_amount_visible, :total_income_visible, :organization_access
            )
            """
        ),
        payload,
    )
    db.commit()
    user_id = int(db.execute(text("SELECT LAST_INSERT_ID()")).scalar_one())
    return get_user_by_id(db, user_id)


def get_user_by_login(db: Session, *, username: str | None, phone: str | None) -> SourceUser | None:
    if not username and not phone:
        return None
    if username:
        row = db.execute(
            text("SELECT * FROM admin_users WHERE username = :value LIMIT 1"),
            {"value": username},
        ).mappings().first()
    else:
        row = db.execute(
            text("SELECT * FROM admin_users WHERE phone = :value LIMIT 1"),
            {"value": phone},
        ).mappings().first()
    return _row_to_user(row) if row else None


def list_users(
    db: Session,
    *,
    viewer: SourceUser,
    page: int,
    per_page: int,
    search: str | None = None,
    role: str | None = None,
    is_active: int | None = None,
    organization_id: int | None = None,
    parent_user_id: int | None = None,
    has_parent: str | None = None,
) -> tuple[list[SourceUser], int]:
    where = ["1=1"]
    params: dict[str, Any] = {}
    if not viewer.is_superadmin:
        where.append("organization_access = :viewer_org")
        params["viewer_org"] = viewer.organization_id
    elif organization_id:
        where.append("organization_access = :org_id")
        params["org_id"] = organization_id
    if search:
        where.append("(username LIKE :search OR nickname LIKE :search OR phone LIKE :search)")
        params["search"] = f"%{search}%"
    if role:
        where.append("role = :role")
        params["role"] = role
    if is_active is not None:
        where.append("is_active = :is_active")
        params["is_active"] = int(bool(is_active))
    if parent_user_id is not None:
        where.append("parent_user_id = :parent_user_id")
        params["parent_user_id"] = parent_user_id
    if has_parent == "yes":
        where.append("parent_user_id IS NOT NULL")
    elif has_parent == "no":
        where.append("parent_user_id IS NULL")
    sql_where = " AND ".join(where)
    total = int(
        db.execute(text(f"SELECT COUNT(*) FROM admin_users WHERE {sql_where}"), params).scalar_one()
    )
    params.update({"offset": max(page - 1, 0) * per_page, "limit": per_page})
    rows = db.execute(
        text(
            f"""
            SELECT *
            FROM admin_users
            WHERE {sql_where}
            ORDER BY id ASC
            LIMIT :limit OFFSET :offset
            """
        ),
        params,
    ).mappings().all()
    return [_row_to_user(row) for row in rows], total


def list_organizations(db: Session, viewer: SourceUser) -> list[SourceOrganization]:
    params: dict[str, Any] = {}
    where = ""
    if not viewer.is_superadmin:
        where = "WHERE id = :org_id"
        params["org_id"] = viewer.organization_id
    rows = db.execute(
        text(f"SELECT * FROM mcm_organizations {where} ORDER BY id ASC"),
        params,
    ).mappings().all()
    return [_row_to_org(row) for row in rows]


def get_organization_by_id(db: Session, org_id: int) -> SourceOrganization | None:
    row = db.execute(
        text("SELECT * FROM mcm_organizations WHERE id = :org_id LIMIT 1"),
        {"org_id": org_id},
    ).mappings().first()
    return _row_to_org(row) if row else None


def create_organization(db: Session, payload: dict[str, Any]) -> SourceOrganization:
    db.execute(
        text(
            """
            INSERT INTO mcm_organizations (org_name, org_code, description, is_active)
            VALUES (:name, :org_code, :description, :is_active)
            """
        ),
        payload,
    )
    db.commit()
    org_id = int(db.execute(text("SELECT LAST_INSERT_ID()")).scalar_one())
    return get_organization_by_id(db, org_id)


def list_accounts(
    db: Session,
    *,
    viewer: SourceUser,
    page: int,
    per_page: int,
    term: str | None = None,
    organization_id: int | None = None,
    group_id: int | None = None,
    owner_id: int | None = None,
) -> tuple[list[SourceAccount], int, int]:
    where = ["1=1"]
    params: dict[str, Any] = {}
    if not viewer.is_superadmin:
        where.append("organization_id = :viewer_org")
        params["viewer_org"] = viewer.organization_id
    elif organization_id:
        where.append("organization_id = :org_id")
        params["org_id"] = organization_id
    if term:
        where.append("(uid LIKE :term OR uid_real LIKE :term OR nickname LIKE :term)")
        params["term"] = f"%{term}%"
    if group_id is not None:
        where.append("group_id = :group_id")
        params["group_id"] = group_id
    if owner_id is not None:
        where.append("owner_id = :owner_id")
        params["owner_id"] = owner_id
    sql_where = " AND ".join(where)
    total = int(db.execute(text(f"SELECT COUNT(*) FROM kuaishou_accounts WHERE {sql_where}"), params).scalar_one())
    mcn_count = int(
        db.execute(text(f"SELECT COUNT(*) FROM kuaishou_accounts WHERE {sql_where} AND is_mcm_member = 1"), params).scalar_one()
    )
    params.update({"offset": max(page - 1, 0) * per_page, "limit": per_page})
    rows = db.execute(
        text(
            f"""
            SELECT *
            FROM kuaishou_accounts
            WHERE {sql_where}
            ORDER BY id DESC
            LIMIT :limit OFFSET :offset
            """
        ),
        params,
    ).mappings().all()
    return [_row_to_account(row) for row in rows], total, mcn_count


def get_account_by_id(db: Session, account_id: int) -> SourceAccount | None:
    row = db.execute(
        text("SELECT * FROM kuaishou_accounts WHERE id = :account_id LIMIT 1"),
        {"account_id": account_id},
    ).mappings().first()
    return _row_to_account(row) if row else None


def list_groups(db: Session, viewer: SourceUser) -> tuple[list[SourceGroup], dict[int, int], int]:
    where = ""
    params: dict[str, Any] = {}
    if viewer.is_superadmin:
        join = "LEFT JOIN admin_users u ON u.id = g.owner_id"
    else:
        join = "LEFT JOIN admin_users u ON u.id = g.owner_id"
        where = "WHERE u.organization_access = :org_id"
        params["org_id"] = viewer.organization_id
    rows = db.execute(
        text(
            f"""
            SELECT g.*, u.organization_access AS organization_id
            FROM account_groups g
            {join}
            {where}
            ORDER BY g.id ASC
            """
        ),
        params,
    ).mappings().all()
    groups = [_row_to_group(row) for row in rows]
    counts_rows = db.execute(
        text(
            """
            SELECT group_id, COUNT(*) AS c
            FROM kuaishou_accounts
            WHERE (:org_id IS NULL OR organization_id = :org_id)
            GROUP BY group_id
            """
        ),
        {"org_id": None if viewer.is_superadmin else viewer.organization_id},
    ).mappings().all()
    counts = {int(row["group_id"]): int(row["c"]) for row in counts_rows if row["group_id"] is not None}
    ungrouped = int(
        db.execute(
            text(
                """
                SELECT COUNT(*)
                FROM kuaishou_accounts
                WHERE group_id IS NULL
                  AND (:org_id IS NULL OR organization_id = :org_id)
                """
            ),
            {"org_id": None if viewer.is_superadmin else viewer.organization_id},
        ).scalar_one()
    )
    return groups, counts, ungrouped


def get_group_by_id(db: Session, group_id: int) -> SourceGroup | None:
    row = db.execute(
        text(
            """
            SELECT g.*, u.organization_access AS organization_id
            FROM account_groups g
            LEFT JOIN admin_users u ON u.id = g.owner_id
            WHERE g.id = :group_id
            LIMIT 1
            """
        ),
        {"group_id": group_id},
    ).mappings().first()
    return _row_to_group(row) if row else None


def create_group(db: Session, payload: dict[str, Any]) -> SourceGroup:
    db.execute(
        text(
            """
            INSERT INTO account_groups (group_name, color, owner_id, description)
            VALUES (:group_name, :color, :owner_id, :description)
            """
        ),
        payload,
    )
    db.commit()
    group_id = int(db.execute(text("SELECT LAST_INSERT_ID()")).scalar_one())
    return get_group_by_id(db, group_id)


def list_ks_accounts(
    db: Session,
    *,
    viewer: SourceUser,
    page: int,
    per_page: int,
    keyword: str | None = None,
) -> tuple[list[SourceKsAccount], int]:
    params: dict[str, Any] = {}
    where = ["1=1"]
    if keyword:
        params["keyword"] = f"%{keyword}%"
        where.append("(username LIKE :keyword OR uid LIKE :keyword OR device_num LIKE :keyword OR uid_real LIKE :keyword)")
    if viewer.is_superadmin:
        sql_where = " AND ".join(where)
        total = int(db.execute(text(f"SELECT COUNT(*) FROM ks_account WHERE {sql_where}"), params).scalar_one())
        params.update({"offset": max(page - 1, 0) * per_page, "limit": per_page})
        rows = db.execute(
            text(
                f"""
                SELECT id, username, uid, uid_real, device_num, NULL AS organization_id
                FROM ks_account
                WHERE {sql_where}
                ORDER BY id DESC
                LIMIT :limit OFFSET :offset
                """
            ),
            params,
        ).mappings().all()
    else:
        params["org_id"] = viewer.organization_id
        sql_where = " AND ".join(where)
        total = int(
            db.execute(
                text(
                    f"""
                    SELECT COUNT(*)
                    FROM ks_account
                    WHERE {sql_where}
                      AND (
                        uid_real IN (SELECT uid_real FROM kuaishou_accounts WHERE organization_id = :org_id AND uid_real IS NOT NULL)
                        OR uid IN (SELECT uid FROM kuaishou_accounts WHERE organization_id = :org_id)
                      )
                    """
                ),
                params,
            ).scalar_one()
        )
        params.update({"offset": max(page - 1, 0) * per_page, "limit": per_page})
        rows = db.execute(
            text(
                f"""
                SELECT ks.id, ks.username, ks.uid, ks.uid_real, ks.device_num, :org_id AS organization_id
                FROM ks_account ks
                WHERE {sql_where}
                  AND (
                    ks.uid_real IN (SELECT uid_real FROM kuaishou_accounts WHERE organization_id = :org_id AND uid_real IS NOT NULL)
                    OR ks.uid IN (SELECT uid FROM kuaishou_accounts WHERE organization_id = :org_id)
                  )
                ORDER BY ks.id DESC
                LIMIT :limit OFFSET :offset
                """
            ),
            params,
        ).mappings().all()
    return [_row_to_ks_account(row) for row in rows], total


def update_user_fields(db: Session, user_id: int, fields: dict[str, Any]) -> SourceUser | None:
    if not fields:
        return get_user_by_id(db, user_id)
    set_sql = ", ".join(f"{key} = :{key}" for key in fields)
    params = dict(fields)
    params["user_id"] = user_id
    db.execute(text(f"UPDATE admin_users SET {set_sql} WHERE id = :user_id"), params)
    db.commit()
    return get_user_by_id(db, user_id)


def batch_update_users(db: Session, user_ids: list[int], fields: dict[str, Any]) -> int:
    if not user_ids:
        return 0
    set_sql = ", ".join(f"{key} = :{key}" for key in fields)
    params = dict(fields)
    placeholders = ", ".join(str(int(item)) for item in user_ids)
    db.execute(text(f"UPDATE admin_users SET {set_sql} WHERE id IN ({placeholders})"), params)
    db.commit()
    return len(user_ids)


def update_organization_fields(db: Session, org_id: int, fields: dict[str, Any]) -> SourceOrganization | None:
    if not fields:
        return get_organization_by_id(db, org_id)
    set_sql = ", ".join(f"{key} = :{key}" for key in fields)
    params = dict(fields)
    params["org_id"] = org_id
    db.execute(text(f"UPDATE mcm_organizations SET {set_sql} WHERE id = :org_id"), params)
    db.commit()
    return get_organization_by_id(db, org_id)


def create_account(db: Session, payload: dict[str, Any]) -> SourceAccount:
    db.execute(
        text(
            """
            INSERT INTO kuaishou_accounts
            (
                uid, uid_real, device_serial, nickname, is_mcm_member, created_at, updated_at,
                group_id, owner_id, account_status, status_note, contract_status, org_note,
                organization_id, commission_rate
            )
            VALUES
            (
                :uid, :uid_real, :device_serial, :nickname, :is_mcm_member, NOW(), NOW(),
                :group_id, :owner_id, :account_status, :status_note, :contract_status, :org_note,
                :organization_id, :commission_rate
            )
            """
        ),
        payload,
    )
    db.commit()
    account_id = int(db.execute(text("SELECT LAST_INSERT_ID()")).scalar_one())
    return get_account_by_id(db, account_id)


def update_account_fields(db: Session, account_id: int, fields: dict[str, Any]) -> SourceAccount | None:
    if not fields:
        return get_account_by_id(db, account_id)
    set_sql = ", ".join(f"{key} = :{key}" for key in fields)
    params = dict(fields)
    params["account_id"] = account_id
    db.execute(text(f"UPDATE kuaishou_accounts SET {set_sql} WHERE id = :account_id"), params)
    db.commit()
    return get_account_by_id(db, account_id)


def batch_update_accounts_by_ids(db: Session, account_ids: list[int], fields: dict[str, Any]) -> int:
    if not account_ids:
        return 0
    set_sql = ", ".join(f"{key} = :{key}" for key in fields)
    params = dict(fields)
    placeholders = ", ".join(str(int(item)) for item in account_ids)
    db.execute(text(f"UPDATE kuaishou_accounts SET {set_sql} WHERE id IN ({placeholders})"), params)
    db.commit()
    return len(account_ids)


def batch_update_accounts(db: Session, identifiers: list[Any], fields: dict[str, Any]) -> int:
    if not identifiers:
        return 0
    set_sql = ", ".join(f"{key} = :{key}" for key in fields)
    params = dict(fields)
    numeric_ids = [int(item) for item in identifiers if str(item).isdigit()]
    string_ids = [str(item) for item in identifiers if item is not None and not str(item).isdigit()]
    where_parts: list[str] = []
    updated = 0
    if numeric_ids:
        where_parts.append(f"id IN ({', '.join(str(item) for item in numeric_ids)})")
    if string_ids:
        quoted = ", ".join("'" + item.replace("'", "''") + "'" for item in string_ids)
        where_parts.append(f"uid IN ({quoted})")
        where_parts.append(f"uid_real IN ({quoted})")
    if not where_parts:
        return 0
    updated = int(
        db.execute(
            text(f"SELECT COUNT(*) FROM kuaishou_accounts WHERE {' OR '.join(where_parts)}"),
            {},
        ).scalar_one()
    )
    db.execute(text(f"UPDATE kuaishou_accounts SET {set_sql} WHERE {' OR '.join(where_parts)}"), params)
    db.commit()
    return updated


def create_or_update_account_by_uid(db: Session, uid: str, fields: dict[str, Any]) -> str:
    existing = db.execute(
        text("SELECT id FROM kuaishou_accounts WHERE uid = :uid OR uid_real = :uid LIMIT 1"),
        {"uid": uid},
    ).mappings().first()
    if existing:
        update_account_fields(db, int(existing["id"]), fields)
        return "updated"
    create_account(
        db,
        {
            "uid": fields.get("uid", uid),
            "uid_real": fields.get("uid_real", uid),
            "device_serial": fields.get("device_serial"),
            "nickname": fields.get("nickname"),
            "is_mcm_member": fields.get("is_mcm_member", 0),
            "group_id": fields.get("group_id"),
            "owner_id": fields.get("owner_id"),
            "account_status": fields.get("account_status", "normal"),
            "status_note": fields.get("status_note"),
            "contract_status": fields.get("contract_status"),
            "org_note": fields.get("org_note"),
            "organization_id": fields.get("organization_id", 1),
            "commission_rate": fields.get("commission_rate"),
        },
    )
    return "created"


def update_group_fields(db: Session, group_id: int, fields: dict[str, Any]) -> SourceGroup | None:
    if not fields:
        return get_group_by_id(db, group_id)
    set_sql = ", ".join(f"{key} = :{key}" for key in fields)
    params = dict(fields)
    params["group_id"] = group_id
    db.execute(text(f"UPDATE account_groups SET {set_sql} WHERE id = :group_id"), params)
    db.commit()
    return get_group_by_id(db, group_id)


def delete_group(db: Session, group_id: int) -> None:
    db.execute(text("UPDATE kuaishou_accounts SET group_id = NULL WHERE group_id = :group_id"), {"group_id": group_id})
    db.execute(text("DELETE FROM account_groups WHERE id = :group_id"), {"group_id": group_id})
    db.commit()


def assign_accounts_to_group(db: Session, group_id: int | None, ids: list[Any]) -> int:
    if not ids:
        return 0
    numeric_ids = [int(item) for item in ids if str(item).isdigit()]
    string_ids = [str(item) for item in ids if not str(item).isdigit()]
    updated = 0
    if numeric_ids:
        placeholders = ", ".join(str(item) for item in numeric_ids)
        db.execute(text(f"UPDATE kuaishou_accounts SET group_id = :group_id WHERE id IN ({placeholders})"), {"group_id": group_id})
        updated += len(numeric_ids)
    if string_ids:
        quoted = ", ".join("'" + item.replace("'", "''") + "'" for item in string_ids)
        db.execute(text(f"UPDATE kuaishou_accounts SET group_id = :group_id WHERE uid IN ({quoted}) OR uid_real IN ({quoted})"), {"group_id": group_id})
        updated += len(string_ids)
    db.commit()
    return updated
