"""Compatibility API for the demo admin frontend.

The live demo frontend is a Vue admin bundle that talks to `/api/*` and expects
responses shaped as `{ success, data, message }`.  Our maintained client API
lives under `/api/client/*` and uses `{ ok, data, meta }`.  This router lets us
serve the demo UI unchanged while still reading/writing our own database.
"""
from __future__ import annotations

from datetime import date, datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

from fastapi import APIRouter, Depends, File, Request, UploadFile
from pydantic import BaseModel
from sqlalchemy import String, func, or_, select
from sqlalchemy.orm import Session

from app.core.deps import CurrentUser, DbSession
from app.core.security import hash_password, verify_password
from app.models import (
    Account,
    AccountGroup,
    AccountTaskRecord,
    Announcement,
    CloudCookieAccount,
    CollectPoolAuthCode,
    CollectPool,
    CxtUser,
    CxtVideo,
    DefaultRolePermission,
    DramaCollectionRecord,
    DramaLinkStatistic,
    ExternalUrlStat,
    FireflyIncome,
    FireflyMember,
    FluorescentIncome,
    HighIncomeDrama,
    IncomeArchive,
    KsAccount,
    KuaishouAccountBinding,
    OperationLog,
    OrgMember,
    Organization,
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
from app.services import auth_service, statistics_service


router = APIRouter()


class CompatLoginRequest(BaseModel):
    username: str | None = None
    phone: str | None = None
    password: str
    fingerprint: str | None = None


class PermissionUpdateRequest(BaseModel):
    permissions: list[dict[str, Any]] = []


class CheckPermissionRequest(BaseModel):
    permission: str


USER_MANAGEMENT_BUTTONS = [
    {"key": "user:create", "name": "创建用户", "category": "user", "description": "创建后台用户"},
    {"key": "user:edit", "name": "编辑", "category": "user", "description": "编辑用户资料"},
    {"key": "user:delete", "name": "删除", "category": "user", "description": "删除用户"},
    {"key": "user:reset_password", "name": "重置密码", "category": "user", "description": "重置用户密码"},
    {"key": "user:toggle_status", "name": "启用/禁用", "category": "user", "description": "切换用户状态"},
    {"key": "user:button_permissions", "name": "按钮权限", "category": "permission", "description": "设置用户管理按钮"},
    {"key": "user:web_page_permissions", "name": "Web页面权限", "category": "permission", "description": "设置后台页面权限"},
    {"key": "user:client_page_permissions", "name": "客户端页面权限", "category": "permission", "description": "设置客户端页面权限"},
    {"key": "user:change_role", "name": "修改角色", "category": "user", "description": "修改上下级角色"},
    {"key": "user:set_organization", "name": "设置机构", "category": "organization", "description": "设置机构归属"},
    {"key": "user:alipay", "name": "支付宝信息", "category": "finance", "description": "维护支付宝信息"},
    {"key": "user:commission", "name": "编辑分成", "category": "finance", "description": "维护分成比例"},
    {"key": "user:commission_visibility", "name": "分成可见", "category": "finance", "description": "维护收益可见范围"},
    {"key": "user:auth_code", "name": "授权码", "category": "external", "description": "维护默认授权码"},
]


PAGE_PERMISSION_KEYS = [
    "dashboard", "statistics", "accounts", "ks-accounts", "org-members",
    "account-violation", "users", "wallet-info", "firefly-members",
    "firefly-income", "fluorescent-income", "spark-members", "spark-archive",
    "spark-income", "collect-pool", "high-income-dramas", "drama-statistics",
    "drama-collections", "external-url-stats", "cxt-user", "cxt-videos",
    "settings", "cloud-cookies", "member-query",
]


def _success(data: Any = None, message: str = "操作成功", **extra: Any) -> dict[str, Any]:
    payload = {"success": True, "message": message, "data": data}
    payload.update(extra)
    return payload


def _dt(value: datetime | date | None) -> str | None:
    if value is None:
        return None
    return value.isoformat()


def _page_size(page: int = 1, page_size: int | None = None, size: int | None = None):
    per_page = page_size or size or 20
    return max(page, 1), max(min(per_page, 500), 1)


def _count(db: Session, stmt) -> int:
    return int(db.execute(select(func.count()).select_from(stmt.subquery())).scalar_one())


def _permission_group(code: str) -> str:
    if code.startswith("page:"):
        code = code[5:]
    if code.startswith("account"):
        return "账号管理"
    if code.startswith("spark"):
        return "星火计划"
    if code.startswith("firefly") or code.startswith("fluorescent"):
        return "萤光计划"
    if code.startswith("collect") or code.startswith("drama") or code.startswith("high-income"):
        return "短剧管理"
    if code.startswith("cxt") or code.startswith("external"):
        return "外部项目"
    if code.startswith("user") or code.startswith("settings") or code.startswith("cloud"):
        return "系统管理"
    return "基础功能"


def _permission_payload(code: str, granted: int = 1) -> dict[str, Any]:
    return {
        "key": code,
        "button_key": code,
        "page_key": code,
        "name": code,
        "label": code,
        "group": _permission_group(code),
        "is_allowed": 1 if granted else 0,
    }


def _role_value(user: User) -> str:
    return "super_admin" if user.is_superadmin else user.role


def _catalog_codes(
    db: Session,
    *,
    permission_type: str | None = None,
    model: type[UserButtonPermission] | type[UserPagePermission] | None = None,
    prefix: str | None = None,
) -> list[str]:
    codes: set[str] = set()
    if permission_type:
        rows = db.execute(
            select(DefaultRolePermission.permission_code)
            .where(DefaultRolePermission.permission_type == permission_type)
            .distinct()
        ).scalars().all()
        codes.update(code for code in rows if code)
    if model:
        rows = db.execute(select(model.permission_code).distinct()).scalars().all()
        for code in rows:
            if not code:
                continue
            if prefix is None or code.startswith(prefix):
                codes.add(code)
    return sorted(codes)


def _effective_permissions(
    db: Session,
    target: User,
    codes: list[str],
    model: type[UserButtonPermission] | type[UserPagePermission],
    permission_type: str | None = None,
) -> list[dict[str, Any]]:
    if target.is_superadmin:
        return [_permission_payload(code, 1) for code in codes]
    explicit = dict(
        db.execute(
            select(model.permission_code, model.granted).where(
                model.user_id == target.id,
                model.permission_code.in_(codes),
            )
        ).all()
    )
    defaults: dict[str, int] = {}
    if permission_type:
        defaults = dict(
            db.execute(
                select(DefaultRolePermission.permission_code, DefaultRolePermission.granted).where(
                    DefaultRolePermission.role == _role_value(target),
                    DefaultRolePermission.permission_type == permission_type,
                    DefaultRolePermission.permission_code.in_(codes),
                )
            ).all()
        )
    return [_permission_payload(code, explicit.get(code, defaults.get(code, 0))) for code in codes]


def _upsert_permissions(
    db: Session,
    user_id: int,
    permissions: list[dict[str, Any]],
    model: type[UserButtonPermission] | type[UserPagePermission],
) -> None:
    for item in permissions:
        code = item.get("button_key") or item.get("page_key") or item.get("key")
        code = str(code).strip() if code is not None else ""
        if not code:
            continue
        granted = 1 if item.get("is_allowed") in (True, 1, "1", "true", "True") else 0
        existing = db.execute(
            select(model).where(model.user_id == user_id, model.permission_code == code)
        ).scalar_one_or_none()
        if existing is None:
            db.add(model(user_id=user_id, permission_code=code, granted=granted))
        else:
            existing.granted = granted
    db.commit()


def _user_payload(user: User) -> dict[str, Any]:
    role = _role_value(user)
    rate = user.commission_rate or 0
    display_rate = rate * 100 if rate <= 1 else rate
    return {
        "id": user.id,
        "username": user.username,
        "nickname": user.display_name or user.username,
        "name": user.display_name or user.username,
        "phone": user.phone,
        "email": user.email,
        "role": role,
        "user_role": role,
        "parent_user_id": user.parent_user_id,
        "organization_id": user.organization_id,
        "organization_access": user.organization_id,
        "is_superadmin": 1 if user.is_superadmin else 0,
        "is_super_admin": 1 if user.is_superadmin else 0,
        "is_active": 1 if user.is_active else 0,
        "last_login": _dt(user.last_login_at),
        "login_count": 0,
        "user_level": "enterprise" if user.account_quota is None else "normal",
        "quota": -1 if user.account_quota is None else user.account_quota,
        "cooperation_type": "cooperative",
        "is_oem": 0,
        "oem_name": None,
        "commission_rate": f"{display_rate:.2f}",
        "commission_rate_visible": 1 if user.commission_rate_visible else 0,
        "commission_amount_visible": 1 if user.commission_amount_visible else 0,
        "total_income_visible": 1 if user.total_income_visible else 0,
        "alipay_info": None,
        "created_at": _dt(user.created_at),
    }


def _organization_payload(org: Organization) -> dict[str, Any]:
    return {
        "id": org.id,
        "name": org.name,
        "org_name": org.name,
        "organization_name": org.name,
        "org_code": org.org_code,
        "code": org.org_code,
        "status": 1 if org.is_active else 0,
        "is_active": 1 if org.is_active else 0,
        "created_at": _dt(org.created_at),
    }


def _account_payload(account: Account) -> dict[str, Any]:
    uid = account.kuaishou_id or account.real_uid or str(account.id)
    rate = account.commission_rate or 0
    display_rate = rate * 100 if rate <= 1 else rate
    is_mcn = account.mcn_status in {"authorized", "signed", "success", "active", "1"}
    return {
        "id": account.id,
        "uid": uid,
        "kuaishou_id": account.kuaishou_id,
        "uid_real": account.real_uid,
        "real_uid": account.real_uid,
        "nickname": account.nickname or "",
        "device_serial": account.device_serial or "",
        "organization_id": account.organization_id,
        "owner_id": account.assigned_user_id,
        "user_id": account.assigned_user_id,
        "group_id": account.group_id,
        "status": account.status,
        "account_status": account.status,
        "is_mcm_member": 1 if is_mcn else 0,
        "mcn_status": account.mcn_status,
        "contract_status": account.sign_status or account.mcn_status or "",
        "sign_status": account.sign_status or "",
        "account_commission_rate": display_rate,
        "user_commission_rate": display_rate,
        "commission_rate": display_rate,
        "remark": account.remark or "",
        "created_at": _dt(account.created_at),
        "updated_at": _dt(account.updated_at),
    }


def _group_payload(group: AccountGroup, account_count: int = 0) -> dict[str, Any]:
    return {
        "id": group.id,
        "group_name": group.name,
        "name": group.name,
        "organization_id": group.organization_id,
        "owner_id": group.owner_user_id,
        "owner_user_id": group.owner_user_id,
        "color": group.color,
        "sort_order": group.id,
        "account_count": account_count,
        "created_at": _dt(group.created_at),
    }


def _member_payload(member: SparkMember | FireflyMember) -> dict[str, Any]:
    base = {
        "id": member.id,
        "member_id": str(member.member_id),
        "uid": str(member.member_id),
        "nickname": member.nickname or "",
        "member_name": member.nickname or "",
        "fans_count": member.fans_count,
        "broker_name": member.broker_name or "",
        "organization_id": member.organization_id,
        "account_id": member.account_id,
        "hidden": int(bool(getattr(member, "hidden", False))),
        "created_at": _dt(member.created_at),
        "updated_at": _dt(member.updated_at),
    }
    if isinstance(member, SparkMember):
        base.update(
            {
                "task_count": member.task_count,
                "total_amount": 0,
                "income": 0,
                "first_release_id": member.first_release_id,
            }
        )
    else:
        base.update(
            {
                "total_amount": member.total_amount,
                "income": member.total_amount,
                "org_task_num": member.org_task_num,
            }
        )
    return base


def _income_payload(row: SparkIncome | FireflyIncome | FluorescentIncome | IncomeArchive) -> dict[str, Any]:
    amount = getattr(row, "income_amount", None)
    if amount is None:
        amount = getattr(row, "total_amount", 0)
    return {
        "id": row.id,
        "organization_id": row.organization_id,
        "member_id": str(row.member_id),
        "account_id": row.account_id,
        "task_id": getattr(row, "task_id", None),
        "task_name": getattr(row, "task_name", None) or "",
        "income": amount,
        "income_amount": amount,
        "total_amount": getattr(row, "total_amount", amount),
        "commission_rate": getattr(row, "commission_rate", None),
        "commission_amount": getattr(row, "commission_amount", None),
        "settlement_status": getattr(row, "settlement_status", "pending"),
        "income_date": _dt(getattr(row, "income_date", None) or getattr(row, "start_date", None)),
        "start_date": _dt(getattr(row, "start_date", None)),
        "end_date": _dt(getattr(row, "end_date", None)),
        "archive_year": getattr(row, "year", None),
        "archive_month": getattr(row, "month", None),
        "archived_at": _dt(getattr(row, "archived_at", None)),
        "created_at": _dt(row.created_at),
    }


def _ks_account_payload(row: KsAccount) -> dict[str, Any]:
    return {
        "id": row.id,
        "uid": row.kuaishou_uid,
        "kuaishou_uid": row.kuaishou_uid,
        "username": row.account_name or row.kuaishou_uid,
        "account_name": row.account_name,
        "device_code": row.device_code,
        "organization_id": row.organization_id,
        "created_at": _dt(row.created_at),
    }


def _org_member_payload(row: OrgMember) -> dict[str, Any]:
    return {
        "id": row.id,
        "member_id": str(row.member_id),
        "uid": str(row.member_id),
        "nickname": row.nickname or "",
        "member_name": row.nickname or "",
        "avatar": row.avatar,
        "fans_count": row.fans_count,
        "broker_name": row.broker_name or "",
        "cooperation_type": row.cooperation_type or "",
        "content_category": row.content_category or "",
        "mcn_level": row.mcn_level or "",
        "contract_renew_status": row.renewal_status or "",
        "renewal_status": row.renewal_status or "",
        "agreement_type": row.cooperation_type or "",
        "organization_id": row.organization_id,
        "account_id": row.account_id,
        "contract_expires_at": _dt(row.contract_expires_at),
        "created_at": _dt(row.created_at),
    }


def _violation_payload(row: ViolationPhoto) -> dict[str, Any]:
    return {
        "id": row.id,
        "work_id": row.work_id,
        "photo_id": row.work_id,
        "uid": row.uid,
        "thumbnail": row.thumbnail,
        "cover_url": row.thumbnail,
        "description": row.description or "",
        "caption": row.description or "",
        "business_type": row.business_type,
        "sub_biz": row.business_type,
        "violation_reason": row.violation_reason or "",
        "view_count": row.view_count,
        "like_count": row.like_count,
        "appeal_status": row.appeal_status,
        "appeal_reason": row.appeal_reason,
        "organization_id": row.organization_id,
        "published_at": _dt(row.published_at),
        "detected_at": _dt(row.detected_at),
        "created_at": _dt(row.created_at),
    }


def _collect_pool_payload(row: CollectPool) -> dict[str, Any]:
    return {
        "id": row.id,
        "name": row.drama_name,
        "drama_name": row.drama_name,
        "url": row.drama_url,
        "drama_url": row.drama_url,
        "platform": row.platform,
        "auth_code": row.auth_code,
        "username": row.auth_code,
        "status": row.status,
        "abnormal_reason": row.abnormal_reason,
        "organization_id": row.organization_id,
        "created_at": _dt(row.created_at),
    }


def _high_income_payload(row: HighIncomeDrama) -> dict[str, Any]:
    return {
        "id": row.id,
        "task_name": row.drama_name,
        "drama_name": row.drama_name,
        "source_program": row.source_program,
        "income": row.income_amount,
        "income_amount": row.income_amount,
        "notes": row.notes,
        "organization_id": row.organization_id,
        "created_at": _dt(row.created_at),
    }


def _drama_link_payload(row: DramaLinkStatistic) -> dict[str, Any]:
    return {
        "id": row.id,
        "drama_name": row.drama_name,
        "drama_link": row.drama_url,
        "drama_url": row.drama_url,
        "total_count": row.execute_count,
        "execute_count": row.execute_count,
        "success_count": row.success_count,
        "failed_count": row.failed_count,
        "account_count": row.account_count,
        "success_rate": round(row.success_rate * 100, 2),
        "organization_id": row.organization_id,
        "last_executed_at": _dt(row.last_executed_at),
        "created_at": _dt(row.created_at),
    }


def _drama_collection_payload(row: DramaCollectionRecord) -> dict[str, Any]:
    return {
        "id": row.id,
        "uid": row.account_uid,
        "account_uid": row.account_uid,
        "nickname": row.account_name,
        "account_name": row.account_name,
        "total_count": row.total_count,
        "spark_count": row.spark_count,
        "firefly_count": row.firefly_count,
        "fluorescent_count": row.fluorescent_count,
        "organization_id": row.organization_id,
        "last_collected_at": _dt(row.last_collected_at),
        "created_at": _dt(row.created_at),
    }


def _external_url_payload(row: ExternalUrlStat) -> dict[str, Any]:
    return {
        "id": row.id,
        "url": row.url,
        "external_url": row.url,
        "drama_url": row.url,
        "source_platform": row.source_platform,
        "url_count": row.reference_count,
        "reference_count": row.reference_count,
        "organization_id": row.organization_id,
        "last_seen_at": _dt(row.last_seen_at),
        "created_at": _dt(row.created_at),
    }


def _auth_code_payload(row: CollectPoolAuthCode) -> dict[str, Any]:
    return {
        "id": row.id,
        "auth_code": row.auth_code,
        "name": row.name or row.auth_code,
        "is_active": 1 if row.is_active else 0,
        "expire_at": _dt(row.expire_at),
        "created_by": row.created_by_user_id,
        "created_at": _dt(row.created_at),
        "updated_at": _dt(row.updated_at),
    }


def _binding_payload(row: KuaishouAccountBinding) -> dict[str, Any]:
    return {
        "id": row.id,
        "source_id": row.source_id,
        "account_id": row.account_id,
        "user_id": row.user_id,
        "kuaishou_id": row.kuaishou_id,
        "uid": row.kuaishou_id,
        "machine_id": row.machine_id,
        "operator_account": row.operator_account,
        "operator": row.operator_account,
        "status": row.status,
        "remark": row.remark,
        "bind_time": _dt(row.bind_time),
        "last_used_time": _dt(row.last_used_time),
        "created_at": _dt(row.created_at),
        "updated_at": _dt(row.updated_at),
    }


def _spark_photo_payload(row: SparkPhoto) -> dict[str, Any]:
    return {
        "id": row.id,
        "source_id": row.source_id,
        "photo_id": row.photo_id,
        "work_id": row.photo_id,
        "member_id": str(row.member_id) if row.member_id is not None else None,
        "uid": str(row.member_id) if row.member_id is not None else None,
        "member_name": row.member_name,
        "nickname": row.member_name,
        "title": row.title,
        "description": row.title,
        "view_count": row.view_count,
        "like_count": row.like_count,
        "comment_count": row.comment_count,
        "duration": row.duration,
        "publish_time": row.publish_time,
        "publish_date": _dt(row.publish_date),
        "cover_url": row.cover_url,
        "thumbnail": row.cover_url,
        "play_url": row.play_url,
        "avatar_url": row.avatar_url,
        "organization_id": row.organization_id,
        "account_id": row.account_id,
        "created_at": _dt(row.created_at),
        "updated_at": _dt(row.updated_at),
    }


def _violation_drama_payload(row: SparkViolationDrama) -> dict[str, Any]:
    return {
        "id": row.id,
        "source_id": row.source_id,
        "drama_title": row.drama_title,
        "title": row.drama_title,
        "drama_name": row.drama_title,
        "source_photo_id": row.source_photo_id,
        "source_caption": row.source_caption,
        "user_id": row.user_id,
        "uid": str(row.user_id) if row.user_id is not None else None,
        "username": row.username,
        "violation_count": row.violation_count,
        "last_violation_time": row.last_violation_time,
        "last_violation_date": _dt(row.last_violation_date),
        "sub_biz": row.sub_biz,
        "status_desc": row.status_desc,
        "reason": row.reason,
        "media_url": row.media_url,
        "thumb_url": row.thumb_url,
        "thumbnail": row.thumb_url,
        "broker_name": row.broker_name,
        "is_blacklisted": 1 if row.is_blacklisted else 0,
        "blacklisted_at": _dt(row.blacklisted_at),
        "organization_id": row.organization_id,
        "created_at": _dt(row.created_at),
        "updated_at": _dt(row.updated_at),
    }


def _announcement_payload(row: Announcement) -> dict[str, Any]:
    priority = 2 if row.level == "urgent" else 1 if row.pinned or row.level == "warning" else 0
    return {
        "id": row.id,
        "title": row.title,
        "content": row.content,
        "level": row.level,
        "priority": priority,
        "pinned": 1 if row.pinned else 0,
        "active": 1 if row.active else 0,
        "is_enabled": 1 if row.active else 0,
        "platform": "web",
        "link_url": None,
        "link_text": None,
        "target_roles": None,
        "target_users": None,
        "attachments": None,
        "organization_id": row.organization_id,
        "start_at": _dt(row.start_at),
        "end_at": _dt(row.end_at),
        "created_by": row.created_by_user_id,
        "created_at": _dt(row.created_at),
        "updated_at": _dt(row.updated_at),
    }


def _apply_org_scope(stmt, model, user: User):
    if user.is_superadmin or user.role == "super_admin":
        return stmt
    if hasattr(model, "organization_id"):
        return stmt.where(model.organization_id == user.organization_id)
    return stmt


def _body_ids(body: dict[str, Any]) -> list[Any]:
    values = (
        body.get("ids")
        or body.get("uids")
        or body.get("account_ids")
        or body.get("accountIds")
        or body.get("selected_ids")
        or []
    )
    if isinstance(values, (str, int)):
        return [values]
    return list(values)


def _as_bool(value: Any, default: bool = False) -> bool:
    if value is None:
        return default
    if isinstance(value, str):
        return value.lower() in {"1", "true", "yes", "on", "active", "enabled"}
    return bool(value)


def _as_int(value: Any, default: int = 0) -> int:
    try:
        if value in (None, ""):
            return default
        return int(value)
    except (TypeError, ValueError):
        return default


def _as_float(value: Any, default: float = 0.0) -> float:
    try:
        if value in (None, ""):
            return default
        return float(value)
    except (TypeError, ValueError):
        return default


def _as_date(value: Any) -> date | None:
    if isinstance(value, date) and not isinstance(value, datetime):
        return value
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, str) and value:
        try:
            return datetime.fromisoformat(value.replace("Z", "+00:00")).date()
        except ValueError:
            return None
    return None


