"""Compatibility API for the demo admin frontend.

The live demo frontend is a Vue admin bundle that talks to `/api/*` and expects
responses shaped as `{ success, data, message }`.  Our maintained client API
lives under `/api/client/*` and uses `{ ok, data, meta }`.  This router lets us
serve the demo UI unchanged while still reading/writing our own database.
"""
from __future__ import annotations

from datetime import date, datetime
from typing import Any

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel
from sqlalchemy import String, func, or_, select
from sqlalchemy.orm import Session

from app.core.deps import CurrentUser, DbSession
from app.core.security import hash_password
from app.models import (
    Account,
    AccountGroup,
    AccountTaskRecord,
    Announcement,
    CloudCookieAccount,
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
    OrgMember,
    Organization,
    SparkIncome,
    SparkMember,
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


def _apply_org_scope(stmt, model, user: User):
    if user.is_superadmin or user.role == "super_admin":
        return stmt
    if hasattr(model, "organization_id"):
        return stmt.where(model.organization_id == user.organization_id)
    return stmt


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
async def logs(page: int = 1, page_size: int | None = None, size: int | None = None):
    page, per_page = _page_size(page, page_size, size)
    return _success([], total=0, pagination={"total": 0, "page": page, "page_size": per_page})


@router.get("/auth/logs/stats")
async def log_stats():
    return _success({"today": 0, "total": 0, "errors": 0})


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
    stmt = select(CollectPool.auth_code, func.min(CollectPool.created_at)).where(CollectPool.auth_code.is_not(None)).group_by(CollectPool.auth_code)
    if not user.is_superadmin:
        stmt = stmt.where(CollectPool.organization_id == user.organization_id)
    rows = [
        {
            "id": index,
            "auth_code": code,
            "name": code,
            "is_active": 1,
            "expire_at": None,
            "created_at": _dt(created_at),
        }
        for index, (code, created_at) in enumerate(db.execute(stmt).all(), start=1)
        if code
    ]
    return _success(rows)


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


@router.get("/config")
async def config():
    return _success({})