def _as_datetime(value: Any) -> datetime | None:
    if isinstance(value, datetime):
        return value
    if isinstance(value, date):
        return datetime.combine(value, datetime.min.time())
    if isinstance(value, str) and value:
        try:
            return datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return None
    return None


def _account_stmt_for_ids(ids: list[Any]):
    text_ids = [str(item) for item in ids if item is not None]
    int_ids = [int(item) for item in text_ids if str(item).isdigit()]
    stmt = select(Account).where(Account.deleted_at.is_(None))
    if not text_ids and not int_ids:
        return stmt.where(False)
    filters = []
    if int_ids:
        filters.append(Account.id.in_(int_ids))
    if text_ids:
        filters.extend([Account.kuaishou_id.in_(text_ids), Account.real_uid.in_(text_ids)])
    return stmt.where(or_(*filters))


@router.get("/health")
async def health():
    return _success({"status": "ok"})


@router.get("/statistics/overview")
async def statistics_overview(db: DbSession, user: CurrentUser):
    data = statistics_service.overview(db, user)
    trend = data.get("trend_7d") or []
    return _success(
        {
            "accounts": {
                "total": data.get("total_accounts", 0),
                "mcn_members": data.get("mcn_accounts", 0),
            },
            "executions": {
                "total": data.get("total_executions", 0),
                "today": data.get("today_executions", 0),
                "success": data.get("today_success", 0),
                "failed": data.get("today_fail", 0),
            },
            "trend": {
                "labels": [row.get("date") for row in trend],
                "values": [row.get("count", 0) for row in trend],
            },
            "showSystemStatus": True,
        }
    )


@router.get("/statistics/drama")
async def statistics_drama(db: DbSession, user: CurrentUser, days: int = 30):
    stmt = select(AccountTaskRecord)
    stmt = _apply_org_scope(stmt, AccountTaskRecord, user)
    total = _count(db, stmt)
    success_stmt = select(AccountTaskRecord).where(AccountTaskRecord.success.is_(True))
    success_stmt = _apply_org_scope(success_stmt, AccountTaskRecord, user)
    success = _count(db, success_stmt)
    failed = max(total - success, 0)
    return _success(
        {
            "summary": {
                "total_count": total,
                "success_count": success,
                "failed_count": failed,
                "success_rate": round(success / total * 100, 2) if total else 0,
                "days": days,
            },
            "daily_stats": [],
        }
    )


@router.post("/auth/login")
async def login(req: CompatLoginRequest, request: Request, db: DbSession):
    user, access, _refresh, _refresh_exp = auth_service.login(
        db,
        username=req.username,
        phone=req.phone,
        password=req.password,
        fingerprint=req.fingerprint,
        user_agent=request.headers.get("user-agent"),
        ip=request.client.host if request.client else None,
    )
    return _success({"token": access, "user": _user_payload(user)}, message="登录成功")


@router.post("/auth/logout")
async def logout():
    return _success({"logged_out": True})


@router.get("/auth/me")
async def current_user(user: CurrentUser):
    return _success(_user_payload(user))


@router.get("/auth/profile")
async def profile(user: CurrentUser):
    return _success(_user_payload(user))


@router.get("/auth/my-alipay")
async def my_alipay(db: DbSession, user: CurrentUser):
    row = db.execute(
        select(WalletProfile).where(WalletProfile.user_id == user.id)
    ).scalar_one_or_none()
    if row is None:
        return _success(
            {
                "alipay_name": "",
                "alipay_account": "",
                "bank_name": "",
                "bank_account": "",
                "real_name": user.display_name or "",
                "notes": "",
            }
        )
    return _success(
        {
            "alipay_name": row.alipay_name,
            "alipay_account": row.alipay_account,
            "bank_name": row.bank_name,
            "bank_account": row.bank_account,
            "real_name": row.real_name,
            "notes": row.notes,
        }
    )


@router.get("/auth/users")
async def users(
    db: DbSession,
    user: CurrentUser,
    page: int = 1,
    pageSize: int | None = None,
    page_size: int | None = None,
    size: int | None = None,
    search: str | None = None,
    role: str | None = None,
    is_active: int | None = None,
    organization_id: int | None = None,
    parent_user_id: int | None = None,
    has_parent: str | None = None,
    cooperation_type: str | None = None,
    include_all: int | None = None,
):
    stmt = select(User).where(User.deleted_at.is_(None)).order_by(User.id.asc())
    if not user.is_superadmin:
        stmt = stmt.where(User.organization_id == user.organization_id)
    if search:
        like = f"%{search}%"
        stmt = stmt.where(or_(User.username.like(like), User.display_name.like(like), User.phone.like(like)))
    if role:
        if role == "super_admin":
            stmt = stmt.where(User.is_superadmin.is_(True))
        else:
            stmt = stmt.where(User.role == role, User.is_superadmin.is_(False))
    if is_active is not None:
        stmt = stmt.where(User.is_active.is_(bool(is_active)))
    if organization_id and user.is_superadmin:
        stmt = stmt.where(User.organization_id == organization_id)
    if parent_user_id is not None:
        stmt = stmt.where(User.parent_user_id == parent_user_id)
    if has_parent == "yes":
        stmt = stmt.where(User.parent_user_id.is_not(None))
    elif has_parent == "no":
        stmt = stmt.where(User.parent_user_id.is_(None))
    if cooperation_type and cooperation_type != "cooperative":
        stmt = stmt.where(False)
    total = _count(db, stmt)
    explicit_page_size = pageSize or page_size or size
    if explicit_page_size is None or include_all:
        per_page = max(total, 1)
    else:
        page, per_page = _page_size(page, pageSize or page_size, size)
    rows = db.execute(stmt.offset((page - 1) * per_page).limit(per_page)).scalars().all()
    data = [_user_payload(row) for row in rows]
    return _success(data, total=total, pagination={"total": total, "page": page, "page_size": per_page})


@router.post("/auth/users")
async def create_user(request: Request, db: DbSession, user: CurrentUser):
    body = await request.json()
    username = str(body.get("username") or body.get("phone") or "").strip()
    if not username:
        return _success(None, message="用户名不能为空")
    role = body.get("role") or "normal_user"
    password = body.get("password") or body.get("initial_password") or "123456"
    new_user = User(
        organization_id=int(body.get("organization_id") or body.get("organization_access") or user.organization_id),
        username=username,
        password_hash=hash_password(str(password)),
        phone=body.get("phone"),
        email=body.get("email"),
        display_name=body.get("nickname") or body.get("display_name") or username,
        role=role,
        level={"super_admin": 100, "operator": 50, "captain": 30}.get(role, 10),
        parent_user_id=body.get("parent_user_id"),
        commission_rate=float(body.get("commission_rate") or 100) / 100,
        commission_rate_visible=bool(body.get("commission_rate_visible", 0)),
        commission_amount_visible=bool(body.get("commission_amount_visible", 0)),
        total_income_visible=bool(body.get("total_income_visible", 0)),
        account_quota=None if int(body.get("quota", -1) or -1) == -1 else int(body.get("quota")),
        is_active=bool(body.get("is_active", 1)),
        is_superadmin=role == "super_admin",
    )
    db.add(new_user)
    db.commit()
    db.refresh(new_user)
    return _success(_user_payload(new_user))


@router.post("/auth/users/batch-delete")
async def batch_delete_users(request: Request, db: DbSession):
    body = await request.json()
    ids = [int(item) for item in _body_ids({"ids": body.get("user_ids") or body.get("ids") or []}) if str(item).isdigit()]
    rows = db.execute(select(User).where(User.id.in_(ids), User.username != "admin")).scalars().all()
    now = datetime.utcnow()
    for row in rows:
        row.is_active = False
        row.deleted_at = now
    db.commit()
    return _success({"deleted": len(rows)})


@router.post("/auth/users/batch-toggle-status")
async def batch_toggle_user_status(request: Request, db: DbSession):
    body = await request.json()
    ids = [int(item) for item in body.get("user_ids", body.get("ids", [])) if str(item).isdigit()]
    is_active = bool(body.get("is_active", True))
    rows = db.execute(select(User).where(User.id.in_(ids))).scalars().all()
    for row in rows:
        row.is_active = is_active
    db.commit()
    return _success({"updated": len(rows), "is_active": is_active})


@router.post("/auth/users/batch-reset-password")
async def batch_reset_user_password(request: Request, db: DbSession):
    body = await request.json()
    ids = [int(item) for item in body.get("user_ids", body.get("ids", [])) if str(item).isdigit()]
    password = str(body.get("new_password") or body.get("password") or "123456")
    rows = db.execute(select(User).where(User.id.in_(ids))).scalars().all()
    new_hash = hash_password(password)
    for row in rows:
        row.password_hash = new_hash
        row.must_change_pw = True
    db.commit()
    return _success({"updated": len(rows)})


@router.post("/auth/users/batch-change-role")
async def batch_change_user_role(request: Request, db: DbSession):
    body = await request.json()
    ids = [int(item) for item in body.get("user_ids", body.get("ids", [])) if str(item).isdigit()]
    role = body.get("new_role") or body.get("role")
    parent_id = body.get("target_operator_id") or body.get("parent_user_id")
    rows = db.execute(select(User).where(User.id.in_(ids))).scalars().all()
    for row in rows:
        if role:
            row.role = role
            row.is_superadmin = role == "super_admin"
            row.level = {"super_admin": 100, "operator": 50, "captain": 30}.get(role, 10)
        if parent_id is not None:
            row.parent_user_id = parent_id
    db.commit()
    return _success({"updated": len(rows)})


@router.post("/auth/users/batch-assign-to-operator")
async def batch_assign_users_to_operator(request: Request, db: DbSession):
    body = await request.json()
    ids = [int(item) for item in body.get("user_ids", body.get("ids", [])) if str(item).isdigit()]
    parent_id = body.get("target_operator_id") or body.get("parent_user_id")
    rows = db.execute(select(User).where(User.id.in_(ids))).scalars().all()
    for row in rows:
        row.parent_user_id = parent_id
    db.commit()
    return _success({"updated": len(rows)})


@router.post("/auth/users/batch-update-commission-rate")
async def batch_update_user_commission_rate(request: Request, db: DbSession):
    body = await request.json()
    ids = [int(item) for item in body.get("user_ids", body.get("ids", [])) if str(item).isdigit()]
    rate = float(body.get("commission_rate") or 0)
    rate = rate / 100 if rate > 1 else rate
    rows = db.execute(select(User).where(User.id.in_(ids))).scalars().all()
    for row in rows:
        row.commission_rate = rate
    db.commit()
    return _success({"updated": len(rows)})


@router.post("/auth/users/batch-commission-visibility")
async def batch_update_user_commission_visibility(request: Request, db: DbSession):
    body = await request.json()
    ids = [int(item) for item in body.get("user_ids", body.get("ids", [])) if str(item).isdigit()]
    rows = db.execute(select(User).where(User.id.in_(ids))).scalars().all()
    for row in rows:
        if "commission_rate_visible" in body:
            row.commission_rate_visible = bool(body.get("commission_rate_visible"))
        if "commission_amount_visible" in body:
            row.commission_amount_visible = bool(body.get("commission_amount_visible"))
        if "total_income_visible" in body:
            row.total_income_visible = bool(body.get("total_income_visible"))
    db.commit()
    return _success({"updated": len(rows)})


@router.post("/auth/users/batch/organizations")
async def batch_set_user_organizations(request: Request, db: DbSession):
    body = await request.json()
    ids = [int(item) for item in body.get("user_ids", body.get("ids", [])) if str(item).isdigit()]
    org_id = body.get("organization_id")
    rows = db.execute(select(User).where(User.id.in_(ids))).scalars().all()
    for row in rows:
        row.organization_id = org_id
    db.commit()
    return _success({"updated": len(rows)})


@router.post("/auth/users/batch-change-level")
async def batch_change_user_level(request: Request, db: DbSession):
    body = await request.json()
    ids = [int(item) for item in body.get("user_ids", body.get("ids", [])) if str(item).isdigit()]
    quota = None if body.get("user_level") == "enterprise" else 10
    rows = db.execute(select(User).where(User.id.in_(ids))).scalars().all()
    for row in rows:
        row.account_quota = quota
    db.commit()
    return _success({"updated": len(rows)})


@router.post("/auth/users/batch-change-quota")
async def batch_change_user_quota(request: Request, db: DbSession):
    body = await request.json()
    ids = [int(item) for item in body.get("user_ids", body.get("ids", [])) if str(item).isdigit()]
    quota = body.get("quota")
    rows = db.execute(select(User).where(User.id.in_(ids))).scalars().all()
    for row in rows:
        row.account_quota = None if quota in (None, -1, "-1") else int(quota)
    db.commit()
    return _success({"updated": len(rows)})


@router.post("/auth/users/batch-change-cooperation-type")
async def batch_change_cooperation_type(request: Request):
    body = await request.json()
    return _success({"updated": len(body.get("user_ids", body.get("ids", []))), "cooperation_type": body.get("cooperation_type", "cooperative")})


@router.get("/auth/operators")
async def operators(db: DbSession, user: CurrentUser):
    stmt = select(User).where(User.deleted_at.is_(None), User.role == "operator")
    stmt = _apply_org_scope(stmt, User, user)
    return _success([_user_payload(row) for row in db.execute(stmt).scalars().all()])


@router.get("/auth/users/{target_user_id}/alipay")
async def user_alipay(target_user_id: int, db: DbSession):
    row = db.execute(select(WalletProfile).where(WalletProfile.user_id == target_user_id)).scalar_one_or_none()
    if not row:
        return _success({"alipay_name": "", "alipay_account": "", "real_name": "", "notes": ""})
    return _success({"alipay_name": row.alipay_name, "alipay_account": row.alipay_account, "real_name": row.real_name, "notes": row.notes})


@router.put("/auth/users/{target_user_id}/alipay")
async def update_user_alipay(target_user_id: int, request: Request, db: DbSession):
    body = await request.json()
    row = db.execute(select(WalletProfile).where(WalletProfile.user_id == target_user_id)).scalar_one_or_none()
    if row is None:
        row = WalletProfile(user_id=target_user_id)
        db.add(row)
    row.real_name = body.get("real_name") or body.get("alipay_name") or row.real_name
    row.alipay_name = body.get("alipay_name") or body.get("real_name") or row.alipay_name
    row.alipay_account = body.get("alipay_account") or row.alipay_account
    row.notes = body.get("notes", row.notes)
    db.commit()
    return _success({"updated": True})


@router.get("/auth/users/{target_user_id}/auth-code")
async def user_auth_code(target_user_id: int, db: DbSession):
    target = db.get(User, target_user_id)
    return _success({"auth_code": target.phone or target.username if target else ""})


@router.put("/auth/users/{target_user_id}/auth-code")
async def set_user_auth_code(target_user_id: int, request: Request, db: DbSession):
    target = db.get(User, target_user_id)
    if target is None:
        return _success(None, message="用户不存在")
    body = await request.json()
    target.phone = body.get("auth_code") or target.phone
    db.commit()
    return _success({"auth_code": target.phone or target.username})


@router.get("/auth/users/{target_user_id}/organizations")
async def user_organizations(target_user_id: int, db: DbSession):
    target = db.get(User, target_user_id)
    return _success({"organization_id": target.organization_id if target else None})


@router.put("/auth/users/{target_user_id}/organizations")
async def set_user_organizations(target_user_id: int, request: Request, db: DbSession):
    target = db.get(User, target_user_id)
    if target is None:
        return _success(None, message="用户不存在")
    body = await request.json()
    target.organization_id = body.get("organization_id") or target.organization_id
    db.commit()
    return _success(_user_payload(target))


@router.put("/auth/users/{target_user_id}")
async def update_user(target_user_id: int, request: Request, db: DbSession):
    target = db.get(User, target_user_id)
    if target is None:
        return _success(None, message="用户不存在")
    body = await request.json()
    target.display_name = body.get("nickname") or body.get("display_name") or target.display_name
    target.email = body.get("email", target.email)
    target.phone = body.get("phone", target.phone)
    if body.get("organization_id") is not None:
        target.organization_id = body.get("organization_id")
    if body.get("parent_user_id") is not None:
        target.parent_user_id = body.get("parent_user_id")
    if body.get("role"):
        target.role = body.get("role")
        target.is_superadmin = target.role == "super_admin"
    db.commit()
    return _success(_user_payload(target))


@router.delete("/auth/users/{target_user_id}")
async def delete_user(target_user_id: int, db: DbSession):
    target = db.get(User, target_user_id)
    if target and target.username != "admin":
        target.is_active = False
        target.deleted_at = datetime.utcnow()
        db.commit()
    return _success({"deleted": True})


@router.put("/auth/users/{target_user_id}/status")
async def update_user_status(target_user_id: int, request: Request, db: DbSession):
    target = db.get(User, target_user_id)
    if target is None:
        return _success(None, message="用户不存在")
    body = await request.json()
    target.is_active = bool(body.get("is_active", not target.is_active))
    db.commit()
    return _success(_user_payload(target))


@router.post("/auth/users/{target_user_id}/reset-password")
async def reset_user_password(target_user_id: int, request: Request, db: DbSession):
    target = db.get(User, target_user_id)
    if target is None:
        return _success(None, message="用户不存在")
    body = await request.json()
    target.password_hash = hash_password(str(body.get("new_password") or body.get("password") or "123456"))
    target.must_change_pw = True
    db.commit()
    return _success({"updated": True})


@router.post("/auth/users/{target_user_id}/assign-to-operator")
async def assign_user_to_operator(target_user_id: int, request: Request, db: DbSession):
    target = db.get(User, target_user_id)
    if target is None:
        return _success(None, message="用户不存在")
    body = await request.json()
    target.parent_user_id = body.get("target_operator_id") or body.get("parent_user_id")
    db.commit()
    return _success(_user_payload(target))


@router.post("/auth/users/{target_user_id}/change-role")
async def change_user_role(target_user_id: int, request: Request, db: DbSession):
    target = db.get(User, target_user_id)
    if target is None:
        return _success(None, message="用户不存在")
    body = await request.json()
    role = body.get("new_role") or body.get("role")
    if role:
        target.role = role
        target.is_superadmin = role == "super_admin"
        target.level = {"super_admin": 100, "operator": 50, "captain": 30}.get(role, 10)
    if body.get("target_operator_id") is not None:
        target.parent_user_id = body.get("target_operator_id")
    db.commit()
    return _success(_user_payload(target))


@router.put("/auth/users/{target_user_id}/commission-rate")
async def update_user_commission_rate(target_user_id: int, request: Request, db: DbSession):
    target = db.get(User, target_user_id)
    if target is None:
        return _success(None, message="用户不存在")
    body = await request.json()
    rate = float(body.get("commission_rate") or target.commission_rate)
    target.commission_rate = rate / 100 if rate > 1 else rate
    db.commit()
    return _success(_user_payload(target))


@router.put("/auth/users/{target_user_id}/commission-visibility")
async def update_user_commission_visibility(target_user_id: int, request: Request, db: DbSession):
    target = db.get(User, target_user_id)
    if target is None:
        return _success(None, message="用户不存在")
    body = await request.json()
    target.commission_rate_visible = bool(body.get("commission_rate_visible", target.commission_rate_visible))
    target.commission_amount_visible = bool(body.get("commission_amount_visible", target.commission_amount_visible))
    target.total_income_visible = bool(body.get("total_income_visible", target.total_income_visible))
    db.commit()
    return _success(_user_payload(target))


@router.put("/auth/users/{target_user_id}/quota")
async def update_user_quota(target_user_id: int, request: Request, db: DbSession):
    target = db.get(User, target_user_id)
    if target is None:
        return _success(None, message="用户不存在")
    body = await request.json()
    quota = body.get("quota")
    target.account_quota = None if quota in (None, -1, "-1") else int(quota)
    db.commit()
    return _success(_user_payload(target))


@router.put("/auth/users/{target_user_id}/level")
@router.post("/auth/users/{target_user_id}/upgrade")
@router.put("/auth/users/{target_user_id}/upgrade")
async def update_user_level(target_user_id: int, db: DbSession):
    target = db.get(User, target_user_id)
    if target is None:
        return _success(None, message="用户不存在")
    target.account_quota = None
    db.commit()
    return _success(_user_payload(target))


@router.put("/auth/users/{target_user_id}/cooperation-type")
async def update_user_cooperation_type(target_user_id: int, request: Request):
    body = await request.json()
    return _success({"user_id": target_user_id, "cooperation_type": body.get("cooperation_type", "cooperative")})


@router.get("/auth/users/{target_user_id}/oem")
async def user_oem(target_user_id: int):
    return _success({"user_id": target_user_id, "is_oem": 0, "oem_name": None, "oem_config": {}})


@router.put("/auth/users/{target_user_id}/oem")
async def update_user_oem(target_user_id: int, request: Request):
    body = await request.json()
    return _success({"user_id": target_user_id, "is_oem": body.get("is_oem", 0), "oem_name": body.get("oem_name")})


@router.get("/auth/roles")
async def roles():
    return _success(
        [
            {"value": "super_admin", "label": "超级管理员"},
            {"value": "operator", "label": "运营"},
            {"value": "captain", "label": "队长"},
            {"value": "normal_user", "label": "普通用户"},
        ]
    )


@router.get("/auth/permissions")
async def permissions(db: DbSession):
    rows = db.execute(select(DefaultRolePermission).order_by(DefaultRolePermission.permission_type.asc(), DefaultRolePermission.permission_code.asc())).scalars().all()
    return _success(
        [
            {
                "id": row.permission_code,
                "key": row.permission_code,
                "name": row.permission_code,
                "module": row.permission_type,
                "min_role": row.role,
                "is_allowed": row.granted,
            }
            for row in rows
        ]
    )


@router.post("/auth/check-permission")
async def check_permission(req: CheckPermissionRequest, db: DbSession, user: CurrentUser):
    if user.is_superadmin:
        return _success({"allowed": True})
    button = db.execute(
        select(UserButtonPermission).where(
            UserButtonPermission.user_id == user.id,
            UserButtonPermission.permission_code == req.permission,
        )
    ).scalar_one_or_none()
    if button is not None:
        return _success({"allowed": bool(button.granted)})
    page = db.execute(
        select(UserPagePermission).where(
            UserPagePermission.user_id == user.id,
            UserPagePermission.permission_code == req.permission,
        )
    ).scalar_one_or_none()
    if page is not None:
        return _success({"allowed": bool(page.granted)})
    default = db.execute(
        select(DefaultRolePermission).where(
            DefaultRolePermission.role == _role_value(user),
            DefaultRolePermission.permission_code == req.permission,
        )
    ).scalar_one_or_none()
    return _success({"allowed": bool(default.granted) if default else False})


@router.get("/auth/logs")
async def logs(
    db: DbSession,
    user: CurrentUser,
    page: int = 1,
    page_size: int | None = None,
    size: int | None = None,
    action: str | None = None,
    module: str | None = None,
):
    page, per_page = _page_size(page, page_size, size)
    stmt = select(OperationLog)
    if not user.is_superadmin:
        stmt = stmt.where(OperationLog.organization_id == user.organization_id)
    if action:
        stmt = stmt.where(OperationLog.action == action)
    if module:
        stmt = stmt.where(OperationLog.module == module)
    total = _count(db, stmt)
    rows = db.execute(stmt.order_by(OperationLog.id.desc()).offset((page - 1) * per_page).limit(per_page)).scalars().all()
    data = [
        {
            "id": row.id,
            "user_id": row.user_id,
            "organization_id": row.organization_id,
            "action": row.action,
            "module": row.module,
            "target_type": row.target_type,
            "target_id": row.target_id,
            "detail": row.detail,
            "ip": row.ip,
            "success": 1 if row.success else 0,
            "created_at": _dt(row.created_at),
        }
        for row in rows
    ]
    return _success({"logs": data, "total": total}, total=total, pagination={"total": total, "page": page, "page_size": per_page})


@router.get("/auth/logs/stats")
async def log_stats(db: DbSession, user: CurrentUser):
    stmt = select(OperationLog)
    if not user.is_superadmin:
        stmt = stmt.where(OperationLog.organization_id == user.organization_id)
    total = _count(db, stmt)
    failed_stmt = select(OperationLog).where(OperationLog.success == 0)
    if not user.is_superadmin:
        failed_stmt = failed_stmt.where(OperationLog.organization_id == user.organization_id)
    return _success({"today": 0, "total": total, "errors": _count(db, failed_stmt)})


@router.delete("/auth/logs")
async def clear_logs(db: DbSession, user: CurrentUser):
    stmt = select(OperationLog)
    if not user.is_superadmin:
        stmt = stmt.where(OperationLog.organization_id == user.organization_id)
    rows = db.execute(stmt).scalars().all()
    for row in rows:
        db.delete(row)
    db.commit()
    return _success({"deleted": len(rows)})


@router.get("/auth/my-page-permissions")
async def my_page_permissions(db: DbSession, user: CurrentUser):
    codes = _catalog_codes(db, permission_type="web_page", model=UserPagePermission, prefix="page:")
    rows = _effective_permissions(db, user, codes, UserPagePermission, "web_page")
    return _success({row["key"]: bool(row["is_allowed"]) for row in rows})


@router.get("/auth/my-button-permissions")
async def my_button_permissions(db: DbSession, user: CurrentUser):
    codes = _catalog_codes(db, permission_type="account_button", model=UserButtonPermission)
    rows = _effective_permissions(db, user, codes, UserButtonPermission, "account_button")
    return _success({row["key"]: bool(row["is_allowed"]) for row in rows})


@router.get("/auth/button-permissions/buttons")
async def button_permission_buttons(db: DbSession):
    codes = _catalog_codes(db, permission_type="account_button", model=UserButtonPermission, prefix="account:")
    return _success([_permission_payload(code, 1) for code in codes])


@router.get("/auth/button-permissions/user/{target_user_id}")
async def button_permissions_for_user(target_user_id: int, db: DbSession):
    target = db.get(User, target_user_id)
    if target is None:
        return _success({"permissions": []})
    codes = _catalog_codes(db, permission_type="account_button", model=UserButtonPermission, prefix="account:")
    return _success({"permissions": _effective_permissions(db, target, codes, UserButtonPermission, "account_button")})


@router.post("/auth/button-permissions/user/{target_user_id}")
async def set_button_permissions_for_user(target_user_id: int, req: PermissionUpdateRequest, db: DbSession):
    _upsert_permissions(db, target_user_id, req.permissions, UserButtonPermission)
    return _success({"updated": len(req.permissions)})


@router.get("/auth/user-management-buttons")
async def user_management_buttons(db: DbSession):
    codes = _catalog_codes(db, permission_type="user_mgmt_button")
    if not codes:
        codes = _catalog_codes(db, model=UserButtonPermission, prefix="user")
    return _success([_permission_payload(code, 1) for code in codes])


@router.get("/auth/users/{target_user_id}/user-button-permissions")
async def user_management_permissions_for_user(target_user_id: int, db: DbSession):
    target = db.get(User, target_user_id)
    if target is None:
        return _success({"permissions": []})
    codes = _catalog_codes(db, permission_type="user_mgmt_button")
    if not codes:
        codes = _catalog_codes(db, model=UserButtonPermission, prefix="user")
    return _success({"permissions": _effective_permissions(db, target, codes, UserButtonPermission, "user_mgmt_button")})


@router.put("/auth/users/{target_user_id}/user-button-permissions")
async def set_user_management_permissions_for_user(target_user_id: int, req: PermissionUpdateRequest, db: DbSession):
    _upsert_permissions(db, target_user_id, req.permissions, UserButtonPermission)
    return _success({"updated": len(req.permissions)})


@router.get("/auth/page-permissions/pages")
async def page_permission_pages(db: DbSession):
    codes = _catalog_codes(db, permission_type="web_page", model=UserPagePermission, prefix="page:")
    return _success([_permission_payload(code, 1) for code in codes])


@router.get("/auth/page-permissions/user/{target_user_id}")
async def page_permissions_for_user(target_user_id: int, db: DbSession):
    target = db.get(User, target_user_id)
    if target is None:
        return _success({"permissions": []})
    codes = _catalog_codes(db, permission_type="web_page", model=UserPagePermission, prefix="page:")
    return _success({"permissions": _effective_permissions(db, target, codes, UserPagePermission, "web_page")})


@router.post("/auth/page-permissions/user/{target_user_id}")
async def set_page_permissions_for_user(target_user_id: int, req: PermissionUpdateRequest, db: DbSession):
    _upsert_permissions(db, target_user_id, req.permissions, UserPagePermission)
    return _success({"updated": len(req.permissions)})


@router.get("/auth/role-default-permissions/{role}")
async def role_default_permissions(role: str, db: DbSession):
    rows = db.execute(
        select(DefaultRolePermission).where(DefaultRolePermission.role == role).order_by(DefaultRolePermission.permission_type.asc(), DefaultRolePermission.permission_code.asc())
    ).scalars().all()
    return _success(
        {
            "role": role,
            "permissions": [
                {
                    "key": row.permission_code,
                    "perm_key": row.permission_code,
                    "permission_type": row.permission_type,
                    "perm_type": row.permission_type,
                    "is_allowed": row.granted,
                }
                for row in rows
            ],
        }
    )


@router.put("/auth/role-default-permissions/{role}")
async def set_role_default_permissions(role: str, req: PermissionUpdateRequest, db: DbSession):
    for item in req.permissions:
        code = item.get("perm_key") or item.get("button_key") or item.get("page_key") or item.get("key")
        code = str(code).strip() if code is not None else ""
        if not code:
            continue
        perm_type = str(item.get("perm_type") or item.get("permission_type") or ("web_page" if code.startswith("page:") else "account_button"))
        granted = 1 if item.get("is_allowed") in (True, 1, "1", "true", "True") else 0
        existing = db.execute(
            select(DefaultRolePermission).where(
                DefaultRolePermission.role == role,
                DefaultRolePermission.permission_type == perm_type,
                DefaultRolePermission.permission_code == code,
            )
        ).scalar_one_or_none()
        if existing is None:
            db.add(DefaultRolePermission(role=role, permission_type=perm_type, permission_code=code, granted=granted))
        else:
            existing.granted = granted
    db.commit()
    return _success({"updated": len(req.permissions)})


@router.get("/page-permissions/user/{target_user_id}")
async def client_page_permissions_for_user(target_user_id: int, db: DbSession):
    target = db.get(User, target_user_id)
    if target is None:
        return _success([])
    codes = _catalog_codes(db, permission_type="client_page")
    rows = _effective_permissions(db, target, codes, UserPagePermission, "client_page")
    return _success([{"page_key": row["key"], "key": row["key"], "is_allowed": row["is_allowed"]} for row in rows])


@router.post("/page-permissions/user/{target_user_id}/update")
async def update_client_page_permissions(target_user_id: int, req: PermissionUpdateRequest, db: DbSession):
    _upsert_permissions(db, target_user_id, req.permissions, UserPagePermission)
    return _success({"updated": len(req.permissions)})


@router.post("/page-permissions/user/{target_user_id}/reset")
async def reset_client_page_permissions(target_user_id: int, db: DbSession):
    codes = _catalog_codes(db, permission_type="client_page")
    _upsert_permissions(
        db,
        target_user_id,
        [{"page_key": code, "is_allowed": 1} for code in codes],
        UserPagePermission,
    )
    return _success({"updated": len(codes)})


@router.post("/page-permissions/batch-update")
async def batch_update_client_page_permissions(request: Request, db: DbSession):
    body = await request.json()
    user_ids = body.get("user_ids") or body.get("ids") or []
    permissions = body.get("permissions") or []
    for user_id in user_ids:
        _upsert_permissions(db, int(user_id), permissions, UserPagePermission)
    return _success({"updated_users": len(user_ids), "updated_permissions": len(permissions)})


@router.get("/organizations")
async def organizations(db: DbSession, user: CurrentUser):
    stmt = select(Organization).where(Organization.deleted_at.is_(None)).order_by(Organization.id.asc())
    if not user.is_superadmin:
        stmt = stmt.where(Organization.id == user.organization_id)
    rows = db.execute(stmt).scalars().all()
    return _success([_organization_payload(row) for row in rows])


@router.get("/organizations/accessible")
async def accessible_organizations(db: DbSession, user: CurrentUser):
    return await organizations(db, user)


@router.post("/organizations")
async def create_organization(request: Request, db: DbSession):
    body = await request.json()
    name = str(body.get("name") or body.get("org_name") or "").strip()
    if not name:
        return _success(None, message="机构名称不能为空")
    code = str(body.get("org_code") or body.get("code") or f"ORG_{int(datetime.utcnow().timestamp())}").strip()
    org = Organization(
        name=name,
        org_code=code,
        org_type=body.get("org_type") or "mcn",
        contact_name=body.get("contact_name"),
        contact_phone=body.get("contact_phone"),
        contact_email=body.get("contact_email"),
        plan_tier=body.get("plan_tier") or "enterprise",
        max_accounts=int(body.get("max_accounts") or 999999),
        max_users=int(body.get("max_users") or 99999),
        is_active=bool(body.get("is_active", 1)),
        notes=body.get("notes") or body.get("description"),
    )
    db.add(org)
    db.commit()
    db.refresh(org)
    return _success(_organization_payload(org))


@router.put("/organizations/{org_id}")
async def update_organization(org_id: int, request: Request, db: DbSession):
    org = db.get(Organization, org_id)
    if org is None:
        return _success(None, message="机构不存在")
    body = await request.json()
    org.name = body.get("name") or body.get("org_name") or org.name
    org.org_code = body.get("org_code") or body.get("code") or org.org_code
    org.contact_name = body.get("contact_name", org.contact_name)
    org.contact_phone = body.get("contact_phone", org.contact_phone)
    org.contact_email = body.get("contact_email", org.contact_email)
    org.notes = body.get("notes", body.get("description", org.notes))
    if "is_active" in body:
        org.is_active = bool(body.get("is_active"))
    db.commit()
    return _success(_organization_payload(org))


@router.put("/organizations/{org_id}/toggle-status")
async def toggle_organization_status(org_id: int, db: DbSession):
    org = db.get(Organization, org_id)
    if org is None:
        return _success(None, message="机构不存在")
    org.is_active = not bool(org.is_active)
    db.commit()
    return _success(_organization_payload(org))


@router.put("/organizations/{org_id}/org-code")
async def update_organization_code(org_id: int, request: Request, db: DbSession):
    org = db.get(Organization, org_id)
    if org is None:
        return _success(None, message="机构不存在")
    body = await request.json()
    org.org_code = body.get("org_code") or org.org_code
    db.commit()
    return _success(_organization_payload(org))


@router.delete("/organizations/{org_id}")
async def delete_organization(org_id: int, db: DbSession):
    org = db.get(Organization, org_id)
    if org is None:
        return _success(None, message="机构不存在")
    # Business rule from production sync: organizations are preserved and only disabled.
    org.is_active = False
    db.commit()
    return _success({"deleted": False, "disabled": True}, message="机构已停用，未从数据库删除")


@router.get("/groups")
async def groups(db: DbSession, user: CurrentUser):
    stmt = select(AccountGroup).order_by(AccountGroup.id.asc())
    stmt = _apply_org_scope(stmt, AccountGroup, user)
    rows = db.execute(stmt).scalars().all()
    counts = dict(
        db.execute(
            select(Account.group_id, func.count(Account.id))
            .where(Account.deleted_at.is_(None))
            .group_by(Account.group_id)
        ).all()
    )
    ungrouped = int(
        db.execute(
            select(func.count(Account.id)).where(Account.deleted_at.is_(None), Account.group_id.is_(None))
        ).scalar_one()
    )
    group_rows = [_group_payload(row, counts.get(row.id, 0)) for row in rows]
    return _success({"groups": group_rows, "tree_data": group_rows, "ungrouped_count": ungrouped})


@router.post("/groups")
async def create_group(request: Request, db: DbSession, user: CurrentUser):
    body = await request.json()
    name = str(body.get("group_name") or body.get("name") or "").strip()
    if not name:
        return _success(None, message="分组名称不能为空")
    group = AccountGroup(
        organization_id=int(body.get("organization_id") or user.organization_id),
        owner_user_id=body.get("owner_id") or body.get("owner_user_id"),
        name=name,
        color=body.get("color"),
    )
    db.add(group)
    db.commit()
    db.refresh(group)
    return _success(_group_payload(group))


@router.put("/groups/{group_id}")
async def update_group(group_id: int, request: Request, db: DbSession):
    group = db.get(AccountGroup, group_id)
    if group is None:
        return _success(None, message="分组不存在")
    body = await request.json()
    group.name = body.get("group_name") or body.get("name") or group.name
    group.color = body.get("color", group.color)
    if body.get("owner_id") is not None:
        group.owner_user_id = body.get("owner_id")
    db.commit()
    return _success(_group_payload(group))


@router.delete("/groups/{group_id}")
async def delete_group(group_id: int, db: DbSession):
    group = db.get(AccountGroup, group_id)
    if group is not None:
        db.execute(select(Account).where(Account.group_id == group_id)).scalars()
        for account in db.execute(select(Account).where(Account.group_id == group_id)).scalars().all():
            account.group_id = None
        db.delete(group)
        db.commit()
    return _success({"deleted": True})


@router.post("/groups/assign")
async def assign_accounts_to_group(request: Request, db: DbSession):
    body = await request.json()
    group_id = body.get("group_id")
    uids = body.get("uids") or body.get("account_ids") or []
    stmt = select(Account)
    if uids:
        stmt = stmt.where(or_(Account.kuaishou_id.in_(uids), Account.real_uid.in_(uids), Account.id.in_(uids)))
    for account in db.execute(stmt).scalars().all():
        account.group_id = group_id
    db.commit()
    return _success({"updated": len(uids)})


@router.get("/groups/{group_id}/accounts")
async def group_accounts(group_id: int, db: DbSession, user: CurrentUser, page: int = 1, page_size: int | None = None, size: int | None = None):
    return await accounts(db, user, page=page, page_size=page_size, size=size, group_id=group_id)


@router.get("/accounts")
async def accounts(
    db: DbSession,
    user: CurrentUser,
    page: int = 1,
    page_size: int | None = None,
    size: int | None = None,
    search: str | None = None,
    keyword: str | None = None,
    organization_id: int | None = None,
    org_id: int | None = None,
    group_id: int | None = None,
    owner_id: int | None = None,
):
    page, per_page = _page_size(page, page_size, size)
    term = search or keyword
    stmt = select(Account).where(Account.deleted_at.is_(None))
    stmt = _apply_org_scope(stmt, Account, user)
    if term:
        like = f"%{term}%"
        stmt = stmt.where(or_(Account.kuaishou_id.like(like), Account.real_uid.like(like), Account.nickname.like(like)))
    org_filter = organization_id or org_id
    if org_filter and user.is_superadmin:
        stmt = stmt.where(Account.organization_id == org_filter)
    if group_id is not None:
        stmt = stmt.where(Account.group_id == group_id)
    if owner_id is not None:
        stmt = stmt.where(Account.assigned_user_id == owner_id)
    total = _count(db, stmt)
    rows = db.execute(stmt.order_by(Account.id.desc()).offset((page - 1) * per_page).limit(per_page)).scalars().all()
    mcn_count = int(db.execute(select(func.count(Account.id)).where(Account.deleted_at.is_(None), Account.mcn_status.is_not(None))).scalar_one())
    data = {
        "accounts": [_account_payload(row) for row in rows],
        "total": total,
        "mcn_count": mcn_count,
        "normal_count": max(total - mcn_count, 0),
        "user_role": "super_admin" if user.is_superadmin else user.role,
    }
    return _success(data)


@router.post("/accounts")
async def create_account(request: Request, db: DbSession, user: CurrentUser):
    body = await request.json()
    uid = body.get("uid") or body.get("kuaishou_id") or body.get("real_uid")
    if not uid:
        return _success(None, message="账号 UID 不能为空")
    org_id = int(body.get("organization_id") or body.get("org_id") or user.organization_id)
    account = Account(
        organization_id=org_id,
        assigned_user_id=body.get("owner_id") or body.get("user_id") or body.get("assigned_user_id"),
        group_id=body.get("group_id"),
        kuaishou_id=str(body.get("kuaishou_id") or uid),
        real_uid=str(body.get("real_uid") or body.get("uid_real") or uid),
        nickname=body.get("nickname"),
        status=body.get("status") or body.get("account_status") or "active",
        mcn_status=body.get("mcn_status"),
        sign_status=body.get("sign_status") or body.get("contract_status"),
        commission_rate=float(body.get("commission_rate") or body.get("account_commission_rate") or 0.8),
        device_serial=body.get("device_serial") or body.get("device_code"),
        remark=body.get("remark"),
        imported_by_user_id=user.id,
        imported_at=datetime.utcnow(),
    )
    db.add(account)
    db.commit()
    db.refresh(account)
    return _success(_account_payload(account))


@router.post("/accounts/batch-import")
async def batch_import_accounts(request: Request, db: DbSession, user: CurrentUser):
    body = await request.json()
    raw_accounts = body.get("accounts") or body.get("items") or []
    created = 0
    updated = 0
    org_id = int(body.get("organization_id") or user.organization_id)
    for item in raw_accounts:
        if isinstance(item, str):
            item = {"uid": item}
        uid = str(item.get("uid") or item.get("kuaishou_id") or item.get("real_uid") or "").strip()
        if not uid:
            continue
        existing = db.execute(
            select(Account).where(
                Account.deleted_at.is_(None),
                or_(Account.kuaishou_id == uid, Account.real_uid == uid),
            )
        ).scalar_one_or_none()
        if existing:
            existing.nickname = item.get("nickname") or existing.nickname
            existing.organization_id = int(item.get("organization_id") or org_id)
            existing.group_id = item.get("group_id", existing.group_id)
            updated += 1
        else:
            db.add(
                Account(
                    organization_id=int(item.get("organization_id") or org_id),
                    kuaishou_id=str(item.get("kuaishou_id") or uid),
                    real_uid=str(item.get("real_uid") or item.get("uid_real") or uid),
                    nickname=item.get("nickname"),
                    status=item.get("status") or "active",
                    commission_rate=float(item.get("commission_rate") or 0.8),
                    imported_by_user_id=user.id,
                    imported_at=datetime.utcnow(),
                )
            )
            created += 1
    db.commit()
    return _success({"created": created, "updated": updated})


@router.post("/accounts/assign")
async def assign_accounts_to_user(request: Request, db: DbSession):
    body = await request.json()
    target_user_id = body.get("user_id") or body.get("assigned_user_id") or body.get("owner_id")
    accounts_to_update = db.execute(_account_stmt_for_ids(_body_ids(body))).scalars().all()
    for account in accounts_to_update:
        account.assigned_user_id = target_user_id
    db.commit()
    return _success({"updated": len(accounts_to_update)})


@router.post("/accounts/batch-assign-organization")
async def batch_assign_account_organization(request: Request, db: DbSession):
    body = await request.json()
    org_id = body.get("organization_id") or body.get("org_id")
    accounts_to_update = db.execute(_account_stmt_for_ids(_body_ids(body))).scalars().all()
    for account in accounts_to_update:
        account.organization_id = org_id
    db.commit()
    return _success({"updated": len(accounts_to_update)})


@router.post("/accounts/batch-commission-rate")
async def batch_account_commission_rate(request: Request, db: DbSession):
    body = await request.json()
    rate = body.get("commission_rate") or body.get("account_commission_rate")
    rate = float(rate) / 100 if rate and float(rate) > 1 else float(rate or 0)
    accounts_to_update = db.execute(_account_stmt_for_ids(_body_ids(body))).scalars().all()
    for account in accounts_to_update:
        account.commission_rate = rate
    db.commit()
    return _success({"updated": len(accounts_to_update)})


@router.post("/accounts/batch-delete")
async def batch_delete_accounts(request: Request, db: DbSession):
    body = await request.json()
    accounts_to_update = db.execute(_account_stmt_for_ids(_body_ids(body))).scalars().all()
    now = datetime.utcnow()
    for account in accounts_to_update:
        account.status = "deleted"
        account.deleted_at = now
    db.commit()
    return _success({"deleted": len(accounts_to_update)})


@router.post("/accounts/set-status")
@router.post("/accounts/blacklist")
@router.post("/accounts/batch-operate-by-uids")
async def set_account_status(request: Request, db: DbSession):
    body = await request.json()
    status = body.get("status") or body.get("account_status") or ("blacklisted" if "blacklist" in str(request.url.path) else "active")
    accounts_to_update = db.execute(_account_stmt_for_ids(_body_ids(body))).scalars().all()
    for account in accounts_to_update:
        account.status = status
    db.commit()
    return _success({"updated": len(accounts_to_update), "status": status})


@router.post("/accounts/batch-import-uid-real")
async def batch_import_uid_real(request: Request, db: DbSession):
    body = await request.json()
    mappings = body.get("mappings") or body.get("items") or []
    updated = 0
    for item in mappings:
        uid = str(item.get("uid") or item.get("kuaishou_id") or "").strip()
        real_uid = str(item.get("real_uid") or item.get("uid_real") or "").strip()
        if not uid or not real_uid:
            continue
        account = db.execute(
            select(Account).where(Account.deleted_at.is_(None), Account.kuaishou_id == uid)
        ).scalar_one_or_none()
        if account:
            account.real_uid = real_uid
            updated += 1
    db.commit()
    return _success({"updated": updated})


@router.post("/accounts/batch-authorize")
async def batch_authorize_accounts(request: Request, db: DbSession):
    body = await request.json()
    is_member = bool(body.get("is_mcm_member", body.get("is_mcn_member", True)))
    accounts_to_update = db.execute(_account_stmt_for_ids(_body_ids(body))).scalars().all()
    for account in accounts_to_update:
        account.mcn_status = "authorized" if is_member else "unauthorized"
    db.commit()
    return _success({"updated": len(accounts_to_update)})


@router.post("/accounts/batch-update-income")
@router.post("/accounts/sync-commission-rate")
async def account_internal_refresh(request: Request):
    return _success({"updated": 0, "note": "当前接口不改写收益明细，收益以 huoshijie 数据同步为准"})


@router.post("/accounts/direct-invite")
@router.post("/accounts/batch-direct-invite")
@router.post("/accounts/open-spark")
@router.post("/accounts/batch-open-spark")
@router.post("/accounts/sync-mcn-authorization")
@router.post("/accounts/invitation-records")
@router.post("/accounts/batch-invitation-records")
async def kuaishou_external_placeholder():
    return _success(
        {"external_connected": False, "queued": False},
        message="快手外部链路尚未接入，未伪造真实执行结果",
    )


@router.get("/accounts/assignable-users")
async def assignable_users(db: DbSession, user: CurrentUser):
    return await users(db, user, page=1, page_size=100000)


@router.get("/accounts/organization-stats")
async def organization_stats(db: DbSession, user: CurrentUser):
    stmt = select(Account.organization_id, func.count(Account.id)).where(Account.deleted_at.is_(None)).group_by(Account.organization_id)
    stmt = _apply_org_scope(stmt, Account, user)
    counts = dict(db.execute(stmt).all())
    orgs = db.execute(select(Organization).where(Organization.deleted_at.is_(None))).scalars().all()
    return _success([
        {**_organization_payload(org), "account_count": counts.get(org.id, 0)}
        for org in orgs
        if user.is_superadmin or org.id == user.organization_id
    ])


@router.get("/accounts/{account_id}")
async def account_detail(account_id: int, db: DbSession):
    account = db.get(Account, account_id)
    return _success(_account_payload(account) if account else None)


@router.put("/accounts/{account_id}")
@router.put("/accounts/by-id/{account_id}")
async def update_account(account_id: int, request: Request, db: DbSession):
    account = db.get(Account, account_id)
    if account is None:
        return _success(None, message="账号不存在")
    body = await request.json()
    account.kuaishou_id = body.get("kuaishou_id") or body.get("uid") or account.kuaishou_id
    account.real_uid = body.get("real_uid") or body.get("uid_real") or account.real_uid
    account.nickname = body.get("nickname", account.nickname)
    account.device_serial = body.get("device_serial", account.device_serial)
    account.status = body.get("status") or body.get("account_status") or account.status
    account.mcn_status = body.get("mcn_status", account.mcn_status)
    account.sign_status = body.get("sign_status") or body.get("contract_status") or account.sign_status
    account.remark = body.get("remark", account.remark)
    if body.get("organization_id") is not None:
        account.organization_id = body.get("organization_id")
    if body.get("group_id") is not None:
        account.group_id = body.get("group_id")
    if body.get("owner_id") is not None or body.get("user_id") is not None:
        account.assigned_user_id = body.get("owner_id") or body.get("user_id")
    db.commit()
    return _success(_account_payload(account))


@router.delete("/accounts/{account_id}")
async def delete_account(account_id: int, db: DbSession):
    account = db.get(Account, account_id)
    if account:
        account.status = "deleted"
        account.deleted_at = datetime.utcnow()
        db.commit()
    return _success({"deleted": True})


@router.put("/accounts/{account_id}/commission-rate")
async def update_account_commission_rate(account_id: int, request: Request, db: DbSession):
    account = db.get(Account, account_id)
    if account is None:
        return _success(None, message="账号不存在")
    body = await request.json()
    rate = float(body.get("commission_rate") or body.get("account_commission_rate") or account.commission_rate)
    account.commission_rate = rate / 100 if rate > 1 else rate
    db.commit()
    return _success(_account_payload(account))


@router.put("/accounts/{account_id}/uid-real")
async def update_account_uid_real(account_id: int, request: Request, db: DbSession):
    account = db.get(Account, account_id)
    if account is None:
        return _success(None, message="账号不存在")
    body = await request.json()
    account.real_uid = body.get("uid_real") or body.get("real_uid") or account.real_uid
    db.commit()
    return _success(_account_payload(account))


@router.get("/accounts/{account_id}/tasks")
async def account_tasks(account_id: int, db: DbSession, page: int = 1, page_size: int | None = None, size: int | None = None):
    page, per_page = _page_size(page, page_size, size)
    stmt = select(AccountTaskRecord).where(AccountTaskRecord.account_id == account_id)
    total = _count(db, stmt)
    rows = db.execute(stmt.order_by(AccountTaskRecord.id.desc()).offset((page - 1) * per_page).limit(per_page)).scalars().all()
    return _success(
        [
            {
                "id": row.id,
                "account_id": row.account_id,
                "task_type": row.task_type,
                "drama_id": row.drama_id,
                "drama_name": row.drama_name,
                "success": 1 if row.success else 0,
                "duration_ms": row.duration_ms,
                "error_message": row.error_message,
                "created_at": _dt(row.created_at),
            }
            for row in rows
        ],
        total=total,
    )


@router.get("/accounts/{account_id}/stats")
async def account_task_stats(account_id: int, db: DbSession):
    total = _count(db, select(AccountTaskRecord).where(AccountTaskRecord.account_id == account_id))
    success = _count(db, select(AccountTaskRecord).where(AccountTaskRecord.account_id == account_id, AccountTaskRecord.success.is_(True)))
    return _success({"total": total, "success": success, "failed": max(total - success, 0)})


@router.delete("/accounts/{account_id}/tasks/{task_id}")
async def delete_account_task(account_id: int, task_id: int, db: DbSession):
    row = db.get(AccountTaskRecord, task_id)
    if row and row.account_id == account_id:
        db.delete(row)
        db.commit()
    return _success({"deleted": True})


@router.get("/ks-accounts")
async def ks_accounts(
    db: DbSession,
    user: CurrentUser,
    page: int = 1,
    pageSize: int | None = None,
    page_size: int | None = None,
    size: int | None = None,
    keyword: str | None = None,
):
    page, per_page = _page_size(page, page_size or pageSize, size)
    stmt = select(KsAccount)
    stmt = _apply_org_scope(stmt, KsAccount, user)
    if keyword:
        like = f"%{keyword}%"
        stmt = stmt.where(or_(KsAccount.account_name.like(like), KsAccount.kuaishou_uid.like(like), KsAccount.device_code.like(like)))
    total = _count(db, stmt)
    rows = db.execute(stmt.order_by(KsAccount.id.desc()).offset((page - 1) * per_page).limit(per_page)).scalars().all()
    return _success(
        [_ks_account_payload(row) for row in rows],
        pagination={"total": total, "page": page, "page_size": per_page},
    )


@router.get("/accounts/organization-stats")
async def account_organization_stats(db: DbSession, user: CurrentUser):
    stmt = (
        select(Organization.id, Organization.name, func.count(Account.id))
        .join(Account, Account.organization_id == Organization.id, isouter=True)
        .where(Organization.deleted_at.is_(None))
        .group_by(Organization.id, Organization.name)
        .order_by(Organization.id.asc())
    )
    if not user.is_superadmin:
        stmt = stmt.where(Organization.id == user.organization_id)
    rows = db.execute(stmt).all()
    return _success([{"organization_id": oid, "organization_name": name, "total": count} for oid, name, count in rows])


@router.get("/accounts/assignable-users")
async def assignable_users(db: DbSession, user: CurrentUser):
    return await users(db, user, page=1, page_size=500)


@router.post("/accounts/batch-delete")
async def batch_delete_accounts(payload: dict[str, Any], db: DbSession, user: CurrentUser):
    uids = payload.get("uids") or payload.get("ids") or []
    stmt = select(Account).where(Account.deleted_at.is_(None))
    stmt = _apply_org_scope(stmt, Account, user)
    stmt = stmt.where(or_(Account.kuaishou_id.in_(uids), Account.real_uid.in_(uids), Account.id.in_([x for x in uids if isinstance(x, int)])))
    rows = db.execute(stmt).scalars().all()
    now = datetime.utcnow()
    for row in rows:
        row.status = "deleted"
        row.deleted_at = now
    db.commit()
    return _success({"deleted_count": len(rows)}, deleted_count=len(rows))


@router.get("/org-members")
async def org_members(
    db: DbSession,
    user: CurrentUser,
    page: int = 1,
    page_size: int | None = None,
    size: int | None = None,
    search: str | None = None,
    broker_name: str | None = None,
    contract_renew_status: str | None = None,
    agreement_type: str | None = None,
):
    page, per_page = _page_size(page, page_size, size)
    stmt = select(OrgMember)
    stmt = _apply_org_scope(stmt, OrgMember, user)
    if search:
        like = f"%{search}%"
        stmt = stmt.where(or_(OrgMember.nickname.like(like), OrgMember.member_id.cast(String).like(like)))
    if broker_name:
        stmt = stmt.where(OrgMember.broker_name == broker_name)
    if contract_renew_status:
        stmt = stmt.where(OrgMember.renewal_status == contract_renew_status)
    if agreement_type:
        stmt = stmt.where(OrgMember.cooperation_type == agreement_type)
    total = _count(db, stmt)
    rows = db.execute(stmt.order_by(OrgMember.id.desc()).offset((page - 1) * per_page).limit(per_page)).scalars().all()
    return _success([_org_member_payload(row) for row in rows], total=total)


@router.get("/org-members/brokers")
async def org_member_brokers(db: DbSession, user: CurrentUser):
    stmt = select(OrgMember.broker_name).where(OrgMember.broker_name.is_not(None)).distinct()
    if not user.is_superadmin:
        stmt = stmt.where(OrgMember.organization_id == user.organization_id)
    return _success([name for name in db.execute(stmt).scalars().all() if name])


@router.get("/org-members/operators")
async def org_member_operators(db: DbSession, user: CurrentUser):
    return await users(db, user, page=1, page_size=500)


@router.get("/org-members/groups")
async def org_member_groups(db: DbSession, user: CurrentUser):
    return await groups(db, user)


@router.get("/spark/violation-photos")
async def spark_violation_photos(
    db: DbSession,
    user: CurrentUser,
    page: int = 1,
    page_size: int | None = None,
    size: int | None = None,
    search: str | None = None,
    sub_biz: str | None = None,
    broker_name: str | None = None,
):
    page, per_page = _page_size(page, page_size, size)
    stmt = select(ViolationPhoto)
    stmt = _apply_org_scope(stmt, ViolationPhoto, user)
    if search:
        like = f"%{search}%"
        stmt = stmt.where(or_(ViolationPhoto.uid.like(like), ViolationPhoto.description.like(like), ViolationPhoto.work_id.like(like)))
    if sub_biz:
        stmt = stmt.where(ViolationPhoto.business_type == sub_biz)
    total = _count(db, stmt)
    rows = db.execute(stmt.order_by(ViolationPhoto.id.desc()).offset((page - 1) * per_page).limit(per_page)).scalars().all()
    return _success([_violation_payload(row) for row in rows], total=total)


@router.get("/firefly/members")
async def firefly_members(db: DbSession, user: CurrentUser, page: int = 1, page_size: int | None = None, size: int | None = None, search: str | None = None):
    page, per_page = _page_size(page, page_size, size)
    stmt = select(FireflyMember)
    stmt = _apply_org_scope(stmt, FireflyMember, user)
    if search:
        like = f"%{search}%"
        stmt = stmt.where(or_(FireflyMember.nickname.like(like), FireflyMember.member_id.cast(String).like(like)))
    total = _count(db, stmt)
    rows = db.execute(stmt.order_by(FireflyMember.total_amount.desc()).offset((page - 1) * per_page).limit(per_page)).scalars().all()
    return _success([_member_payload(row) for row in rows], total=total)


@router.get("/firefly/members/stats")
async def firefly_member_stats(db: DbSession, user: CurrentUser):
    stmt = select(func.count(FireflyMember.id), func.coalesce(func.sum(FireflyMember.total_amount), 0))
    if not user.is_superadmin:
        stmt = stmt.where(FireflyMember.organization_id == user.organization_id)
    total, amount = db.execute(stmt).one()
    return _success({"total_members": total, "total_amount": amount, "period_income": amount, "period_commission": 0})


@router.get("/firefly/members/groups")
async def firefly_member_groups(db: DbSession, user: CurrentUser):
    return await groups(db, user)


@router.get("/firefly/members/operators")
async def firefly_member_operators(db: DbSession, user: CurrentUser):
    return await users(db, user, page=1, page_size=500)


@router.get("/firefly/members/organizations")
async def firefly_member_organizations(db: DbSession, user: CurrentUser):
    return await organizations(db, user)


@router.get("/firefly/income/organizations")
async def firefly_income_organizations(db: DbSession, user: CurrentUser):
    return await organizations(db, user)


@router.get("/firefly/income/groups")
async def firefly_income_groups(db: DbSession, user: CurrentUser):
    return await groups(db, user)


@router.get("/firefly/income/operators")
async def firefly_income_operators(db: DbSession, user: CurrentUser):
    return await users(db, user, page=1, page_size=500)


@router.get("/spark/members")
async def spark_members(db: DbSession, user: CurrentUser, page: int = 1, page_size: int | None = None, size: int | None = None, search: str | None = None, broker_name: str | None = None):
    page, per_page = _page_size(page, page_size, size)
    stmt = select(SparkMember)
    stmt = _apply_org_scope(stmt, SparkMember, user)
    if search:
        like = f"%{search}%"
        stmt = stmt.where(or_(SparkMember.nickname.like(like), SparkMember.member_id.cast(String).like(like)))
    if broker_name:
        stmt = stmt.where(SparkMember.broker_name == broker_name)
    total = _count(db, stmt)
    rows = db.execute(stmt.order_by(SparkMember.task_count.desc()).offset((page - 1) * per_page).limit(per_page)).scalars().all()
    return _success([_member_payload(row) for row in rows], total=total)


@router.get("/spark/members/stats")
async def spark_member_stats(db: DbSession, user: CurrentUser):
    stmt = select(func.count(SparkMember.id), func.coalesce(func.sum(SparkMember.task_count), 0))
    if not user.is_superadmin:
        stmt = stmt.where(SparkMember.organization_id == user.organization_id)
    total, tasks = db.execute(stmt).one()
    return _success({"total_members": total, "total_tasks": tasks, "period_income": 0, "period_commission": 0, "monthly_period": ""})


@router.get("/spark/groups")
async def spark_groups(db: DbSession, user: CurrentUser):
    return await groups(db, user)


@router.get("/spark/operators")
async def spark_operators(db: DbSession, user: CurrentUser):
    return await users(db, user, page=1, page_size=500)


@router.get("/spark/brokers")
async def spark_brokers(db: DbSession, user: CurrentUser):
    stmt = select(SparkMember.broker_name).where(SparkMember.broker_name.is_not(None)).distinct()
    if not user.is_superadmin:
        stmt = stmt.where(SparkMember.organization_id == user.organization_id)
    rows = [name for name in db.execute(stmt).scalars().all() if name]
    return _success(rows)


@router.get("/spark/archive/groups")
async def spark_archive_groups(db: DbSession, user: CurrentUser):
    return await groups(db, user)


@router.get("/spark/archive/operators")
async def spark_archive_operators(db: DbSession, user: CurrentUser):
    return await users(db, user, page=1, page_size=500)


@router.get("/fluorescent/groups")
async def fluorescent_groups(db: DbSession, user: CurrentUser):
    return await groups(db, user)


@router.get("/fluorescent/operators")
async def fluorescent_operators(db: DbSession, user: CurrentUser):
    return await users(db, user, page=1, page_size=500)


@router.get("/firefly/income")
async def firefly_income(db: DbSession, user: CurrentUser, page: int = 1, page_size: int | None = None, size: int | None = None, task_name: str | None = None):
    data, total = _income_list(db, user, FireflyIncome, page, page_size, size, task_name)
    return _success(data, total=total)


@router.get("/spark/income")
async def spark_income(db: DbSession, user: CurrentUser, page: int = 1, page_size: int | None = None, size: int | None = None, task_name: str | None = None):
    data, total = _income_list(db, user, SparkIncome, page, page_size, size, task_name)
    return _success(data, total=total)


@router.get("/fluorescent/income")
async def fluorescent_income(db: DbSession, user: CurrentUser, page: int = 1, page_size: int | None = None, size: int | None = None, task_name: str | None = None):
    data, total = _income_list(db, user, FluorescentIncome, page, page_size, size, task_name)
    return _success(data, total=total)


def _income_list(db: Session, user: User, model, page: int, page_size: int | None, size: int | None, task_name: str | None):
    page, per_page = _page_size(page, page_size, size)
    stmt = select(model)
    stmt = _apply_org_scope(stmt, model, user)
    if task_name and hasattr(model, "task_name"):
        stmt = stmt.where(model.task_name.like(f"%{task_name}%"))
    total = _count(db, stmt)
    rows = db.execute(stmt.order_by(model.id.desc()).offset((page - 1) * per_page).limit(per_page)).scalars().all()
    return [_income_payload(row) for row in rows], total


@router.get("/firefly/income/stats")
async def firefly_income_stats(db: DbSession, user: CurrentUser):
    return _success(_sum_income(db, user, FireflyIncome))


@router.get("/spark/income/stats")
async def spark_income_stats(db: DbSession, user: CurrentUser):
    return _success(_sum_income(db, user, SparkIncome))


@router.get("/fluorescent/income/stats")
async def fluorescent_income_stats(db: DbSession, user: CurrentUser):
    return _success(_sum_income(db, user, FluorescentIncome))


def _sum_income(db: Session, user: User, model) -> dict[str, Any]:
    amount_col = getattr(model, "income_amount", getattr(model, "total_amount", None))
    stmt = select(func.count(model.id), func.coalesce(func.sum(amount_col), 0))
    if not user.is_superadmin:
        stmt = stmt.where(model.organization_id == user.organization_id)
    total, amount = db.execute(stmt).one()
    return {
        "total": total,
        "total_amount": amount,
        "total_income": amount,
        "settled_income": 0,
        "unsettled_income": amount,
        "total_members": total,
    }


@router.get("/spark/archive")
async def spark_archive(db: DbSession, user: CurrentUser, page: int = 1, page_size: int | None = None, size: int | None = None):
    page, per_page = _page_size(page, page_size, size)
    stmt = select(IncomeArchive).where(IncomeArchive.program_type == "spark")
    stmt = _apply_org_scope(stmt, IncomeArchive, user)
    total = _count(db, stmt)
    rows = db.execute(stmt.order_by(IncomeArchive.id.desc()).offset((page - 1) * per_page).limit(per_page)).scalars().all()
    return _success([_income_payload(row) for row in rows], total=total)


@router.get("/spark/archive/stats")
async def spark_archive_stats(db: DbSession, user: CurrentUser):
    return _success(_sum_income(db, user, IncomeArchive))


@router.get("/collect-pool/my-permission")
async def collect_pool_permission(user: CurrentUser):
    is_admin = bool(user.is_superadmin)
    return _success(
        {
            "role": "super_admin" if is_admin else user.role,
            "username": user.username,
            "is_super_admin": is_admin,
            "default_auth_code": user.phone or user.username,
            "can_create_auth_code": is_admin,
            "can_change_auth_code": is_admin,
            "can_view_all": is_admin,
            "can_import": is_admin,
            "can_edit": is_admin,
            "can_delete": is_admin,
        }
    )


@router.get("/collect-pool")
async def collect_pool(
    db: DbSession,
    user: CurrentUser,
    page: int = 1,
    page_size: int | None = None,
    size: int | None = None,
    search: str | None = None,
    platform: str | None = None,
    username: str | None = None,
):
    page, per_page = _page_size(page, page_size, size)
    stmt = select(CollectPool).where(CollectPool.deleted_at.is_(None))
    stmt = _apply_org_scope(stmt, CollectPool, user)
    if search:
        like = f"%{search}%"
        stmt = stmt.where(or_(CollectPool.drama_name.like(like), CollectPool.drama_url.like(like)))
    if platform not in (None, ""):
        stmt = stmt.where(CollectPool.platform == platform)
    if username:
        stmt = stmt.where(CollectPool.auth_code == username)
    total = _count(db, stmt)
    rows = db.execute(stmt.order_by(CollectPool.id.desc()).offset((page - 1) * per_page).limit(per_page)).scalars().all()
    return _success([_collect_pool_payload(row) for row in rows], total=total)


@router.get("/collect-pool/stats")
async def collect_pool_stats(db: DbSession, user: CurrentUser):
    stmt = select(CollectPool).where(CollectPool.deleted_at.is_(None))
    stmt = _apply_org_scope(stmt, CollectPool, user)
    total = _count(db, stmt)
    abnormal_stmt = select(CollectPool).where(
        CollectPool.deleted_at.is_(None),
        CollectPool.status != "active",
    )
    abnormal_stmt = _apply_org_scope(abnormal_stmt, CollectPool, user)
    abnormal = _count(db, abnormal_stmt)
    return _success({"total": total, "active": max(total - abnormal, 0), "abnormal": abnormal})


@router.get("/collect-pool/auth-code")
async def collect_pool_auth_code(db: DbSession, user: CurrentUser):
    stmt = select(CollectPoolAuthCode).order_by(CollectPoolAuthCode.id.asc())
    rows = db.execute(stmt).scalars().all()
    return _success([_auth_code_payload(row) for row in rows])


@router.post("/collect-pool")
async def create_collect_pool(request: Request, db: DbSession, user: CurrentUser):
    body = await request.json()
    name = str(body.get("drama_name") or body.get("name") or "").strip()
    url = str(body.get("drama_url") or body.get("url") or "").strip()
    row = CollectPool(
        organization_id=int(body.get("organization_id") or user.organization_id),
        drama_name=name or url or "未命名短剧",
        drama_url=url,
        platform=str(body.get("platform") or "kuaishou"),
        auth_code=body.get("auth_code") or body.get("username") or (user.phone or user.username),
        status=body.get("status") or ("abnormal" if not url else "active"),
        abnormal_reason=body.get("abnormal_reason") or ("url_empty" if not url else None),
        imported_by_user_id=user.id,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return _success(_collect_pool_payload(row))


@router.put("/collect-pool/{row_id}")
async def update_collect_pool(row_id: int, request: Request, db: DbSession):
    row = db.get(CollectPool, row_id)
    if row is None:
        return _success(None, message="短剧不存在")
    body = await request.json()
    row.drama_name = body.get("drama_name") or body.get("name") or row.drama_name
    row.drama_url = body.get("drama_url") or body.get("url") or row.drama_url
    row.platform = str(body.get("platform") or row.platform)
    row.auth_code = body.get("auth_code") or body.get("username") or row.auth_code
    row.status = body.get("status") or row.status
    row.abnormal_reason = body.get("abnormal_reason", row.abnormal_reason)
    db.commit()
    return _success(_collect_pool_payload(row))


@router.delete("/collect-pool/{row_id}")
async def delete_collect_pool(row_id: int, db: DbSession):
    row = db.get(CollectPool, row_id)
    if row:
        row.status = "deleted"
        row.deleted_at = datetime.utcnow()
        db.commit()
    return _success({"deleted": True})


@router.post("/collect-pool/batch-delete")
async def batch_delete_collect_pool(request: Request, db: DbSession):
    body = await request.json()
    ids = [int(item) for item in _body_ids(body) if str(item).isdigit()]
    rows = db.execute(select(CollectPool).where(CollectPool.id.in_(ids))).scalars().all()
    now = datetime.utcnow()
    for row in rows:
        row.status = "deleted"
        row.deleted_at = now
    db.commit()
    return _success({"deleted": len(rows)})


@router.post("/collect-pool/batch-import")
async def batch_import_collect_pool(request: Request, db: DbSession, user: CurrentUser):
    body = await request.json()
    items = body.get("items") or body.get("dramas") or []
    created = 0
    for item in items:
        if isinstance(item, str):
            item = {"drama_url": item}
        url = str(item.get("drama_url") or item.get("url") or "").strip()
        name = str(item.get("drama_name") or item.get("name") or url or "").strip()
        if not url and not name:
            continue
        db.add(
            CollectPool(
                organization_id=int(item.get("organization_id") or body.get("organization_id") or user.organization_id),
                drama_name=name or "未命名短剧",
                drama_url=url,
                platform=str(item.get("platform") or body.get("platform") or "kuaishou"),
                auth_code=item.get("auth_code") or body.get("auth_code") or body.get("username") or user.phone or user.username,
                status="abnormal" if not url else "active",
                abnormal_reason="url_empty" if not url else None,
                imported_by_user_id=user.id,
            )
        )
        created += 1
    db.commit()
    return _success({"created": created})


@router.post("/collect-pool/batch-status")
async def batch_collect_pool_status(request: Request, db: DbSession):
    body = await request.json()
    ids = [int(item) for item in _body_ids(body) if str(item).isdigit()]
    status = body.get("status") or "active"
    rows = db.execute(select(CollectPool).where(CollectPool.id.in_(ids))).scalars().all()
    for row in rows:
        row.status = status
    db.commit()
    return _success({"updated": len(rows), "status": status})


@router.post("/collect-pool/deduplicate-preview")
async def collect_pool_deduplicate_preview(request: Request, db: DbSession, user: CurrentUser):
    body = await request.json()
    target_auth_code = body.get("target_auth_code")
    stmt = select(CollectPool).where(CollectPool.deleted_at.is_(None))
    stmt = _apply_org_scope(stmt, CollectPool, user)
    rows = db.execute(stmt).scalars().all()
    unique_names = {row.drama_name for row in rows if row.drama_name}
    existing_target = {row.drama_name for row in rows if row.auth_code == target_auth_code}
    return _success(
        {
            "total_count": len(rows),
            "deduplicated_count": len(unique_names),
            "existing_count": len(existing_target),
            "will_copy_count": max(len(unique_names - existing_target), 0),
        }
    )


@router.post("/collect-pool/deduplicate-and-copy")
async def collect_pool_deduplicate_and_copy(request: Request, db: DbSession, user: CurrentUser):
    body = await request.json()
    target_auth_code = body.get("target_auth_code")
    if not target_auth_code:
        return _success({"created": 0}, message="目标授权码不能为空")
    stmt = select(CollectPool).where(CollectPool.deleted_at.is_(None))
    stmt = _apply_org_scope(stmt, CollectPool, user)
    rows = db.execute(stmt.order_by(CollectPool.id.desc())).scalars().all()
    seen: set[str] = set()
    target_existing = {(row.drama_name, row.auth_code) for row in rows}
    created = 0
    for row in rows:
        if not row.drama_name or row.drama_name in seen:
            continue
        seen.add(row.drama_name)
        if (row.drama_name, target_auth_code) in target_existing:
            continue
        db.add(
            CollectPool(
                organization_id=row.organization_id,
                drama_name=row.drama_name,
                drama_url=row.drama_url,
                platform=row.platform,
                auth_code=target_auth_code,
                status=row.status,
                abnormal_reason=row.abnormal_reason,
                imported_by_user_id=user.id,
            )
        )
        created += 1
    db.commit()
    return _success({"created": created})


@router.post("/collect-pool/auth-code")
async def create_collect_pool_auth_code(request: Request, db: DbSession, user: CurrentUser):
    body = await request.json()
    auth_code = str(body.get("auth_code") or "").strip()
    if not auth_code:
        return _success(None, message="auth_code is required")
    row = db.execute(
        select(CollectPoolAuthCode).where(CollectPoolAuthCode.auth_code == auth_code)
    ).scalar_one_or_none()
    if row is None:
        row = CollectPoolAuthCode(auth_code=auth_code, created_by_user_id=user.id)
        db.add(row)
    row.name = body.get("name") or row.name or auth_code
    row.is_active = _as_bool(body.get("is_active"), True)
    row.expire_at = _as_datetime(body.get("expire_at"))
    db.commit()
    db.refresh(row)
    return _success(_auth_code_payload(row))


@router.put("/collect-pool/auth-code/{auth_id}")
async def update_collect_pool_auth_code(auth_id: int, request: Request, db: DbSession):
    row = db.get(CollectPoolAuthCode, auth_id)
    if row is None:
        return _success(None, message="auth code not found")
    body = await request.json()
    if body.get("auth_code"):
        row.auth_code = str(body["auth_code"]).strip()
    if "name" in body:
        row.name = body.get("name")
    if "is_active" in body:
        row.is_active = _as_bool(body.get("is_active"), True)
    if "expire_at" in body:
        row.expire_at = _as_datetime(body.get("expire_at"))
    db.commit()
    return _success(_auth_code_payload(row))


@router.delete("/collect-pool/auth-code/{auth_id}")
async def delete_collect_pool_auth_code(auth_id: int, db: DbSession):
    row = db.get(CollectPoolAuthCode, auth_id)
    if row:
        db.delete(row)
        db.commit()
    return _success({"deleted": True, "id": auth_id})


@router.get("/high-income-dramas")
async def high_income_dramas(
    db: DbSession,
    user: CurrentUser,
    page: int = 1,
    pageSize: int | None = None,
    page_size: int | None = None,
    size: int | None = None,
    keyword: str | None = None,
):
    page, per_page = _page_size(page, page_size or pageSize, size)
    stmt = select(HighIncomeDrama)
    stmt = _apply_org_scope(stmt, HighIncomeDrama, user)
    if keyword:
        stmt = stmt.where(HighIncomeDrama.drama_name.like(f"%{keyword}%"))
    total = _count(db, stmt)
    rows = db.execute(stmt.order_by(HighIncomeDrama.id.desc()).offset((page - 1) * per_page).limit(per_page)).scalars().all()
    return _success({"list": [_high_income_payload(row) for row in rows], "total": total})


@router.post("/high-income-dramas")
async def create_high_income_drama(request: Request, db: DbSession, user: CurrentUser):
    body = await request.json()
    names = body.get("task_names") or body.get("drama_names") or body.get("items")
    if names is None:
        names = [body.get("drama_name") or body.get("name")]
    if isinstance(names, str):
        names = [names]
    created = 0
    for name in names:
        if isinstance(name, dict):
            payload = name
            name = payload.get("drama_name") or payload.get("name")
        else:
            payload = {}
        name = str(name or "").strip()
        if not name:
            continue
        existing = db.execute(
            select(HighIncomeDrama).where(
                HighIncomeDrama.organization_id == int(payload.get("organization_id") or body.get("organization_id") or user.organization_id),
                HighIncomeDrama.drama_name == name,
            )
        ).scalar_one_or_none()
        if existing:
            continue
        db.add(
            HighIncomeDrama(
                organization_id=int(payload.get("organization_id") or body.get("organization_id") or user.organization_id),
                drama_name=name,
                source_program=payload.get("source_program") or body.get("source_program") or "manual",
                income_amount=payload.get("income_amount") or body.get("income_amount"),
                notes=payload.get("notes") or body.get("notes"),
                added_by_user_id=user.id,
            )
        )
        created += 1
    db.commit()
    return _success({"created": created})


@router.delete("/high-income-dramas/{row_id}")
async def delete_high_income_drama(row_id: int, db: DbSession):
    row = db.get(HighIncomeDrama, row_id)
    if row:
        db.delete(row)
        db.commit()
    return _success({"deleted": True})


@router.post("/high-income-dramas/batch-delete")
async def batch_delete_high_income_dramas(request: Request, db: DbSession):
    body = await request.json()
    ids = [int(item) for item in _body_ids(body) if str(item).isdigit()]
    rows = db.execute(select(HighIncomeDrama).where(HighIncomeDrama.id.in_(ids))).scalars().all()
    for row in rows:
        db.delete(row)
    db.commit()
    return _success({"deleted": len(rows)})


@router.get("/high-income-dramas/links")
async def high_income_drama_links(title: str | None = None):
    return _success([])


@router.delete("/high-income-dramas/links/{row_id}")
async def delete_high_income_drama_link(row_id: int):
    return _success({"deleted": True, "id": row_id})


@router.get("/statistics/drama-links")
async def statistics_drama_links(
    db: DbSession,
    user: CurrentUser,
    page: int = 1,
    page_size: int | None = None,
    size: int | None = None,
    search: str | None = None,
    export: bool = False,
):
    page, per_page = _page_size(page, page_size, size)
    if export:
        per_page = 10000
    stmt = select(DramaLinkStatistic)
    stmt = _apply_org_scope(stmt, DramaLinkStatistic, user)
    if search:
        like = f"%{search}%"
        stmt = stmt.where(or_(DramaLinkStatistic.drama_name.like(like), DramaLinkStatistic.drama_url.like(like)))
    total = _count(db, stmt)
    rows = db.execute(stmt.order_by(DramaLinkStatistic.execute_count.desc()).offset((page - 1) * per_page).limit(per_page)).scalars().all()
    summary = {
        "total_count": total,
        "execute_count": sum(row.execute_count for row in rows),
        "success_count": sum(row.success_count for row in rows),
        "failed_count": sum(row.failed_count for row in rows),
    }
    return _success({"list": [_drama_link_payload(row) for row in rows], "summary": summary, "total": total})


@router.get("/collections/accounts")
async def collection_accounts(db: DbSession, user: CurrentUser):
    stmt = select(DramaCollectionRecord)
    stmt = _apply_org_scope(stmt, DramaCollectionRecord, user)
    rows = db.execute(stmt.order_by(DramaCollectionRecord.total_count.desc()).limit(1000)).scalars().all()
    return _success([_drama_collection_payload(row) for row in rows])


@router.get("/collections/stats/overview")
async def collection_stats(db: DbSession, user: CurrentUser):
    stmt = select(DramaCollectionRecord)
    stmt = _apply_org_scope(stmt, DramaCollectionRecord, user)
    rows = db.execute(stmt).scalars().all()
    return _success(
        {
            "total_accounts": len(rows),
            "total_count": sum(row.total_count for row in rows),
            "spark_count": sum(row.spark_count for row in rows),
            "firefly_count": sum(row.firefly_count for row in rows),
            "fluorescent_count": sum(row.fluorescent_count for row in rows),
        }
    )


@router.get("/statistics/external-urls")
async def statistics_external_urls(
    db: DbSession,
    user: CurrentUser,
    page: int = 1,
    page_size: int | None = None,
    size: int | None = None,
    search: str | None = None,
):
    page, per_page = _page_size(page, page_size, size)
    stmt = select(ExternalUrlStat)
    if not user.is_superadmin:
        stmt = stmt.where(or_(ExternalUrlStat.organization_id.is_(None), ExternalUrlStat.organization_id == user.organization_id))
    if search:
        stmt = stmt.where(ExternalUrlStat.url.like(f"%{search}%"))
    total = _count(db, stmt)
    rows = db.execute(stmt.order_by(ExternalUrlStat.reference_count.desc()).offset((page - 1) * per_page).limit(per_page)).scalars().all()
    summary = {"total": total, "url_count": sum(row.reference_count for row in rows)}
    return _success({"list": [_external_url_payload(row) for row in rows], "summary": summary, "total": total})


@router.get("/cloud-cookies")
async def cloud_cookies(db: DbSession, user: CurrentUser, page: int = 1, page_size: int | None = None, size: int | None = None):
    page, per_page = _page_size(page, page_size, size)
    stmt = select(CloudCookieAccount)
    stmt = _apply_org_scope(stmt, CloudCookieAccount, user)
    total = _count(db, stmt)
    rows = db.execute(stmt.order_by(CloudCookieAccount.id.desc()).offset((page - 1) * per_page).limit(per_page)).scalars().all()
    data = [
        {
            "id": row.id,
            "uid": row.uid,
            "nickname": row.nickname,
            "owner_code": row.owner_code,
            "login_status": row.login_status,
            "cookies": row.cookie_preview,
            "created_at": _dt(row.created_at),
        }
        for row in rows
    ]
    return _success(data, pagination={"total": total, "page": page, "page_size": per_page})


@router.get("/cloud-cookies/owner-codes")
async def cloud_cookie_owner_codes(db: DbSession):
    rows = db.execute(select(CloudCookieAccount.owner_code).where(CloudCookieAccount.owner_code.is_not(None)).distinct()).scalars().all()
    return _success(rows)


@router.get("/cxt-user")
async def cxt_users(db: DbSession, user: CurrentUser, page: int = 1, page_size: int | None = None, size: int | None = None, search: str | None = None, status: str | None = None):
    page, per_page = _page_size(page, page_size, size)
    stmt = select(CxtUser)
    if search:
        like = f"%{search}%"
        stmt = stmt.where(or_(CxtUser.platform_uid.like(like), CxtUser.username.like(like), CxtUser.note.like(like)))
    if status not in (None, ""):
        stmt = stmt.where(CxtUser.status == str(status))
    total = _count(db, stmt)
    rows = db.execute(stmt.order_by(CxtUser.id.desc()).offset((page - 1) * per_page).limit(per_page)).scalars().all()
    data = [
        {
            "id": row.id,
            "uid": row.platform_uid,
            "sec_user_id": row.platform_uid,
            "nickname": row.username,
            "auth_code": row.auth_code,
            "status": row.status,
            "note": row.note,
            "created_at": _dt(row.created_at),
        }
        for row in rows
    ]
    return _success({"list": data, "total": total})


@router.post("/cxt-user/batch")
async def batch_create_cxt_users(request: Request, db: DbSession, user: CurrentUser):
    body = await request.json()
    items = body.get("items") or []
    auth_code = body.get("auth_code")
    created = 0
    updated = 0
    for item in items:
        if isinstance(item, str):
            item = {"uid": item}
        uid = str(item.get("uid") or item.get("platform_uid") or item.get("sec_user_id") or "").strip()
        if not uid:
            continue
        existing = db.execute(
            select(CxtUser).where(CxtUser.organization_id == user.organization_id, CxtUser.platform_uid == uid)
        ).scalar_one_or_none()
        if existing:
            existing.username = item.get("nickname") or item.get("username") or existing.username
            existing.auth_code = item.get("auth_code") or auth_code or existing.auth_code
            existing.note = item.get("note", existing.note)
            existing.status = item.get("status") or existing.status
            updated += 1
        else:
            db.add(
                CxtUser(
                    organization_id=user.organization_id,
                    platform_uid=uid,
                    username=item.get("nickname") or item.get("username"),
                    auth_code=item.get("auth_code") or auth_code,
                    note=item.get("note"),
                    status=item.get("status") or "active",
                )
            )
            created += 1
    db.commit()
    return _success({"created": created, "updated": updated})


@router.put("/cxt-user/batch-status")
async def batch_update_cxt_user_status(request: Request, db: DbSession):
    body = await request.json()
    ids = [int(item) for item in _body_ids(body) if str(item).isdigit()]
    status = body.get("status") or "active"
    note = body.get("note")
    rows = db.execute(select(CxtUser).where(CxtUser.id.in_(ids))).scalars().all()
    for row in rows:
        row.status = status
        if note is not None:
            row.note = note
    db.commit()
    return _success({"updated": len(rows)})


@router.delete("/cxt-user/batch")
async def batch_delete_cxt_users(request: Request, db: DbSession):
    body = await request.json()
    ids = [int(item) for item in _body_ids(body) if str(item).isdigit()]
    rows = db.execute(select(CxtUser).where(CxtUser.id.in_(ids))).scalars().all()
    for row in rows:
        db.delete(row)
    db.commit()
    return _success({"deleted": len(rows)})


@router.put("/cxt-user/batch-status-by-uid")
async def batch_update_cxt_user_status_by_uid(request: Request, db: DbSession):
    body = await request.json()
    uids = [str(item) for item in body.get("uids", [])]
    status = body.get("status") or "active"
    rows = db.execute(select(CxtUser).where(CxtUser.platform_uid.in_(uids))).scalars().all()
    for row in rows:
        row.status = status
        if body.get("note") is not None:
            row.note = body.get("note")
    db.commit()
    return _success({"updated": len(rows)})


@router.delete("/cxt-user/batch-by-uid")
async def batch_delete_cxt_users_by_uid(request: Request, db: DbSession):
    body = await request.json()
    uids = [str(item) for item in body.get("uids", [])]
    rows = db.execute(select(CxtUser).where(CxtUser.platform_uid.in_(uids))).scalars().all()
    for row in rows:
        db.delete(row)
    db.commit()
    return _success({"deleted": len(rows)})


@router.get("/cxt-videos")
async def cxt_videos(db: DbSession, user: CurrentUser, page: int = 1, page_size: int | None = None, size: int | None = None, title: str | None = None, author: str | None = None, aweme_id: str | None = None):
    page, per_page = _page_size(page, page_size, size)
    stmt = select(CxtVideo)
    if title:
        stmt = stmt.where(CxtVideo.title.like(f"%{title}%"))
    if author:
        stmt = stmt.where(CxtVideo.author.like(f"%{author}%"))
    if aweme_id:
        stmt = stmt.where(CxtVideo.aweme_id.like(f"%{aweme_id}%"))
    total = _count(db, stmt)
    rows = db.execute(stmt.order_by(CxtVideo.id.desc()).offset((page - 1) * per_page).limit(per_page)).scalars().all()
    data = [
        {
            "id": row.id,
            "title": row.title,
            "author": row.author,
            "sec_user_id": row.sec_user_id,
            "aweme_id": row.aweme_id,
            "duration": row.duration,
            "play_count": row.play_count,
            "digg_count": row.digg_count,
            "comment_count": row.comment_count,
            "collect_count": row.collect_count,
            "share_count": row.share_count,
            "recommend_count": row.recommend_count,
            "created_at": _dt(row.created_at),
        }
        for row in rows
    ]
    stats = {
        "totalCount": total,
        "totalPlay": sum(row.play_count or 0 for row in rows),
        "totalDigg": sum(row.digg_count or 0 for row in rows),
        "totalComment": sum(row.comment_count or 0 for row in rows),
    }
    return _success({"list": data, "total": total, "stats": stats})


@router.post("/cxt-videos/batch-import")
async def batch_import_cxt_videos(request: Request, db: DbSession, user: CurrentUser):
    body = await request.json()
    items = body.get("items") or []
    created = 0
    updated = 0
    for item in items:
        aweme_id = str(item.get("aweme_id") or "").strip()
        platform = item.get("platform") or "unknown"
        existing = None
        if aweme_id:
            existing = db.execute(
                select(CxtVideo).where(CxtVideo.platform == platform, CxtVideo.aweme_id == aweme_id)
            ).scalar_one_or_none()
        payload = {
            "organization_id": user.organization_id,
            "title": item.get("title"),
            "author": item.get("author"),
            "sec_user_id": item.get("sec_user_id"),
            "aweme_id": aweme_id or None,
            "description": item.get("description"),
            "video_url": item.get("video_url"),
            "cover_url": item.get("cover_url"),
            "duration": item.get("duration"),
            "comment_count": int(item.get("comment_count") or 0),
            "collect_count": int(item.get("collect_count") or 0),
            "recommend_count": int(item.get("recommend_count") or 0),
            "share_count": int(item.get("share_count") or 0),
            "play_count": int(item.get("play_count") or 0),
            "digg_count": int(item.get("digg_count") or 0),
            "platform": platform,
            "status": item.get("status") or "active",
        }
        if existing:
            for key, value in payload.items():
                setattr(existing, key, value)
            updated += 1
        else:
            db.add(CxtVideo(**payload))
            created += 1
    db.commit()
    return _success({"created": created, "updated": updated})


@router.delete("/cxt-videos/batch")
async def batch_delete_cxt_videos(request: Request, db: DbSession):
    body = await request.json()
    ids = [int(item) for item in _body_ids(body) if str(item).isdigit()]
    rows = db.execute(select(CxtVideo).where(CxtVideo.id.in_(ids))).scalars().all()
    for row in rows:
        db.delete(row)
    db.commit()
    return _success({"deleted": len(rows)})


@router.delete("/cxt-videos/batch-by-aweme-ids")
async def batch_delete_cxt_videos_by_aweme(request: Request, db: DbSession):
    body = await request.json()
    aweme_ids = [str(item) for item in body.get("aweme_ids", [])]
    rows = db.execute(select(CxtVideo).where(CxtVideo.aweme_id.in_(aweme_ids))).scalars().all()
    for row in rows:
        db.delete(row)
    db.commit()
    return _success({"deleted": len(rows)})


@router.get("/cxt-videos/{video_id}")
async def cxt_video_detail(video_id: int, db: DbSession, user: CurrentUser):
    row = db.get(CxtVideo, video_id)
    return _success({} if row is None else {
        "id": row.id,
        "title": row.title,
        "author": row.author,
        "sec_user_id": row.sec_user_id,
        "aweme_id": row.aweme_id,
        "video_url": row.video_url,
        "cover_url": row.cover_url,
        "created_at": _dt(row.created_at),
    })


@router.put("/cxt-videos/{video_id}")
async def update_cxt_video(video_id: int, request: Request, db: DbSession):
    row = db.get(CxtVideo, video_id)
    if row is None:
        return _success(None, message="剧集不存在")
    body = await request.json()
    for key in [
        "title", "author", "sec_user_id", "aweme_id", "description", "video_url",
        "cover_url", "duration", "comment_count", "collect_count", "recommend_count",
        "share_count", "play_count", "digg_count", "platform", "status",
    ]:
        if key in body:
            setattr(row, key, body[key])
    db.commit()
    return _success({"updated": True})


@router.get("/announcements/active")
async def active_announcements(db: DbSession, user: CurrentUser):
    now = datetime.utcnow()
    stmt = (
        select(Announcement)
        .where(Announcement.active.is_(True))
        .where(or_(Announcement.organization_id.is_(None), Announcement.organization_id == user.organization_id))
        .where(or_(Announcement.start_at.is_(None), Announcement.start_at <= now))
        .where(or_(Announcement.end_at.is_(None), Announcement.end_at >= now))
        .order_by(Announcement.pinned.desc(), Announcement.id.desc())
        .limit(5)
    )
    rows = db.execute(stmt).scalars().all()
    data = [
        {
            "id": row.id,
            "title": row.title,
            "content": row.content,
            "level": row.level,
            "pinned": row.pinned,
            "active": row.active,
            "created_at": _dt(row.created_at),
        }
        for row in rows
    ]
    return _success(data)


@router.get("/announcements")
async def announcements(
    db: DbSession,
    user: CurrentUser,
    page: int = 1,
    page_size: int | None = None,
    size: int | None = None,
    platform: str | None = None,
):
    page, per_page = _page_size(page, page_size, size)
    stmt = select(Announcement).order_by(Announcement.pinned.desc(), Announcement.id.desc())
    if not user.is_superadmin:
        stmt = stmt.where(or_(Announcement.organization_id.is_(None), Announcement.organization_id == user.organization_id))
    total = _count(db, stmt)
    rows = db.execute(stmt.offset((page - 1) * per_page).limit(per_page)).scalars().all()
    data = [_announcement_payload(row) for row in rows]
    return _success({"announcements": data, "total": total}, total=total)


@router.post("/announcements")
async def create_announcement(request: Request, db: DbSession, user: CurrentUser):
    body = await request.json()
    row = Announcement(
        organization_id=body.get("organization_id"),
        title=str(body.get("title") or "").strip() or "Untitled",
        content=str(body.get("content") or ""),
        level="warning" if _as_int(body.get("priority")) > 0 else body.get("level") or "info",
        pinned=_as_int(body.get("priority")) > 0 or _as_bool(body.get("pinned")),
        active=_as_bool(body.get("is_enabled"), True),
        start_at=_as_datetime(body.get("start_at")),
        end_at=_as_datetime(body.get("end_at")),
        created_by_user_id=user.id,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return _success(_announcement_payload(row))


@router.put("/announcements/{announcement_id}")
async def update_announcement(announcement_id: int, request: Request, db: DbSession):
    row = db.get(Announcement, announcement_id)
    if row is None:
        return _success(None, message="announcement not found")
    body = await request.json()
    if "title" in body:
        row.title = str(body.get("title") or row.title).strip()
    if "content" in body:
        row.content = str(body.get("content") or "")
    if "level" in body or "priority" in body:
        row.level = body.get("level") or ("warning" if _as_int(body.get("priority")) > 0 else "info")
    if "priority" in body or "pinned" in body:
        row.pinned = _as_int(body.get("priority")) > 0 or _as_bool(body.get("pinned"))
    if "is_enabled" in body or "active" in body:
        row.active = _as_bool(body.get("is_enabled", body.get("active")), True)
    if "start_at" in body:
        row.start_at = _as_datetime(body.get("start_at"))
    if "end_at" in body:
        row.end_at = _as_datetime(body.get("end_at"))
    db.commit()
    return _success(_announcement_payload(row))


@router.put("/announcements/{announcement_id}/toggle")
async def toggle_announcement(announcement_id: int, db: DbSession):
    row = db.get(Announcement, announcement_id)
    if row is None:
        return _success(None, message="announcement not found")
    row.active = not row.active
    db.commit()
    return _success(_announcement_payload(row))


@router.delete("/announcements/{announcement_id}")
async def delete_announcement_compat(announcement_id: int, db: DbSession):
    row = db.get(Announcement, announcement_id)
    if row:
        db.delete(row)
        db.commit()
    return _success({"deleted": True})


@router.post("/announcements/upload")
async def upload_announcement_files(request: Request):
    form = await request.form()
    upload_root = Path("/var/www/ksjuzheng/uploads/announcements")
    if not upload_root.parent.parent.exists():
        upload_root = Path("data/uploads/announcements")
    upload_root.mkdir(parents=True, exist_ok=True)
    uploaded: list[dict[str, Any]] = []
    for item in form.getlist("files"):
        filename = getattr(item, "filename", None)
        if not filename:
            continue
        safe_name = f"{uuid4().hex}_{Path(filename).name}"
        target = upload_root / safe_name
        content = await item.read()
        target.write_bytes(content)
        uploaded.append(
            {
                "filename": safe_name,
                "originalName": filename,
                "size": len(content),
                "url": f"/uploads/announcements/{safe_name}",
            }
        )
    return _success(uploaded)


@router.delete("/announcements/files/{file_id}")
async def delete_announcement_file(file_id: str):
    for root in (Path("/var/www/ksjuzheng/uploads/announcements"), Path("data/uploads/announcements")):
        target = root / Path(file_id).name
        if target.exists() and target.is_file():
            target.unlink()
            return _success({"deleted": True})
    return _success({"deleted": False})


@router.put("/auth/profile")
async def update_profile(request: Request, db: DbSession, user: CurrentUser):
    body = await request.json()
    if "nickname" in body or "display_name" in body:
        user.display_name = body.get("nickname") or body.get("display_name") or user.display_name
    if "email" in body:
        user.email = body.get("email")
    if "phone" in body:
        user.phone = body.get("phone")
    db.commit()
    return _success(_user_payload(user))


@router.post("/auth/change-password")
async def change_password(request: Request, db: DbSession, user: CurrentUser):
    body = await request.json()
    old_password = body.get("old_password") or body.get("current_password")
    new_password = body.get("new_password") or body.get("password")
    if old_password and not verify_password(str(old_password), user.password_hash):
        return _success({"changed": False}, message="current password is invalid")
    if not new_password:
        return _success({"changed": False}, message="new password is required")
    user.password_hash = hash_password(str(new_password))
    db.commit()
    return _success({"changed": True})


@router.put("/auth/my-alipay")
async def update_my_alipay(request: Request, db: DbSession, user: CurrentUser):
    body = await request.json()
    row = db.execute(select(WalletProfile).where(WalletProfile.user_id == user.id)).scalar_one_or_none()
    if row is None:
        row = WalletProfile(user_id=user.id)
        db.add(row)
    row.alipay_name = body.get("alipay_name", row.alipay_name)
    row.alipay_account = body.get("alipay_account", row.alipay_account)
    row.bank_name = body.get("bank_name", row.bank_name)
    row.bank_account = body.get("bank_account", row.bank_account)
    row.real_name = body.get("real_name", row.real_name)
    row.notes = body.get("notes", row.notes)
    db.commit()
    return _success({"updated": True})


@router.get("/auth/my-auth-code")
async def my_auth_code(user: CurrentUser):
    return _success({"auth_code": user.phone or user.username, "source": "user.phone_or_username"})


@router.put("/auth/my-skin")
async def update_my_skin(request: Request):
    body = await request.json()
    return _success({"skin": body.get("skin") or body.get("theme")})


@router.post("/auth/my-logo")
async def upload_my_logo(request: Request):
    return await upload_announcement_files(request)


@router.put("/auth/toggle-member-query")
async def toggle_member_query(request: Request, user: CurrentUser):
    body = await request.json()
    return _success({"user_id": user.id, "allow": _as_bool(body.get("allow"), True)})


@router.get("/auth/auth-codes-status")
async def auth_codes_status(db: DbSession):
    total = _count(db, select(CollectPoolAuthCode))
    active = _count(db, select(CollectPoolAuthCode).where(CollectPoolAuthCode.is_active.is_(True)))
    return _success({"total": total, "active": active, "inactive": max(total - active, 0)})


@router.post("/auth/supplement-auth-codes")
async def supplement_auth_codes(db: DbSession):
    created = 0
    users_without_codes = db.execute(select(User).where(User.deleted_at.is_(None))).scalars().all()
    existing = set(db.execute(select(CollectPoolAuthCode.auth_code)).scalars().all())
    for row in users_without_codes:
        code = (row.phone or row.username or "").strip()
        if not code or code in existing:
            continue
        db.add(CollectPoolAuthCode(auth_code=code, name=row.display_name or row.username, created_by_user_id=row.id))
        existing.add(code)
        created += 1
    db.commit()
    return _success({"created": created})


@router.post("/auth/users/{target_user_id}/logo")
async def upload_user_logo(target_user_id: int, request: Request):
    data = await upload_announcement_files(request)
    data["data"] = {"user_id": target_user_id, "files": data.get("data", [])}
    return data


@router.delete("/auth/users/{target_user_id}/logo")
async def delete_user_logo(target_user_id: int):
    return _success({"user_id": target_user_id, "deleted": True})


@router.post("/auth/users/{target_user_id}/badge-icon")
async def upload_user_badge_icon(target_user_id: int, request: Request):
    data = await upload_announcement_files(request)
    data["data"] = {"user_id": target_user_id, "files": data.get("data", [])}
    return data


@router.delete("/auth/users/{target_user_id}/badge-icon")
async def delete_user_badge_icon(target_user_id: int):
    return _success({"user_id": target_user_id, "deleted": True})


@router.get("/bindings")
async def bindings(
    db: DbSession,
    user: CurrentUser,
    page: int = 1,
    page_size: int | None = None,
    size: int | None = None,
    operator_account: str | None = None,
    status: str | None = None,
    search: str | None = None,
):
    page, per_page = _page_size(page, page_size, size)
    stmt = select(KuaishouAccountBinding)
    if operator_account:
        stmt = stmt.where(KuaishouAccountBinding.operator_account == operator_account)
    if status:
        stmt = stmt.where(KuaishouAccountBinding.status == status)
    if search:
        like = f"%{search}%"
        stmt = stmt.where(or_(KuaishouAccountBinding.kuaishou_id.like(like), KuaishouAccountBinding.machine_id.like(like), KuaishouAccountBinding.operator_account.like(like)))
    total = _count(db, stmt)
    rows = db.execute(stmt.order_by(KuaishouAccountBinding.id.desc()).offset((page - 1) * per_page).limit(per_page)).scalars().all()
    return _success({"list": [_binding_payload(row) for row in rows], "total": total}, total=total)


@router.get("/bindings/operators")
async def bindings_operators(db: DbSession, user: CurrentUser):
    rows = db.execute(
        select(KuaishouAccountBinding.operator_account, func.count(KuaishouAccountBinding.id))
        .group_by(KuaishouAccountBinding.operator_account)
        .order_by(KuaishouAccountBinding.operator_account.asc())
    ).all()
    return _success([{"operator_account": name, "username": name, "binding_count": count} for name, count in rows])


@router.get("/bindings/operator/{operator_id}")
async def operator_bindings(operator_id: str, db: DbSession, user: CurrentUser):
    target = db.get(User, _as_int(operator_id, -1))
    operator_account = target.username if target else operator_id
    rows = db.execute(
        select(KuaishouAccountBinding).where(KuaishouAccountBinding.operator_account == operator_account)
    ).scalars().all()
    return _success([_binding_payload(row) for row in rows])


@router.get("/bindings/stats")
async def binding_stats(db: DbSession):
    total = _count(db, select(KuaishouAccountBinding))
    active = _count(db, select(KuaishouAccountBinding).where(KuaishouAccountBinding.status == "active"))
    return _success({"total": total, "active": active, "disabled": max(total - active, 0)})


@router.put("/bindings/quota/{user_id}")
async def set_binding_quota(user_id: int, request: Request, db: DbSession):
    target = db.get(User, user_id)
    if target is None:
        return _success(None, message="user not found")
    body = await request.json()
    target.account_quota = None if _as_int(body.get("max_accounts"), -1) < 0 else _as_int(body.get("max_accounts"))
    db.commit()
    return _success(_user_payload(target))


@router.post("/bindings/{binding_id}/disable")
async def disable_binding(binding_id: int, db: DbSession):
    row = db.get(KuaishouAccountBinding, binding_id)
    if row:
        row.status = "disabled"
        db.commit()
    return _success({"id": binding_id, "status": "disabled"})


@router.post("/bindings/{binding_id}/enable")
async def enable_binding(binding_id: int, db: DbSession):
    row = db.get(KuaishouAccountBinding, binding_id)
    if row:
        row.status = "active"
        db.commit()
    return _success({"id": binding_id, "status": "active"})


@router.delete("/bindings/{binding_id}")
async def delete_binding(binding_id: int, db: DbSession):
    row = db.get(KuaishouAccountBinding, binding_id)
    if row:
        db.delete(row)
        db.commit()
    return _success({"deleted": True})


@router.get("/org-members/stats")
async def org_member_stats(db: DbSession, user: CurrentUser):
    stmt = select(OrgMember)
    stmt = _apply_org_scope(stmt, OrgMember, user)
    rows = db.execute(stmt).scalars().all()
    active = sum(1 for row in rows if row.renewal_status == "active")
    return _success({"total": len(rows), "active": active, "pending": max(len(rows) - active, 0)})


@router.post("/org-members")
async def create_org_member(request: Request, db: DbSession, user: CurrentUser):
    body = await request.json()
    member_id = _as_int(body.get("member_id") or body.get("uid"))
    row = OrgMember(
        organization_id=_as_int(body.get("organization_id"), user.organization_id),
        member_id=member_id,
        nickname=body.get("nickname") or body.get("member_name"),
        avatar=body.get("avatar"),
        fans_count=_as_int(body.get("fans_count")),
        broker_name=body.get("broker_name"),
        cooperation_type=body.get("cooperation_type") or body.get("agreement_type"),
        content_category=body.get("content_category"),
        mcn_level=body.get("mcn_level"),
        renewal_status=body.get("renewal_status") or body.get("contract_renew_status"),
        contract_expires_at=_as_date(body.get("contract_expires_at")),
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return _success(_org_member_payload(row))


@router.put("/org-members/{member_row_id}")
async def update_org_member(member_row_id: int, request: Request, db: DbSession):
    row = db.get(OrgMember, member_row_id)
    if row is None:
        return _success(None, message="member not found")
    body = await request.json()
    for field in ["nickname", "avatar", "broker_name", "cooperation_type", "content_category", "mcn_level", "renewal_status"]:
        if field in body:
            setattr(row, field, body[field])
    if "member_name" in body:
        row.nickname = body.get("member_name")
    if "fans_count" in body:
        row.fans_count = _as_int(body.get("fans_count"))
    if "contract_expires_at" in body:
        row.contract_expires_at = _as_date(body.get("contract_expires_at"))
    db.commit()
    return _success(_org_member_payload(row))


@router.delete("/org-members/{member_row_id}")
async def delete_org_member(member_row_id: int, db: DbSession):
    row = db.get(OrgMember, member_row_id)
    if row:
        db.delete(row)
        db.commit()
    return _success({"deleted": True})


@router.get("/statistics/account")
async def account_stats(uid: str, db: DbSession, user: CurrentUser):
    account = db.execute(
        select(Account).where(or_(Account.kuaishou_id == uid, Account.real_uid == uid, Account.id == _as_int(uid, -1)))
    ).scalar_one_or_none()
    if account is None:
        return _success({"uid": uid, "total": 0, "success": 0, "failed": 0, "tasks": []})
    rows = db.execute(
        select(AccountTaskRecord).where(AccountTaskRecord.account_id == account.id).order_by(AccountTaskRecord.id.desc()).limit(200)
    ).scalars().all()
    success_count = sum(1 for row in rows if row.success)
    return _success(
        {
            "uid": uid,
            "account": _account_payload(account),
            "total": len(rows),
            "success": success_count,
            "failed": max(len(rows) - success_count, 0),
            "tasks": [
                {
                    "id": row.id,
                    "task_type": row.task_type,
                    "drama_name": row.drama_name,
                    "success": 1 if row.success else 0,
                    "error_message": row.error_message,
                    "created_at": _dt(row.created_at),
                }
                for row in rows
            ],
        }
    )


@router.post("/mcn/verify")
async def verify_mcn(request: Request, db: DbSession, user: CurrentUser):
    body = await request.json()
    uid = str(body.get("uid") or body.get("kuaishou_id") or "").strip()
    account = db.execute(select(Account).where(or_(Account.kuaishou_id == uid, Account.real_uid == uid))).scalar_one_or_none()
    is_member = bool(account and account.mcn_status in {"authorized", "signed", "success", "active", "1"})
    return _success({"uid": uid, "is_mcn_member": 1 if is_member else 0, "account": _account_payload(account) if account else None})


@router.delete("/collections/{collection_id}")
async def delete_collection(collection_id: int, db: DbSession):
    row = db.get(DramaCollectionRecord, collection_id)
    if row:
        db.delete(row)
        db.commit()
    return _success({"deleted": True})


@router.get("/collections/{collection_id}")
async def collection_detail(collection_id: int, db: DbSession):
    row = db.get(DramaCollectionRecord, collection_id)
    return _success({} if row is None else _drama_collection_payload(row))


@router.post("/collections/batch-delete")
async def batch_delete_collections(request: Request, db: DbSession):
    body = await request.json()
    ids = [int(item) for item in _body_ids(body) if str(item).isdigit()]
    rows = db.execute(select(DramaCollectionRecord).where(DramaCollectionRecord.id.in_(ids))).scalars().all()
    for row in rows:
        db.delete(row)
    db.commit()
    return _success({"deleted": len(rows)})


@router.delete("/statistics/drama-links")
async def delete_drama_links(request: Request, db: DbSession):
    body = await request.json()
    ids = [int(item) for item in _body_ids(body) if str(item).isdigit()]
    rows = db.execute(select(DramaLinkStatistic).where(DramaLinkStatistic.id.in_(ids))).scalars().all()
    for row in rows:
        db.delete(row)
    db.commit()
    return _success({"deleted": len(rows)})


@router.delete("/statistics/external-urls")
async def delete_external_urls(request: Request, db: DbSession):
    body = await request.json()
    ids = [int(item) for item in _body_ids(body) if str(item).isdigit()]
    rows = db.execute(select(ExternalUrlStat).where(ExternalUrlStat.id.in_(ids))).scalars().all()
    for row in rows:
        db.delete(row)
    db.commit()
    return _success({"deleted": len(rows)})


@router.post("/fluorescent/add-to-high-income")
async def add_fluorescent_to_high_income(request: Request, db: DbSession, user: CurrentUser):
    body = await request.json()
    names = body.get("task_names") or body.get("drama_names") or []
    created = 0
    for name in names:
        name = str(name or "").strip()
        if not name:
            continue
        exists = db.execute(
            select(HighIncomeDrama).where(HighIncomeDrama.organization_id == user.organization_id, HighIncomeDrama.drama_name == name)
        ).scalar_one_or_none()
        if exists:
            continue
        db.add(HighIncomeDrama(organization_id=user.organization_id, drama_name=name, source_program="fluorescent", added_by_user_id=user.id))
        created += 1
    db.commit()
    return _success({"created": created})


def _external_not_connected(name: str) -> dict[str, Any]:
    return _success({"external_connected": False, "imported_count": 0, "source": name}, message="external kuaishou link is not connected; no fake result was written")


@router.post("/firefly-external/income")
async def firefly_external_income():
    return _external_not_connected("firefly_external_income")


@router.post("/spark-external/income")
async def spark_external_income():
    return _external_not_connected("spark_external_income")


@router.post("/spark-external/photos")
async def spark_external_photos():
    return _external_not_connected("spark_external_photos")


@router.post("/spark-external/violation-photos")
async def spark_external_violation_photos():
    return _external_not_connected("spark_external_violation_photos")


def _income_stats_by_role(db: Session, user: User, model) -> dict[str, Any]:
    stmt = select(model)
    stmt = _apply_org_scope(stmt, model, user)
    rows = db.execute(stmt).scalars().all()
    total_amount = sum(float(getattr(row, "income_amount", getattr(row, "total_amount", 0)) or 0) for row in rows)
    return {"total": len(rows), "total_amount": total_amount, "items": [{"role": _role_value(user), "total": len(rows), "total_amount": total_amount}]}


def _income_operators_summary(db: Session, user: User, model) -> dict[str, Any]:
    rows = db.execute(select(model)).scalars().all() if user.is_superadmin else db.execute(select(model).where(model.organization_id == user.organization_id)).scalars().all()
    return {"operators": [], "total": len(rows), "total_amount": sum(float(getattr(row, "income_amount", getattr(row, "total_amount", 0)) or 0) for row in rows)}


def _income_wallet_stats(db: Session, user: User, model) -> dict[str, Any]:
    base = _sum_income(db, user, model)
    wallets = _count(db, select(WalletProfile))
    base.update({"wallet_count": wallets, "missing_wallet_count": 0})
    return base


@router.get("/firefly/income/stats/by-role")
async def firefly_income_stats_by_role(db: DbSession, user: CurrentUser):
    return _success(_income_stats_by_role(db, user, FireflyIncome))


@router.get("/firefly/income/stats/operators-summary")
async def firefly_income_operators_summary(db: DbSession, user: CurrentUser):
    return _success(_income_operators_summary(db, user, FireflyIncome))


@router.get("/firefly/income/wallet-stats")
async def firefly_income_wallet_stats(db: DbSession, user: CurrentUser):
    return _success(_income_wallet_stats(db, user, FireflyIncome))


@router.post("/firefly/income/search-by-uids")
async def search_firefly_income_by_uids(request: Request, db: DbSession, user: CurrentUser):
    body = await request.json()
    uids = [int(item) for item in body.get("uids", []) if str(item).isdigit()]
    stmt = select(FireflyIncome).where(FireflyIncome.member_id.in_(uids))
    stmt = _apply_org_scope(stmt, FireflyIncome, user)
    rows = db.execute(stmt.limit(1000)).scalars().all()
    return _success([_income_payload(row) for row in rows])


@router.post("/firefly/income/update-by-user-rate")
async def update_firefly_income_by_user_rate(request: Request, db: DbSession):
    body = await request.json()
    ids = [int(item) for item in _body_ids(body) if str(item).isdigit()]
    rows = db.execute(select(FireflyIncome).where(FireflyIncome.id.in_(ids))).scalars().all()
    for row in rows:
        rate = row.commission_rate if row.commission_rate is not None else 1.0
        row.commission_amount = row.income_amount * rate
    db.commit()
    return _success({"updated": len(rows)})


@router.post("/firefly/income")
async def create_firefly_income(request: Request, db: DbSession, user: CurrentUser):
    body = await request.json()
    row = FireflyIncome(
        organization_id=_as_int(body.get("organization_id"), user.organization_id),
        member_id=_as_int(body.get("member_id") or body.get("uid")),
        account_id=body.get("account_id"),
        task_id=body.get("task_id"),
        task_name=body.get("task_name") or body.get("drama_name"),
        income_amount=_as_float(body.get("income_amount") or body.get("income")),
        commission_rate=_as_float(body.get("commission_rate"), 1.0),
        commission_amount=_as_float(body.get("commission_amount"), _as_float(body.get("income_amount") or body.get("income"))),
        income_date=_as_date(body.get("income_date")),
        settlement_status=body.get("settlement_status") or "pending",
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return _success(_income_payload(row))


@router.put("/firefly/income/{income_id}")
async def update_firefly_income(income_id: int, request: Request, db: DbSession):
    row = db.get(FireflyIncome, income_id)
    if row is None:
        return _success(None, message="income not found")
    body = await request.json()
    for field in ["task_id", "task_name", "settlement_status"]:
        if field in body:
            setattr(row, field, body[field])
    if "income_amount" in body or "income" in body:
        row.income_amount = _as_float(body.get("income_amount", body.get("income")))
    if "commission_rate" in body:
        row.commission_rate = _as_float(body.get("commission_rate"))
    if "commission_amount" in body:
        row.commission_amount = _as_float(body.get("commission_amount"))
    if "income_date" in body:
        row.income_date = _as_date(body.get("income_date"))
    db.commit()
    return _success(_income_payload(row))


@router.delete("/firefly/income/{income_id}")
async def delete_firefly_income(income_id: int, db: DbSession):
    row = db.get(FireflyIncome, income_id)
    if row:
        db.delete(row)
        db.commit()
    return _success({"deleted": True})


@router.put("/firefly/income/{income_id}/settlement")
async def update_firefly_income_settlement(income_id: int, request: Request, db: DbSession):
    row = db.get(FireflyIncome, income_id)
    if row is None:
        return _success(None, message="income not found")
    body = await request.json()
    row.settlement_status = body.get("settlement_status") or "settled"
    db.commit()
    return _success(_income_payload(row))


@router.post("/firefly/income/batch-delete")
async def batch_delete_firefly_income(request: Request, db: DbSession):
    body = await request.json()
    ids = [int(item) for item in _body_ids(body) if str(item).isdigit()]
    rows = db.execute(select(FireflyIncome).where(FireflyIncome.id.in_(ids))).scalars().all()
    for row in rows:
        db.delete(row)
    db.commit()
    return _success({"deleted": len(rows)})


@router.post("/firefly/income/batch-settlement")
async def batch_firefly_income_settlement(request: Request, db: DbSession):
    body = await request.json()
    ids = [int(item) for item in _body_ids(body) if str(item).isdigit()]
    status = body.get("settlement_status") or "settled"
    rows = db.execute(select(FireflyIncome).where(FireflyIncome.id.in_(ids))).scalars().all()
    for row in rows:
        row.settlement_status = status
    db.commit()
    return _success({"updated": len(rows), "settlement_status": status})


@router.get("/firefly/members/stats/by-role")
async def firefly_members_stats_by_role(db: DbSession, user: CurrentUser):
    return await firefly_member_stats(db, user)


@router.get("/firefly/members/stats/operators-summary")
async def firefly_members_operators_summary(db: DbSession, user: CurrentUser):
    return _success({"operators": [], **(await firefly_member_stats(db, user))["data"]})


@router.post("/firefly/members/upload")
async def upload_firefly_members(request: Request, db: DbSession, user: CurrentUser):
    body = await request.json()
    members = body.get("members") or []
    created = 0
    for item in members:
        member_id = _as_int(item.get("member_id") or item.get("uid"))
        if not member_id:
            continue
        db.add(FireflyMember(organization_id=user.organization_id, member_id=member_id, nickname=item.get("nickname") or item.get("member_name")))
        created += 1
    db.commit()
    return _success({"created": created})


@router.post("/firefly/members/sync")
async def sync_firefly_members():
    return _external_not_connected("firefly_members_sync")


@router.put("/firefly/members/{member_id}")
async def update_firefly_member(member_id: int, request: Request, db: DbSession):
    row = db.get(FireflyMember, member_id)
    if row is None:
        return _success(None, message="member not found")
    body = await request.json()
    if "nickname" in body or "member_name" in body:
        row.nickname = body.get("nickname") or body.get("member_name")
    if "fans_count" in body:
        row.fans_count = _as_int(body.get("fans_count"))
    if "broker_name" in body:
        row.broker_name = body.get("broker_name")
    if "hidden" in body:
        row.hidden = _as_bool(body.get("hidden"))
    db.commit()
    return _success(_member_payload(row))


@router.delete("/firefly/members/{member_id}")
async def delete_firefly_member(member_id: int, db: DbSession):
    row = db.get(FireflyMember, member_id)
    if row:
        db.delete(row)
        db.commit()
    return _success({"deleted": True})


@router.get("/firefly/members/{member_id}/all-records")
async def firefly_member_all_records(member_id: int, db: DbSession):
    member = db.get(FireflyMember, member_id)
    real_member_id = member.member_id if member else member_id
    rows = db.execute(select(FireflyIncome).where(FireflyIncome.member_id == real_member_id).order_by(FireflyIncome.id.desc()).limit(1000)).scalars().all()
    return _success([_income_payload(row) for row in rows])


@router.get("/firefly/members/{member_id}/period-records")
async def firefly_member_period_records(member_id: int, db: DbSession):
    return await firefly_member_all_records(member_id, db)


@router.get("/spark/stats")
async def spark_stats(db: DbSession, user: CurrentUser):
    return await spark_member_stats(db, user)


@router.post("/spark/members")
async def create_spark_member(request: Request, db: DbSession, user: CurrentUser):
    body = await request.json()
    row = SparkMember(
        organization_id=_as_int(body.get("organization_id"), user.organization_id),
        member_id=_as_int(body.get("member_id") or body.get("uid")),
        nickname=body.get("nickname") or body.get("member_name"),
        fans_count=_as_int(body.get("fans_count")),
        broker_name=body.get("broker_name"),
        task_count=_as_int(body.get("task_count")),
        hidden=_as_bool(body.get("hidden")),
        first_release_id=body.get("first_release_id"),
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return _success(_member_payload(row))


@router.put("/spark/members/{member_id}")
async def update_spark_member(member_id: int, request: Request, db: DbSession):
    row = db.get(SparkMember, member_id)
    if row is None:
        return _success(None, message="member not found")
    body = await request.json()
    for field in ["nickname", "broker_name", "first_release_id"]:
        if field in body:
            setattr(row, field, body[field])
    if "member_name" in body:
        row.nickname = body.get("member_name")
    if "fans_count" in body:
        row.fans_count = _as_int(body.get("fans_count"))
    if "task_count" in body:
        row.task_count = _as_int(body.get("task_count"))
    if "hidden" in body:
        row.hidden = _as_bool(body.get("hidden"))
    db.commit()
    return _success(_member_payload(row))


@router.delete("/spark/members/{member_id}")
async def delete_spark_member(member_id: int, db: DbSession):
    row = db.get(SparkMember, member_id)
    if row:
        db.delete(row)
        db.commit()
    return _success({"deleted": True})


@router.post("/spark/income")
async def create_spark_income(request: Request, db: DbSession, user: CurrentUser):
    body = await request.json()
    row = SparkIncome(
        organization_id=_as_int(body.get("organization_id"), user.organization_id),
        member_id=_as_int(body.get("member_id") or body.get("uid")),
        account_id=body.get("account_id"),
        task_id=body.get("task_id"),
        task_name=body.get("task_name") or body.get("drama_name"),
        income_amount=_as_float(body.get("income_amount") or body.get("income")),
        commission_rate=_as_float(body.get("commission_rate"), 1.0),
        commission_amount=_as_float(body.get("commission_amount"), _as_float(body.get("income_amount") or body.get("income"))),
        start_date=_as_date(body.get("start_date") or body.get("income_date")),
        end_date=_as_date(body.get("end_date")),
        settlement_status=body.get("settlement_status") or "pending",
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return _success(_income_payload(row))


@router.put("/spark/income/{income_id}")
async def update_spark_income(income_id: int, request: Request, db: DbSession):
    row = db.get(SparkIncome, income_id)
    if row is None:
        return _success(None, message="income not found")
    body = await request.json()
    for field in ["task_id", "task_name", "settlement_status"]:
        if field in body:
            setattr(row, field, body[field])
    if "income_amount" in body or "income" in body:
        row.income_amount = _as_float(body.get("income_amount", body.get("income")))
    if "commission_rate" in body:
        row.commission_rate = _as_float(body.get("commission_rate"))
    if "commission_amount" in body:
        row.commission_amount = _as_float(body.get("commission_amount"))
    if "start_date" in body:
        row.start_date = _as_date(body.get("start_date"))
    if "end_date" in body:
        row.end_date = _as_date(body.get("end_date"))
    db.commit()
    return _success(_income_payload(row))


@router.delete("/spark/income/{income_id}")
async def delete_spark_income(income_id: int, db: DbSession):
    row = db.get(SparkIncome, income_id)
    if row:
        db.delete(row)
        db.commit()
    return _success({"deleted": True})


@router.get("/spark/archive/stats/by-role")
async def spark_archive_stats_by_role(db: DbSession, user: CurrentUser):
    return _success(_income_stats_by_role(db, user, IncomeArchive))


@router.get("/spark/archive/stats/operators-summary")
async def spark_archive_operators_summary(db: DbSession, user: CurrentUser):
    return _success(_income_operators_summary(db, user, IncomeArchive))


@router.get("/spark/archive/wallet-stats")
async def spark_archive_wallet_stats(db: DbSession, user: CurrentUser):
    return _success(_income_wallet_stats(db, user, IncomeArchive))


@router.post("/spark/archive/search-by-uids")
async def search_spark_archive_by_uids(request: Request, db: DbSession, user: CurrentUser):
    body = await request.json()
    uids = [int(item) for item in body.get("uids", []) if str(item).isdigit()]
    stmt = select(IncomeArchive).where(IncomeArchive.member_id.in_(uids), IncomeArchive.program_type == "spark")
    stmt = _apply_org_scope(stmt, IncomeArchive, user)
    rows = db.execute(stmt.limit(1000)).scalars().all()
    return _success([_income_payload(row) for row in rows])


@router.post("/spark/archive/update-by-user-rate")
async def update_spark_archive_by_user_rate(request: Request, db: DbSession):
    body = await request.json()
    ids = [int(item) for item in _body_ids(body) if str(item).isdigit()]
    rows = db.execute(select(IncomeArchive).where(IncomeArchive.id.in_(ids))).scalars().all()
    for row in rows:
        rate = row.commission_rate if row.commission_rate is not None else 1.0
        row.commission_amount = row.total_amount * rate
    db.commit()
    return _success({"updated": len(rows)})


@router.put("/spark/archive/{archive_id}/settlement")
async def update_archive_settlement(archive_id: int, request: Request, db: DbSession):
    row = db.get(IncomeArchive, archive_id)
    if row is None:
        return _success(None, message="archive not found")
    body = await request.json()
    row.settlement_status = body.get("settlement_status") or "settled"
    db.commit()
    return _success(_income_payload(row))


@router.put("/spark/archive/{archive_id}/commission")
async def update_archive_commission(archive_id: int, request: Request, db: DbSession):
    row = db.get(IncomeArchive, archive_id)
    if row is None:
        return _success(None, message="archive not found")
    body = await request.json()
    row.commission_rate = _as_float(body.get("commission_rate"), row.commission_rate or 1.0)
    row.commission_amount = row.total_amount * row.commission_rate
    db.commit()
    return _success(_income_payload(row))


@router.post("/spark/archive/batch-settlement")
async def batch_archive_settlement(request: Request, db: DbSession):
    body = await request.json()
    ids = [int(item) for item in _body_ids(body) if str(item).isdigit()]
    status = body.get("settlement_status") or "settled"
    rows = db.execute(select(IncomeArchive).where(IncomeArchive.id.in_(ids))).scalars().all()
    for row in rows:
        row.settlement_status = status
    db.commit()
    return _success({"updated": len(rows)})


@router.post("/spark/archive/batch-commission")
async def batch_archive_commission(request: Request, db: DbSession):
    body = await request.json()
    ids = [int(item) for item in _body_ids(body) if str(item).isdigit()]
    rate = _as_float(body.get("commission_rate"), 1.0)
    rows = db.execute(select(IncomeArchive).where(IncomeArchive.id.in_(ids))).scalars().all()
    for row in rows:
        row.commission_rate = rate
        row.commission_amount = row.total_amount * rate
    db.commit()
    return _success({"updated": len(rows)})


@router.get("/spark/photos")
async def spark_photos(db: DbSession, user: CurrentUser, page: int = 1, page_size: int | None = None, size: int | None = None, search: str | None = None):
    page, per_page = _page_size(page, page_size, size)
    stmt = select(SparkPhoto)
    stmt = _apply_org_scope(stmt, SparkPhoto, user)
    if search:
        like = f"%{search}%"
        stmt = stmt.where(or_(SparkPhoto.photo_id.like(like), SparkPhoto.title.like(like), SparkPhoto.member_name.like(like)))
    total = _count(db, stmt)
    rows = db.execute(stmt.order_by(SparkPhoto.id.desc()).offset((page - 1) * per_page).limit(per_page)).scalars().all()
    return _success([_spark_photo_payload(row) for row in rows], total=total)


@router.post("/spark/photos")
async def create_spark_photo(request: Request, db: DbSession, user: CurrentUser):
    body = await request.json()
    row = SparkPhoto(
        organization_id=_as_int(body.get("organization_id"), user.organization_id),
        photo_id=str(body.get("photo_id") or body.get("work_id") or uuid4().hex),
        member_id=_as_int(body.get("member_id") or body.get("uid")),
        member_name=body.get("member_name") or body.get("nickname"),
        title=body.get("title") or body.get("description"),
        view_count=_as_int(body.get("view_count")),
        like_count=_as_int(body.get("like_count")),
        comment_count=_as_int(body.get("comment_count")),
        duration=body.get("duration"),
        publish_date=_as_datetime(body.get("publish_date")),
        cover_url=body.get("cover_url") or body.get("thumbnail"),
        play_url=body.get("play_url"),
        avatar_url=body.get("avatar_url"),
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return _success(_spark_photo_payload(row))


@router.put("/spark/photos/{photo_row_id}")
async def update_spark_photo(photo_row_id: int, request: Request, db: DbSession):
    row = db.get(SparkPhoto, photo_row_id)
    if row is None:
        return _success(None, message="photo not found")
    body = await request.json()
    for field in ["member_name", "title", "duration", "cover_url", "play_url", "avatar_url"]:
        if field in body:
            setattr(row, field, body[field])
    for field in ["view_count", "like_count", "comment_count"]:
        if field in body:
            setattr(row, field, _as_int(body[field]))
    if "publish_date" in body:
        row.publish_date = _as_datetime(body.get("publish_date"))
    db.commit()
    return _success(_spark_photo_payload(row))


@router.delete("/spark/photos/{photo_row_id}")
async def delete_spark_photo(photo_row_id: int, db: DbSession):
    row = db.get(SparkPhoto, photo_row_id)
    if row:
        db.delete(row)
        db.commit()
    return _success({"deleted": True})


@router.get("/spark/violation-dramas")
async def spark_violation_dramas(db: DbSession, user: CurrentUser, page: int = 1, page_size: int | None = None, size: int | None = None, search: str | None = None):
    page, per_page = _page_size(page, page_size, size)
    stmt = select(SparkViolationDrama)
    stmt = _apply_org_scope(stmt, SparkViolationDrama, user)
    if search:
        like = f"%{search}%"
        stmt = stmt.where(or_(SparkViolationDrama.drama_title.like(like), SparkViolationDrama.username.like(like), SparkViolationDrama.reason.like(like)))
    total = _count(db, stmt)
    rows = db.execute(stmt.order_by(SparkViolationDrama.violation_count.desc()).offset((page - 1) * per_page).limit(per_page)).scalars().all()
    return _success([_violation_drama_payload(row) for row in rows], total=total)


@router.post("/spark/violation-dramas")
async def create_spark_violation_drama(request: Request, db: DbSession, user: CurrentUser):
    body = await request.json()
    row = SparkViolationDrama(
        organization_id=_as_int(body.get("organization_id"), user.organization_id),
        drama_title=str(body.get("drama_title") or body.get("title") or body.get("drama_name") or "").strip(),
        source_photo_id=body.get("source_photo_id"),
        source_caption=body.get("source_caption"),
        user_id=_as_int(body.get("user_id") or body.get("uid")),
        username=body.get("username"),
        violation_count=_as_int(body.get("violation_count"), 1),
        last_violation_date=_as_datetime(body.get("last_violation_date")),
        sub_biz=body.get("sub_biz"),
        status_desc=body.get("status_desc"),
        reason=body.get("reason"),
        media_url=body.get("media_url"),
        thumb_url=body.get("thumb_url") or body.get("thumbnail"),
        broker_name=body.get("broker_name"),
        is_blacklisted=_as_bool(body.get("is_blacklisted")),
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return _success(_violation_drama_payload(row))


@router.put("/spark/violation-dramas/{row_id}")
async def update_spark_violation_drama(row_id: int, request: Request, db: DbSession):
    row = db.get(SparkViolationDrama, row_id)
    if row is None:
        return _success(None, message="violation drama not found")
    body = await request.json()
    for field in ["drama_title", "source_photo_id", "source_caption", "username", "sub_biz", "status_desc", "reason", "media_url", "thumb_url", "broker_name"]:
        if field in body:
            setattr(row, field, body[field])
    if "violation_count" in body:
        row.violation_count = _as_int(body.get("violation_count"), row.violation_count)
    if "is_blacklisted" in body:
        row.is_blacklisted = _as_bool(body.get("is_blacklisted"))
    db.commit()
    return _success(_violation_drama_payload(row))


@router.delete("/spark/violation-dramas/{row_id}")
async def delete_spark_violation_drama(row_id: int, db: DbSession):
    row = db.get(SparkViolationDrama, row_id)
    if row:
        db.delete(row)
        db.commit()
    return _success({"deleted": True})


@router.post("/spark/violation-photos")
async def create_spark_violation_photo(request: Request, db: DbSession, user: CurrentUser):
    body = await request.json()
    row = ViolationPhoto(
        organization_id=_as_int(body.get("organization_id"), user.organization_id),
        work_id=str(body.get("work_id") or body.get("photo_id") or uuid4().hex),
        uid=str(body.get("uid") or ""),
        thumbnail=body.get("thumbnail") or body.get("cover_url"),
        description=body.get("description") or body.get("caption"),
        business_type=body.get("business_type") or body.get("sub_biz") or "spark",
        violation_reason=body.get("violation_reason"),
        view_count=_as_int(body.get("view_count")),
        like_count=_as_int(body.get("like_count")),
        appeal_status=body.get("appeal_status"),
        appeal_reason=body.get("appeal_reason"),
        published_at=_as_datetime(body.get("published_at")),
        detected_at=_as_datetime(body.get("detected_at")),
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return _success(_violation_payload(row))


@router.put("/spark/violation-photos/{row_id}")
async def update_spark_violation_photo(row_id: int, request: Request, db: DbSession):
    row = db.get(ViolationPhoto, row_id)
    if row is None:
        return _success(None, message="violation photo not found")
    body = await request.json()
    for field in ["uid", "thumbnail", "description", "business_type", "violation_reason", "appeal_status", "appeal_reason"]:
        if field in body:
            setattr(row, field, body[field])
    if "view_count" in body:
        row.view_count = _as_int(body.get("view_count"))
    if "like_count" in body:
        row.like_count = _as_int(body.get("like_count"))
    db.commit()
    return _success(_violation_payload(row))


@router.delete("/spark/violation-photos/{row_id}")
async def delete_spark_violation_photo(row_id: int, db: DbSession):
    row = db.get(ViolationPhoto, row_id)
    if row:
        db.delete(row)
        db.commit()
    return _success({"deleted": True})


@router.get("/config")
async def config():
    return _success({})
