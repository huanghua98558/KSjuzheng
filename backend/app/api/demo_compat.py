"""Compatibility API for the demo admin frontend.

The live demo frontend is a Vue admin bundle that talks to `/api/*` and expects
responses shaped as `{ success, data, message }`.  Our maintained client API
lives under `/api/client/*` and uses `{ ok, data, meta }`.  This router lets us
serve the demo UI unchanged while still reading/writing our own database.
"""
from __future__ import annotations

import json
from datetime import date, datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

from fastapi import APIRouter, Depends, File, Request, UploadFile
from pydantic import BaseModel
from sqlalchemy import String, func, or_, select, text
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
    FluorescentMember,
    HighIncomeDrama,
    HighIncomeDramaLink,
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
from app.services import auth_service, source_mysql_service, statistics_service


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


ROLE_CATALOG = [
    {
        "id": "super_admin",
        "value": "super_admin",
        "name": "超级管理员",
        "label": "超级管理员",
        "level": 100,
        "description": "系统最高权限，可查看所有MCN账号，可删除账号，可查看任务记录",
    },
    {
        "id": "operator",
        "value": "operator",
        "name": "团长",
        "label": "团长",
        "level": 50,
        "description": "只能查看自己的MCN账号，可上传账号、授权MCN、创建分组，可创建队长和普通用户",
    },
    {
        "id": "captain",
        "value": "captain",
        "name": "队长",
        "label": "队长",
        "level": 30,
        "description": "介于团长和普通用户之间的角色，可管理下属普通用户，可创建普通用户",
    },
    {
        "id": "normal_user",
        "value": "normal_user",
        "name": "普通用户",
        "label": "普通用户",
        "level": 0,
        "description": "由团长或队长创建和管理的普通用户",
    },
]

ROLE_FEATURES = [
    {"id": "account:own", "key": "account:own", "name": "查看自己的账号", "module": "account", "min_role": "operator"},
    {"id": "account:all", "key": "account:all", "name": "查看所有账号", "module": "account", "min_role": "super_admin"},
    {"id": "account:upload", "key": "account:upload", "name": "上传MCN账号", "module": "account", "min_role": "operator"},
    {"id": "account:authorize_mcn", "key": "account:authorize_mcn", "name": "授权MCN成员", "module": "account", "min_role": "operator"},
    {"id": "account:delete", "key": "account:delete", "name": "删除MCN账号", "module": "account", "min_role": "super_admin"},
    {"id": "account:create_group", "key": "account:create_group", "name": "创建分组", "module": "account", "min_role": "operator"},
    {"id": "account:assign_group", "key": "account:assign_group", "name": "分配账号到分组", "module": "account", "min_role": "operator"},
    {"id": "drama:link_stats", "key": "drama:link_stats", "name": "查看短剧链接统计", "module": "drama", "min_role": "super_admin"},
    {"id": "task:history", "key": "task:history", "name": "查看任务记录", "module": "task", "min_role": "super_admin"},
    {"id": "user:manage", "key": "user:manage", "name": "管理用户", "module": "user", "min_role": "super_admin"},
]


def _dt(value: datetime | date | int | float | str | None) -> str | None:
    if value is None:
        return None
    if isinstance(value, (int, float)):
        if value <= 0:
            return None
        seconds = value / 1000 if value > 10_000_000_000 else value
        return datetime.fromtimestamp(seconds).isoformat()
    if isinstance(value, str):
        return value
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


PERMISSION_LABELS = {
    "account:add": "新增软件账号",
    "account:advanced_filter": "高级筛选",
    "account:assign_user": "分配用户",
    "account:authorize_mcn": "授权 MCN",
    "account:batch_edit_commission_rate": "批量修改分成比例",
    "account:batch_invite": "批量邀请",
    "account:batch_open_spark": "批量开通星火",
    "account:batch_query_records": "批量查询记录",
    "account:control": "账号控制",
    "account:delete": "删除账号",
    "account:direct_invite": "直接邀请",
    "account:edit_commission_rate": "修改分成比例",
    "account:file_batch": "文件批量导入",
    "account:group_manager": "分组管理",
    "account:import": "导入账号",
    "account:invitation_records": "邀请记录",
    "account:open_spark": "开通星火",
    "account:refresh": "刷新账号",
    "account:remove_group": "移出分组",
    "account:set_group": "设置分组",
    "account:sync_auth": "同步授权",
    "account:unauthorize_mcn": "取消 MCN 授权",
    "account:update_income": "更新收益",
    "account_drama_mode": "账号短剧模式",
    "account_mode": "账号模式",
    "browser_accounts": "浏览器账号",
    "drama_favorite": "短剧收藏",
    "drama_mode": "短剧模式",
    "drama_mode2": "短剧模式二",
    "elf_film_cxt": "橙星短剧",
    "elf_film_tv": "影视短剧",
    "elf_film_tv_activity": "影视活动",
    "elf_firefly_plan": "萤光计划",
    "elf_goods_delivery": "商品交付",
    "elf_spark_plan": "星火计划",
    "firefly_plan": "萤光计划",
    "income_query": "收益查询",
    "task_history": "任务历史",
    "task_queue": "任务队列",
    "video_collection": "视频收藏",
    "user:update_org_cookie": "更新机构 Cookie",
    "user_alipay_info": "支付宝信息",
    "user_alipay_stats": "支付宝统计",
    "user_assign_operator": "分配运营",
    "user_bindings": "账号绑定",
    "user_change_role": "修改角色",
    "user_commission_visibility": "分成可见性",
    "user_cooperation_type": "合作类型",
    "user_create_captain": "创建队长",
    "user_delete": "删除用户",
    "user_edit": "编辑用户",
    "user_edit_commission_rate": "修改用户分成",
    "user_level": "用户等级",
    "user_oem_setting": "OEM 设置",
    "user_quota": "账号额度",
    "user_reset_password": "重置密码",
    "user_simulation_mode": "模拟模式",
    "user_toggle_status": "启用/禁用用户",
    "page:account-violation": "账号违规信息",
    "page:accounts": "软件账号管理",
    "page:cloud-cookies": "云端 Cookie 管理",
    "page:collect-pool": "短剧收藏池",
    "page:cxt-user": "橙星用户",
    "page:cxt-videos": "橙星视频",
    "page:dashboard": "概览仪表盘",
    "page:drama-collections": "短剧收藏记录",
    "page:drama-statistics": "短剧链接统计",
    "page:external-url-stats": "外部链接统计",
    "page:firefly-income": "萤光本月收益",
    "page:firefly-members": "萤光成员",
    "page:fluorescent-income": "萤光收益明细",
    "page:high-income-dramas": "高转化短剧管理",
    "page:ks-accounts": "KS 账号管理",
    "page:org-members": "机构成员管理",
    "page:settings": "系统配置",
    "page:spark-archive": "星火历史收益",
    "page:spark-income": "星火收益",
    "page:spark-members": "星火成员",
    "page:spark-photos": "星火作品",
    "page:spark-violation-dramas": "星火违规短剧",
    "page:spark-violation-photos": "星火违规作品",
    "page:statistics": "执行统计",
    "page:users": "用户管理",
    "page:wallet-info": "钱包信息",
}


def _permission_label(code: str) -> str:
    if code in PERMISSION_LABELS:
        return PERMISSION_LABELS[code]
    if code.startswith("page:"):
        return code[5:].replace("-", " ").replace("_", " ")
    return code.replace("account:", "").replace("user_", "").replace("_", " ").replace("-", " ")


def _permission_payload(code: str, granted: int = 1) -> dict[str, Any]:
    label = _permission_label(code)
    return {
        "key": code,
        "code": code,
        "perm_key": code,
        "button_key": code,
        "page_key": code,
        "name": label,
        "label": label,
        "title": label,
        "display_name": label,
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
        "device_code": account.device_serial or "",
        "device_num": account.device_serial or "",
        "device_no": account.device_serial or "",
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


def _member_payload(
    member: SparkMember | FireflyMember | FluorescentMember,
    owner: User | None = None,
    organization: Organization | None = None,
) -> dict[str, Any]:
    owner_rate = owner.commission_rate if owner and owner.commission_rate is not None else None
    owner_rate_percent = None
    if owner_rate is not None:
        owner_rate_percent = owner_rate * 100 if owner_rate <= 1 else owner_rate
    avatar = getattr(member, "avatar", None)
    in_limit = int(bool(getattr(member, "in_limit", False)))
    base = {
        "id": member.id,
        "member_id": str(member.member_id),
        "uid": str(member.member_id),
        "nickname": member.nickname or "",
        "member_name": member.nickname or "",
        "member_head": avatar,
        "avatar": avatar,
        "fans_count": member.fans_count,
        "in_limit": in_limit,
        "broker_name": member.broker_name or "",
        "organization_id": member.organization_id,
        "org_id": member.organization_id,
        "org_name": organization.name if organization else None,
        "organization_name": organization.name if organization else None,
        "account_id": member.account_id,
        "owner_id": owner.id if owner else None,
        "user_id": owner.id if owner else None,
        "owner_username": owner.username if owner else None,
        "owner_nickname": (owner.display_name or owner.username) if owner else None,
        "user_commission_rate": owner_rate_percent if owner_rate_percent is not None else 100,
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


def _member_payloads(db: Session, rows: list[SparkMember | FireflyMember | FluorescentMember]) -> list[dict[str, Any]]:
    account_ids = [row.account_id for row in rows if row.account_id]
    org_ids = [row.organization_id for row in rows if row.organization_id]
    accounts = {}
    users_by_id = {}
    if account_ids:
        accounts = {
            row.id: row
            for row in db.execute(select(Account).where(Account.id.in_(account_ids))).scalars().all()
        }
        user_ids = [row.assigned_user_id for row in accounts.values() if row.assigned_user_id]
        if user_ids:
            users_by_id = {
                row.id: row
                for row in db.execute(select(User).where(User.id.in_(user_ids))).scalars().all()
            }
    organizations = {}
    if org_ids:
        organizations = {
            row.id: row
            for row in db.execute(select(Organization).where(Organization.id.in_(org_ids))).scalars().all()
        }
    return [
        _member_payload(
            row,
            users_by_id.get(accounts[row.account_id].assigned_user_id) if row.account_id in accounts else None,
            organizations.get(row.organization_id),
        )
        for row in rows
    ]


def _income_payload(
    row: SparkIncome | FireflyIncome | FluorescentIncome | IncomeArchive,
    member: SparkMember | FireflyMember | FluorescentMember | None = None,
    account: Account | None = None,
    owner: User | None = None,
    organization: Organization | None = None,
) -> dict[str, Any]:
    amount = getattr(row, "income_amount", None)
    if amount is None:
        amount = getattr(row, "total_amount", 0)
    owner_rate = owner.commission_rate if owner and owner.commission_rate is not None else None
    owner_rate_percent = owner_rate * 100 if owner_rate is not None and owner_rate <= 1 else owner_rate
    member_name = member.nickname if member else None
    avatar = getattr(member, "avatar", None) if member else None
    return {
        "id": row.id,
        "organization_id": row.organization_id,
        "org_id": row.organization_id,
        "org_name": organization.name if organization else None,
        "organization_name": organization.name if organization else None,
        "member_id": str(row.member_id),
        "uid": str(row.member_id),
        "member_name": member_name or "",
        "nickname": member_name or "",
        "member_head": avatar,
        "avatar": avatar,
        "fans_count": member.fans_count if member else 0,
        "broker_name": member.broker_name if member else "",
        "org_task_num": getattr(member, "org_task_num", 0) if member else 0,
        "account_id": row.account_id,
        "owner_id": owner.id if owner else None,
        "user_id": owner.id if owner else None,
        "owner_username": owner.username if owner else None,
        "owner_nickname": (owner.display_name or owner.username) if owner else None,
        "user_commission_rate": owner_rate_percent if owner_rate_percent is not None else 100,
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


def _income_payloads(
    db: Session,
    rows: list[SparkIncome | FireflyIncome | FluorescentIncome | IncomeArchive],
) -> list[dict[str, Any]]:
    if not rows:
        return []

    org_ids = {row.organization_id for row in rows if row.organization_id}
    organizations = {
        row.id: row
        for row in db.execute(select(Organization).where(Organization.id.in_(org_ids))).scalars().all()
    } if org_ids else {}

    account_ids = {row.account_id for row in rows if row.account_id}
    accounts = {
        row.id: row
        for row in db.execute(select(Account).where(Account.id.in_(account_ids))).scalars().all()
    } if account_ids else {}

    member_keys: dict[type[Any], set[tuple[int, int]]] = {
        SparkMember: set(),
        FireflyMember: set(),
        FluorescentMember: set(),
    }
    row_member_models: dict[int, type[Any]] = {}
    for row in rows:
        model: type[Any] | None = None
        if isinstance(row, SparkIncome):
            model = SparkMember
        elif isinstance(row, FireflyIncome):
            model = FireflyMember
        elif isinstance(row, FluorescentIncome):
            model = FluorescentMember
        elif isinstance(row, IncomeArchive):
            model = SparkMember if row.program_type == "spark" else FluorescentMember
        if model is not None:
            row_member_models[id(row)] = model
            member_keys[model].add((row.organization_id, row.member_id))

    members: dict[tuple[type[Any], int, int], SparkMember | FireflyMember | FluorescentMember] = {}
    for model, keys in member_keys.items():
        if not keys:
            continue
        org_values = {org_id for org_id, _ in keys}
        member_values = {member_id for _, member_id in keys}
        found = db.execute(
            select(model).where(
                model.organization_id.in_(org_values),
                model.member_id.in_(member_values),
            )
        ).scalars().all()
        members.update({(model, item.organization_id, item.member_id): item for item in found})

    for row in rows:
        model = row_member_models.get(id(row))
        member = members.get((model, row.organization_id, row.member_id)) if model else None
        if member and member.account_id:
            account_ids.add(member.account_id)
    missing_account_ids = account_ids - set(accounts)
    if missing_account_ids:
        accounts.update({
            row.id: row
            for row in db.execute(select(Account).where(Account.id.in_(missing_account_ids))).scalars().all()
        })

    user_ids = {account.assigned_user_id for account in accounts.values() if account.assigned_user_id}
    users = {
        row.id: row
        for row in db.execute(select(User).where(User.id.in_(user_ids))).scalars().all()
    } if user_ids else {}

    payloads = []
    for row in rows:
        model = row_member_models.get(id(row))
        member = members.get((model, row.organization_id, row.member_id)) if model else None
        account = accounts.get(row.account_id) if row.account_id else None
        if account is None and member and member.account_id:
            account = accounts.get(member.account_id)
        owner = users.get(account.assigned_user_id) if account and account.assigned_user_id else None
        payloads.append(_income_payload(row, member, account, owner, organizations.get(row.organization_id)))
    return payloads


def _ks_account_payload(row: KsAccount) -> dict[str, Any]:
    return {
        "id": row.id,
        "uid": row.kuaishou_uid,
        "kuaishou_uid": row.kuaishou_uid,
        "username": row.account_name or row.kuaishou_uid,
        "account_name": row.account_name,
        "device_code": row.device_code,
        "device_num": row.device_code,
        "device_serial": row.device_code,
        "device_no": row.device_code,
        "organization_id": row.organization_id,
        "created_at": _dt(row.created_at),
    }


def _org_member_payload(
    row: OrgMember,
    organization: Organization | None = None,
    account: Account | None = None,
    owner: User | None = None,
) -> dict[str, Any]:
    return {
        "id": row.id,
        "member_id": str(row.member_id),
        "uid": str(row.member_id),
        "user_id": row.user_id,
        "nickname": row.nickname or "",
        "member_name": row.nickname or "",
        "avatar": row.avatar,
        "member_head": row.avatar,
        "fans_count": row.fans_count,
        "broker_name": row.broker_name or "",
        "cooperation_type": row.cooperation_type or "",
        "agreement_types": row.cooperation_type or "",
        "content_category": row.content_category or "",
        "mcn_level": row.mcn_level or "",
        "mcn_grade": row.mcn_level or "",
        "contract_renew_status": row.renewal_status or "",
        "renewal_status": row.renewal_status or "",
        "agreement_type": row.cooperation_type or "",
        "organization_id": row.organization_id,
        "org_id": row.organization_id,
        "org_name": organization.name if organization else None,
        "organization_name": organization.name if organization else None,
        "account_id": row.account_id,
        "owner_id": owner.id if owner else None,
        "owner_username": owner.username if owner else None,
        "owner_nickname": (owner.display_name or owner.username) if owner else None,
        "contract_expires_at": _dt(row.contract_expires_at),
        "created_at": _dt(row.created_at),
    }


def _org_member_payloads(db: Session, rows: list[OrgMember]) -> list[dict[str, Any]]:
    org_ids = {row.organization_id for row in rows if row.organization_id}
    account_ids = {row.account_id for row in rows if row.account_id}
    organizations = {
        row.id: row
        for row in db.execute(select(Organization).where(Organization.id.in_(org_ids))).scalars().all()
    } if org_ids else {}
    accounts = {
        row.id: row
        for row in db.execute(select(Account).where(Account.id.in_(account_ids))).scalars().all()
    } if account_ids else {}
    user_ids = {account.assigned_user_id for account in accounts.values() if account.assigned_user_id}
    users = {
        row.id: row
        for row in db.execute(select(User).where(User.id.in_(user_ids))).scalars().all()
    } if user_ids else {}
    return [
        _org_member_payload(
            row,
            organizations.get(row.organization_id),
            accounts.get(row.account_id) if row.account_id else None,
            users.get(accounts[row.account_id].assigned_user_id)
            if row.account_id in accounts and accounts[row.account_id].assigned_user_id
            else None,
        )
        for row in rows
    ]


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


def _source_org_member_payload(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": row["id"],
        "member_id": str(row["member_id"]),
        "uid": str(row["member_id"]),
        "user_id": row.get("user_id"),
        "nickname": row.get("member_name") or "",
        "member_name": row.get("member_name") or "",
        "avatar": row.get("member_head"),
        "member_head": row.get("member_head"),
        "fans_count": row.get("fans_count") or 0,
        "broker_id": row.get("broker_id"),
        "broker_name": row.get("broker_name") or "",
        "cooperation_type": row.get("agreement_types") or "",
        "agreement_types": row.get("agreement_types") or "",
        "broker_type": row.get("broker_type"),
        "content_category": row.get("content_category") or "",
        "mcn_level": row.get("mcn_grade") or "",
        "mcn_grade": row.get("mcn_grade") or "",
        "contract_renew_status": str(row.get("contract_renew_status") or ""),
        "renewal_status": str(row.get("contract_renew_status") or ""),
        "agreement_type": row.get("agreement_types") or "",
        "organization_id": row.get("org_id"),
        "org_id": row.get("org_id"),
        "org_name": None,
        "organization_name": None,
        "account_id": None,
        "owner_id": None,
        "owner_username": None,
        "owner_nickname": None,
        "last_photo_time": row.get("last_photo_time"),
        "last_photo_date": _dt(row.get("last_photo_date")),
        "last_live_time": row.get("last_live_time"),
        "last_live_date": _dt(row.get("last_live_date")),
        "contract_expires_at": _dt(row.get("contract_expire_date")),
        "contract_expire_date": _dt(row.get("contract_expire_date")),
        "join_time": row.get("join_time"),
        "join_date": _dt(row.get("join_date")),
        "comment": row.get("comment"),
        "created_at": _dt(row.get("created_at")),
        "updated_at": _dt(row.get("updated_at")),
    }


def _source_collect_pool_payload(row: dict[str, Any]) -> dict[str, Any]:
    platform = row.get("platform")
    platform_name = "kuaishou" if str(platform) in {"1", "kuaishou"} else str(platform or "kuaishou")
    return {
        "id": row["id"],
        "name": row.get("name"),
        "drama_name": row.get("name"),
        "url": row.get("url"),
        "drama_url": row.get("url"),
        "platform": platform_name,
        "platform_raw": platform,
        "auth_code": row.get("username"),
        "username": row.get("username"),
        "cover_url": row.get("cover_url"),
        "status": "active" if row.get("url") else "abnormal",
        "abnormal_reason": None if row.get("url") else "url_empty",
        "organization_id": None,
        "created_at": _dt(row.get("created_at")),
    }


def _high_income_payload(row: HighIncomeDrama) -> dict[str, Any]:
    return {
        "id": row.id,
        "title": row.drama_name,
        "name": row.drama_name,
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
        "task_type": row.task_type,
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


def _high_income_link_payload(row: HighIncomeDramaLink) -> dict[str, Any]:
    return {
        "id": row.id,
        "drama_name": row.drama_name,
        "title": row.drama_name,
        "task_type": "高转化短剧",
        "drama_link": row.drama_url,
        "drama_url": row.drama_url,
        "total_count": row.reference_count,
        "execute_count": row.reference_count,
        "success_count": 0,
        "failed_count": 0,
        "account_count": row.account_count,
        "success_rate": 0,
        "source": row.source,
        "organization_id": row.organization_id,
        "last_executed_at": _dt(row.last_seen_at),
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


def _source_org_clause(user: CurrentUser, column: str = "org_id") -> tuple[list[str], dict[str, Any]]:
    if user.is_superadmin:
        return [], {}
    return [f"{column} = :viewer_org_id"], {"viewer_org_id": user.organization_id}


def _source_count(db: Session, table: str, where: list[str], params: dict[str, Any]) -> int:
    sql_where = " AND ".join(where) if where else "1=1"
    return int(db.execute(text(f"SELECT COUNT(*) FROM {table} WHERE {sql_where}"), params).scalar_one())


def _source_member_payload(row: dict[str, Any], *, program: str) -> dict[str, Any]:
    member_id = row.get("member_id") or row.get("author_id") or row.get("id")
    name = row.get("member_name") or row.get("author_name") or row.get("nickname") or ""
    avatar = row.get("member_head") or row.get("avatar")
    org_id = row.get("org_id") or row.get("organization_id")
    total_amount = row.get("total_amount") or row.get("total_income") or row.get("period_income") or 0
    task_count = row.get("org_task_num") or row.get("record_count") or 0
    return {
        "id": row.get("id") or member_id,
        "member_id": str(member_id) if member_id is not None else "",
        "uid": str(member_id) if member_id is not None else "",
        "nickname": name,
        "member_name": name,
        "member_head": avatar,
        "avatar": avatar,
        "fans_count": row.get("fans_count") or 0,
        "in_limit": 1 if _as_bool(row.get("in_limit")) else 0,
        "broker_name": row.get("broker_name") or "",
        "organization_id": org_id,
        "org_id": org_id,
        "account_id": row.get("account_id"),
        "owner_id": None,
        "user_id": None,
        "owner_username": None,
        "owner_nickname": None,
        "user_commission_rate": 100,
        "hidden": 0,
        "task_count": task_count,
        "org_task_num": task_count,
        "total_amount": float(total_amount or 0),
        "income": float(total_amount or 0),
        "first_release_id": row.get("first_release_id"),
        "program": program,
        "created_at": _dt(row.get("created_at")),
        "updated_at": _dt(row.get("updated_at")),
    }


def _source_income_payload(row: dict[str, Any], *, program: str) -> dict[str, Any]:
    member_id = row.get("member_id") or row.get("author_id")
    amount = row.get("income_amount")
    if amount is None:
        amount = row.get("settlement_amount")
    if amount is None:
        amount = row.get("income")
    if amount is None:
        amount = row.get("total_amount") or 0
    org_id = row.get("org_id") or row.get("organization_id")
    start_date = row.get("start_date") or row.get("start_time") or row.get("income_date") or row.get("task_start_time")
    end_date = row.get("end_date") or row.get("end_time")
    return {
        "id": row.get("id"),
        "organization_id": org_id,
        "org_id": org_id,
        "member_id": str(member_id) if member_id is not None else "",
        "uid": str(member_id) if member_id is not None else "",
        "member_name": row.get("member_name") or row.get("author_nickname") or "",
        "nickname": row.get("member_name") or row.get("author_nickname") or "",
        "member_head": row.get("member_head"),
        "avatar": row.get("member_head"),
        "fans_count": row.get("fans_count") or 0,
        "broker_name": row.get("broker_name") or "",
        "org_task_num": row.get("org_task_num") or 0,
        "account_id": row.get("account_id"),
        "owner_id": None,
        "user_id": None,
        "owner_username": None,
        "owner_nickname": None,
        "user_commission_rate": 100,
        "task_id": row.get("task_id") or row.get("video_id"),
        "task_name": row.get("task_name") or "",
        "income": float(amount or 0),
        "income_amount": float(amount or 0),
        "total_amount": float(row.get("total_amount") or amount or 0),
        "commission_rate": row.get("commission_rate"),
        "commission_amount": row.get("commission_amount"),
        "settlement_status": row.get("settlement_status") or "pending",
        "income_date": _dt(row.get("income_date") or start_date),
        "start_date": _dt(start_date),
        "end_date": _dt(end_date),
        "archive_year": row.get("archive_year"),
        "archive_month": row.get("archive_month"),
        "archived_at": _dt(row.get("archived_at")),
        "program": program,
        "created_at": _dt(row.get("created_at")),
    }


def _source_member_list(
    db: Session,
    user: CurrentUser,
    *,
    table: str,
    program: str,
    page: int,
    per_page: int,
    search: str | None = None,
    broker_name: str | None = None,
    org_id: int | None = None,
    sort_field: str | None = None,
    sort_order: str | None = None,
) -> tuple[list[dict[str, Any]], int]:
    where, params = _source_org_clause(user, "org_id")
    if org_id and user.is_superadmin:
        where.append("org_id = :org_id")
        params["org_id"] = org_id
    if search:
        where.append("(CAST(member_id AS CHAR) LIKE :search OR member_name LIKE :search)")
        params["search"] = f"%{search}%"
    if broker_name:
        where.append("broker_name = :broker_name")
        params["broker_name"] = broker_name
    total = _source_count(db, table, where, params)
    order_map = {
        "member_id": "member_id",
        "member_name": "member_name",
        "fans_count": "fans_count",
        "org_task_num": "org_task_num",
        "total_amount": "total_amount",
        "created_at": "created_at",
    }
    order_col = order_map.get(sort_field or "total_amount", "total_amount")
    direction = "ASC" if sort_order == "ascending" else "DESC"
    sql_where = " AND ".join(where) if where else "1=1"
    rows = db.execute(
        text(f"SELECT * FROM {table} WHERE {sql_where} ORDER BY {order_col} {direction} LIMIT :limit OFFSET :offset"),
        {**params, "limit": per_page, "offset": (page - 1) * per_page},
    ).mappings().all()
    return [_source_member_payload(dict(row), program=program) for row in rows], total


def _source_income_list(
    db: Session,
    user: CurrentUser,
    *,
    table: str,
    program: str,
    page: int,
    per_page: int,
    task_name: str | None = None,
    org_column: str | None = "org_id",
) -> tuple[list[dict[str, Any]], int]:
    where: list[str] = []
    params: dict[str, Any] = {}
    if org_column and not user.is_superadmin:
        where.append(f"{org_column} = :viewer_org_id")
        params["viewer_org_id"] = user.organization_id
    if task_name:
        name_column = "member_name" if table in {"spark_income_archive", "fluorescent_income_archive"} else "task_name"
        where.append(f"{name_column} LIKE :task_name")
        params["task_name"] = f"%{task_name}%"
    total = _source_count(db, table, where, params)
    sql_where = " AND ".join(where) if where else "1=1"
    rows = db.execute(
        text(f"SELECT * FROM {table} WHERE {sql_where} ORDER BY id DESC LIMIT :limit OFFSET :offset"),
        {**params, "limit": per_page, "offset": (page - 1) * per_page},
    ).mappings().all()
    return [_source_income_payload(dict(row), program=program) for row in rows], total


def _source_income_stats(db: Session, user: CurrentUser, *, table: str, amount_column: str, org_column: str | None = "org_id") -> dict[str, Any]:
    where: list[str] = []
    params: dict[str, Any] = {}
    if org_column and not user.is_superadmin:
        where.append(f"{org_column} = :viewer_org_id")
        params["viewer_org_id"] = user.organization_id
    sql_where = " AND ".join(where) if where else "1=1"
    row = db.execute(
        text(f"SELECT COUNT(*) AS total, COALESCE(SUM({amount_column}), 0) AS amount FROM {table} WHERE {sql_where}"),
        params,
    ).mappings().one()
    amount = float(row["amount"] or 0)
    return {
        "total": int(row["total"] or 0),
        "total_amount": amount,
        "total_income": amount,
        "settled_income": 0,
        "unsettled_income": amount,
        "total_members": int(row["total"] or 0),
    }


def _source_income_role_stats(db: Session, user: CurrentUser, *, table: str, amount_column: str, org_column: str | None = "org_id") -> dict[str, Any]:
    stats = _source_income_stats(db, user, table=table, amount_column=amount_column, org_column=org_column)
    stats["items"] = [{"role": _role_value(user), "total": stats["total"], "total_amount": stats["total_amount"]}]
    return stats


def _source_income_wallet_stats(db: Session, user: CurrentUser, *, table: str, amount_column: str, org_column: str | None = "org_id") -> dict[str, Any]:
    stats = _source_income_stats(db, user, table=table, amount_column=amount_column, org_column=org_column)
    wallets = _count(db, select(WalletProfile))
    stats.update({"wallet_count": wallets, "missing_wallet_count": 0})
    return stats


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
    if source_mysql_service.is_source_mysql(db):
        account_where, account_params = _source_org_clause(user, "organization_id")
        account_sql = " AND ".join(account_where) if account_where else "1=1"
        account_row = db.execute(
            text(
                f"""
                SELECT COUNT(*) AS total_accounts,
                       SUM(CASE WHEN is_mcm_member = 1 THEN 1 ELSE 0 END) AS mcn_accounts
                FROM kuaishou_accounts
                WHERE {account_sql}
                """
            ),
            account_params,
        ).mappings().one()

        task_where: list[str] = []
        task_params: dict[str, Any] = {}
        if not user.is_superadmin:
            task_where.append(
                """
                EXISTS (
                    SELECT 1 FROM kuaishou_accounts ka
                    WHERE ka.organization_id = :viewer_org_id
                      AND (ka.uid = ts.uid OR ka.uid_real = ts.uid)
                )
                """
            )
            task_params["viewer_org_id"] = user.organization_id
        task_sql = " AND ".join(task_where) if task_where else "1=1"
        task_row = db.execute(
            text(
                f"""
                SELECT COUNT(*) AS total_executions,
                       SUM(CASE WHEN DATE(created_at) = CURDATE() THEN 1 ELSE 0 END) AS today_executions,
                       SUM(CASE WHEN status = 'success' THEN 1 ELSE 0 END) AS success_count,
                       SUM(CASE WHEN status = 'failed' THEN 1 ELSE 0 END) AS failed_count
                FROM task_statistics ts
                WHERE {task_sql}
                """
            ),
            task_params,
        ).mappings().one()
        trend_rows = db.execute(
            text(
                f"""
                SELECT DATE(created_at) AS stat_date, COUNT(*) AS total_count
                FROM task_statistics ts
                WHERE {task_sql}
                GROUP BY DATE(created_at)
                ORDER BY stat_date DESC
                LIMIT 7
                """
            ),
            task_params,
        ).mappings().all()
        trend = list(reversed(trend_rows))
        return _success(
            {
                "accounts": {
                    "total": int(account_row["total_accounts"] or 0),
                    "mcn_members": int(account_row["mcn_accounts"] or 0),
                },
                "executions": {
                    "total": int(task_row["total_executions"] or 0),
                    "today": int(task_row["today_executions"] or 0),
                    "success": int(task_row["success_count"] or 0),
                    "failed": int(task_row["failed_count"] or 0),
                },
                "trend": {
                    "labels": [str(row["stat_date"]) for row in trend],
                    "values": [int(row["total_count"] or 0) for row in trend],
                },
                "showSystemStatus": True,
            }
        )
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
    if source_mysql_service.is_source_mysql(db):
        days = max(1, min(int(days or 30), 365))
        task_where = ["created_at >= DATE_SUB(CURDATE(), INTERVAL :days DAY)"]
        params: dict[str, Any] = {"days": days}
        if not user.is_superadmin:
            task_where.append(
                """
                EXISTS (
                    SELECT 1 FROM kuaishou_accounts ka
                    WHERE ka.organization_id = :viewer_org_id
                      AND (ka.uid = ts.uid OR ka.uid_real = ts.uid)
                )
                """
            )
            params["viewer_org_id"] = user.organization_id
        sql_where = " AND ".join(task_where)
        row = db.execute(
            text(
                f"""
                SELECT COUNT(*) AS total_count,
                       SUM(CASE WHEN status = 'success' THEN 1 ELSE 0 END) AS success_count,
                       SUM(CASE WHEN status = 'failed' THEN 1 ELSE 0 END) AS failed_count
                FROM task_statistics ts
                WHERE {sql_where}
                """
            ),
            params,
        ).mappings().one()
        daily_rows = db.execute(
            text(
                f"""
                SELECT DATE(created_at) AS stat_date,
                       COUNT(*) AS total_count,
                       SUM(CASE WHEN status = 'success' THEN 1 ELSE 0 END) AS success_count,
                       SUM(CASE WHEN status = 'failed' THEN 1 ELSE 0 END) AS failed_count
                FROM task_statistics ts
                WHERE {sql_where}
                GROUP BY DATE(created_at)
                ORDER BY stat_date ASC
                """
            ),
            params,
        ).mappings().all()
        total = int(row["total_count"] or 0)
        success = int(row["success_count"] or 0)
        failed = int(row["failed_count"] or 0)
        daily_stats = []
        for item in daily_rows:
            day_total = int(item["total_count"] or 0)
            day_success = int(item["success_count"] or 0)
            day_failed = int(item["failed_count"] or 0)
            daily_stats.append(
                {
                    "date": str(item["stat_date"]),
                    "total_count": day_total,
                    "success_count": day_success,
                    "failed_count": day_failed,
                    "success_rate": round(day_success / day_total * 100, 2) if day_total else 0,
                }
            )
        return _success(
            {
                "summary": {
                    "total_count": total,
                    "success_count": success,
                    "failed_count": failed,
                    "success_rate": round(success / total * 100, 2) if total else 0,
                    "days": days,
                },
                "daily_stats": daily_stats,
            }
        )
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
    if source_mysql_service.is_source_mysql(db):
        row = db.execute(
            text(
                """
                SELECT id, username, nickname, phone, alipay_info, updated_at, created_at
                FROM admin_users
                WHERE id = :user_id
                LIMIT 1
                """
            ),
            {"user_id": user.id},
        ).mappings().first()
        info = _parse_alipay_info(row["alipay_info"] if row else None)
        return _success(
            {
                "alipay_name": info.get("alipay_name") or info.get("real_name") or (row["nickname"] if row else ""),
                "alipay_account": info.get("alipay_account") or info.get("account") or (row["phone"] if row else ""),
                "bank_name": info.get("bank_name") or "",
                "bank_account": info.get("bank_account") or "",
                "real_name": info.get("real_name") or (row["nickname"] if row else ""),
                "notes": info.get("notes") or "",
                "source": "admin_users.alipay_info",
            }
        )
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


def _parse_alipay_info(value: Any) -> dict[str, Any]:
    if not value:
        return {}
    if isinstance(value, dict):
        return value
    text_value = str(value).strip()
    if not text_value:
        return {}
    try:
        parsed = json.loads(text_value)
    except json.JSONDecodeError:
        return {"notes": text_value}
    return parsed if isinstance(parsed, dict) else {"notes": text_value}


def _source_wallet_payload(row: Any) -> dict[str, Any]:
    info = _parse_alipay_info(row.get("alipay_info"))
    display_name = row.get("nickname") or row.get("username") or ""
    phone = row.get("phone") or ""
    return {
        "id": row.get("id"),
        "user_id": row.get("id"),
        "username": row.get("username"),
        "nickname": display_name,
        "display_name": display_name,
        "phone": phone,
        "alipay_name": info.get("alipay_name") or info.get("real_name") or display_name,
        "alipay_account": info.get("alipay_account") or info.get("account") or phone,
        "bank_name": info.get("bank_name") or "",
        "bank_account": info.get("bank_account") or "",
        "real_name": info.get("real_name") or display_name,
        "notes": info.get("notes") or "",
        "has_wallet": bool(row.get("alipay_info")),
        "created_at": _dt(row.get("created_at")),
        "updated_at": _dt(row.get("updated_at")),
        "source": "admin_users.alipay_info",
    }


@router.get("/wallet-info")
async def wallet_info(
    db: DbSession,
    user: CurrentUser,
    page: int = 1,
    page_size: int | None = None,
    size: int | None = None,
    search: str | None = None,
):
    page, per_page = _page_size(page, page_size, size)
    if source_mysql_service.is_source_mysql(db):
        where = ["1=1"]
        params: dict[str, Any] = {}
        if not user.is_superadmin:
            where.append("organization_access = :viewer_org_id")
            params["viewer_org_id"] = user.organization_id
        if search:
            where.append("(username LIKE :search OR nickname LIKE :search OR phone LIKE :search OR alipay_info LIKE :search)")
            params["search"] = f"%{search}%"
        sql_where = " AND ".join(where)
        total = int(db.execute(text(f"SELECT COUNT(*) FROM admin_users WHERE {sql_where}"), params).scalar_one())
        rows = db.execute(
            text(
                f"""
                SELECT id, username, nickname, phone, alipay_info, created_at, updated_at
                FROM admin_users
                WHERE {sql_where}
                ORDER BY id DESC
                LIMIT :limit OFFSET :offset
                """
            ),
            {**params, "limit": per_page, "offset": (page - 1) * per_page},
        ).mappings().all()
        return _success([_source_wallet_payload(dict(row)) for row in rows], total=total, pagination={"total": total, "page": page, "page_size": per_page})

    stmt = select(WalletProfile)
    if not user.is_superadmin:
        stmt = stmt.where(WalletProfile.user_id == user.id)
    total = _count(db, stmt)
    rows = db.execute(stmt.order_by(WalletProfile.id.desc()).offset((page - 1) * per_page).limit(per_page)).scalars().all()
    data = [
        {
            "id": row.id,
            "user_id": row.user_id,
            "alipay_name": row.alipay_name,
            "alipay_account": row.alipay_account,
            "bank_name": row.bank_name,
            "bank_account": row.bank_account,
            "real_name": row.real_name,
            "notes": row.notes,
            "created_at": _dt(row.created_at),
            "updated_at": _dt(row.updated_at),
        }
        for row in rows
    ]
    return _success(data, total=total, pagination={"total": total, "page": page, "page_size": per_page})


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
    if source_mysql_service.is_source_mysql(db):
        explicit_page_size = pageSize or page_size or size
        if explicit_page_size is None or include_all:
            per_page = 100000
        else:
            page, per_page = _page_size(page, pageSize or page_size, size)
        rows, total = source_mysql_service.list_users(
            db,
            viewer=user,
            page=page,
            per_page=per_page,
            search=search,
            role=role,
            is_active=is_active,
            organization_id=organization_id,
            parent_user_id=parent_user_id,
            has_parent=has_parent,
        )
        data = [_user_payload(row) for row in rows]
        return _success(data, total=total, pagination={"total": total, "page": page, "page_size": per_page})
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
    if source_mysql_service.is_source_mysql(db):
        new_user = source_mysql_service.create_user(
            db,
            {
                "username": username,
                "password_hash": hash_password(str(password)),
                "password_salt": "",
                "nickname": body.get("nickname") or body.get("display_name") or username,
                "role": role,
                "is_active": 1 if bool(body.get("is_active", 1)) else 0,
                "avatar": "",
                "email": body.get("email") or "",
                "phone": body.get("phone") or "",
                "default_auth_code": body.get("default_auth_code") or body.get("auth_code") or "",
                "user_level": "enterprise" if int(body.get("quota", -1) or -1) == -1 else "normal",
                "quota": int(body.get("quota", -1) or -1),
                "parent_user_id": body.get("parent_user_id"),
                "commission_rate": float(body.get("commission_rate") or 100),
                "commission_rate_visible": 1 if bool(body.get("commission_rate_visible", 0)) else 0,
                "commission_amount_visible": 1 if bool(body.get("commission_amount_visible", 0)) else 0,
                "total_income_visible": 1 if bool(body.get("total_income_visible", 0)) else 0,
                "organization_access": int(body.get("organization_id") or body.get("organization_access") or user.organization_id),
            },
        )
        return _success(_user_payload(new_user))
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
    if source_mysql_service.is_source_mysql(db):
        target_ids = [
            item for item in ids
            if (row := source_mysql_service.get_user_by_id(db, item)) is not None and row.username != "admin"
        ]
        source_mysql_service.batch_update_users(db, target_ids, {"is_active": 0})
        return _success({"deleted": len(target_ids)})
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
    is_active = _as_bool(body.get("is_active"), True)
    if source_mysql_service.is_source_mysql(db):
        source_mysql_service.batch_update_users(db, ids, {"is_active": 1 if is_active else 0})
        return _success({"updated": len(ids), "is_active": is_active})
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
    if source_mysql_service.is_source_mysql(db):
        source_mysql_service.batch_update_users(db, ids, {"password_hash": hash_password(password)})
        return _success({"updated": len(ids)})
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
    if source_mysql_service.is_source_mysql(db):
        fields: dict[str, Any] = {}
        if role:
            fields["role"] = role
        if parent_id is not None:
            fields["parent_user_id"] = parent_id
        source_mysql_service.batch_update_users(db, ids, fields)
        return _success({"updated": len(ids)})
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
    if source_mysql_service.is_source_mysql(db):
        source_mysql_service.batch_update_users(db, ids, {"parent_user_id": parent_id})
        return _success({"updated": len(ids)})
    rows = db.execute(select(User).where(User.id.in_(ids))).scalars().all()
    for row in rows:
        row.parent_user_id = parent_id
    db.commit()
    return _success({"updated": len(rows)})


@router.post("/auth/users/batch-update-commission-rate")
async def batch_update_user_commission_rate(request: Request, db: DbSession):
    body = await request.json()
    ids = [int(item) for item in body.get("user_ids", body.get("ids", [])) if str(item).isdigit()]
    rate = _as_float(body.get("commission_rate"), 0.0)
    if source_mysql_service.is_source_mysql(db):
        source_mysql_service.batch_update_users(db, ids, {"commission_rate": rate if rate > 1 else rate * 100})
        return _success({"updated": len(ids)})
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
    if source_mysql_service.is_source_mysql(db):
        fields: dict[str, Any] = {}
        if "commission_rate_visible" in body:
            fields["commission_rate_visible"] = 1 if _as_bool(body.get("commission_rate_visible")) else 0
        if "commission_amount_visible" in body:
            fields["commission_amount_visible"] = 1 if _as_bool(body.get("commission_amount_visible")) else 0
        if "total_income_visible" in body:
            fields["total_income_visible"] = 1 if _as_bool(body.get("total_income_visible")) else 0
        source_mysql_service.batch_update_users(db, ids, fields)
        return _success({"updated": len(ids)})
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
    if source_mysql_service.is_source_mysql(db):
        source_mysql_service.batch_update_users(db, ids, {"organization_access": org_id})
        return _success({"updated": len(ids)})
    rows = db.execute(select(User).where(User.id.in_(ids))).scalars().all()
    for row in rows:
        row.organization_id = org_id
    db.commit()
    return _success({"updated": len(rows)})


@router.post("/auth/users/batch-change-level")
async def batch_change_user_level(request: Request, db: DbSession):
    body = await request.json()
    ids = [int(item) for item in body.get("user_ids", body.get("ids", [])) if str(item).isdigit()]
    user_level = body.get("user_level") or "normal"
    if source_mysql_service.is_source_mysql(db):
        quota = -1 if user_level == "enterprise" else _as_int(body.get("quota"), 10)
        source_mysql_service.batch_update_users(db, ids, {"user_level": user_level, "quota": quota})
        return _success({"updated": len(ids)})
    quota = None if user_level == "enterprise" else 10
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
    if source_mysql_service.is_source_mysql(db):
        quota_value = -1 if quota in (None, -1, "-1") else int(quota)
        user_level = "enterprise" if quota_value == -1 else "normal"
        source_mysql_service.batch_update_users(db, ids, {"quota": quota_value, "user_level": user_level})
        return _success({"updated": len(ids)})
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
    if source_mysql_service.is_source_mysql(db):
        rows, _total = source_mysql_service.list_users(
            db,
            viewer=user,
            page=1,
            per_page=100000,
            role="operator",
        )
        return _success([_user_payload(row) for row in rows])
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
    if source_mysql_service.is_source_mysql(db):
        target = source_mysql_service.get_user_by_id(db, target_user_id)
        return _success({"auth_code": target.default_auth_code or target.username if target else ""})
    target = db.get(User, target_user_id)
    return _success({"auth_code": target.phone or target.username if target else ""})


@router.put("/auth/users/{target_user_id}/auth-code")
async def set_user_auth_code(target_user_id: int, request: Request, db: DbSession):
    body = await request.json()
    if source_mysql_service.is_source_mysql(db):
        target = source_mysql_service.update_user_fields(
            db,
            target_user_id,
            {"default_auth_code": body.get("auth_code") or ""},
        )
        if target is None:
            return _success(None, message="用户不存在")
        return _success({"auth_code": target.default_auth_code or target.username})
    target = db.get(User, target_user_id)
    if target is None:
        return _success(None, message="用户不存在")
    target.phone = body.get("auth_code") or target.phone
    db.commit()
    return _success({"auth_code": target.phone or target.username})


@router.get("/auth/users/{target_user_id}/organizations")
async def user_organizations(target_user_id: int, db: DbSession):
    if source_mysql_service.is_source_mysql(db):
        target = source_mysql_service.get_user_by_id(db, target_user_id)
        return _success({"organization_id": target.organization_id if target else None})
    target = db.get(User, target_user_id)
    return _success({"organization_id": target.organization_id if target else None})


@router.put("/auth/users/{target_user_id}/organizations")
async def set_user_organizations(target_user_id: int, request: Request, db: DbSession):
    body = await request.json()
    if source_mysql_service.is_source_mysql(db):
        target = source_mysql_service.update_user_fields(
            db,
            target_user_id,
            {"organization_access": body.get("organization_id")},
        )
        if target is None:
            return _success(None, message="用户不存在")
        return _success(_user_payload(target))
    target = db.get(User, target_user_id)
    if target is None:
        return _success(None, message="用户不存在")
    target.organization_id = body.get("organization_id") or target.organization_id
    db.commit()
    return _success(_user_payload(target))


@router.put("/auth/users/{target_user_id}")
async def update_user(target_user_id: int, request: Request, db: DbSession):
    body = await request.json()
    if source_mysql_service.is_source_mysql(db):
        fields: dict[str, Any] = {
            "nickname": body.get("nickname") or body.get("display_name"),
            "email": body.get("email"),
            "phone": body.get("phone"),
        }
        if body.get("organization_id") is not None:
            fields["organization_access"] = body.get("organization_id")
        if body.get("parent_user_id") is not None:
            fields["parent_user_id"] = body.get("parent_user_id")
        if body.get("role"):
            fields["role"] = body.get("role")
        target = source_mysql_service.update_user_fields(
            db,
            target_user_id,
            {key: value for key, value in fields.items() if value is not None},
        )
        if target is None:
            return _success(None, message="用户不存在")
        return _success(_user_payload(target))
    target = db.get(User, target_user_id)
    if target is None:
        return _success(None, message="用户不存在")
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
    if source_mysql_service.is_source_mysql(db):
        target = source_mysql_service.get_user_by_id(db, target_user_id)
        if target and target.username != "admin":
            source_mysql_service.update_user_fields(db, target_user_id, {"is_active": 0})
        return _success({"deleted": True})
    target = db.get(User, target_user_id)
    if target and target.username != "admin":
        target.is_active = False
        target.deleted_at = datetime.utcnow()
        db.commit()
    return _success({"deleted": True})


@router.put("/auth/users/{target_user_id}/status")
async def update_user_status(target_user_id: int, request: Request, db: DbSession):
    body = await request.json()
    if source_mysql_service.is_source_mysql(db):
        current = source_mysql_service.get_user_by_id(db, target_user_id)
        if current is None:
            return _success(None, message="用户不存在")
        target = source_mysql_service.update_user_fields(
            db,
            target_user_id,
            {"is_active": 1 if _as_bool(body.get("is_active"), not current.is_active) else 0},
        )
        return _success(_user_payload(target))
    target = db.get(User, target_user_id)
    if target is None:
        return _success(None, message="用户不存在")
    target.is_active = bool(body.get("is_active", not target.is_active))
    db.commit()
    return _success(_user_payload(target))


@router.post("/auth/users/{target_user_id}/reset-password")
async def reset_user_password(target_user_id: int, request: Request, db: DbSession):
    body = await request.json()
    if source_mysql_service.is_source_mysql(db):
        target = source_mysql_service.update_user_fields(
            db,
            target_user_id,
            {"password_hash": hash_password(str(body.get("new_password") or body.get("password") or "123456"))},
        )
        if target is None:
            return _success(None, message="用户不存在")
        return _success({"updated": True})
    target = db.get(User, target_user_id)
    if target is None:
        return _success(None, message="用户不存在")
    target.password_hash = hash_password(str(body.get("new_password") or body.get("password") or "123456"))
    target.must_change_pw = True
    db.commit()
    return _success({"updated": True})


@router.post("/auth/users/{target_user_id}/assign-to-operator")
async def assign_user_to_operator(target_user_id: int, request: Request, db: DbSession):
    body = await request.json()
    if source_mysql_service.is_source_mysql(db):
        target = source_mysql_service.update_user_fields(
            db,
            target_user_id,
            {"parent_user_id": body.get("target_operator_id") or body.get("parent_user_id")},
        )
        if target is None:
            return _success(None, message="用户不存在")
        return _success(_user_payload(target))
    target = db.get(User, target_user_id)
    if target is None:
        return _success(None, message="用户不存在")
    target.parent_user_id = body.get("target_operator_id") or body.get("parent_user_id")
    db.commit()
    return _success(_user_payload(target))


@router.post("/auth/users/{target_user_id}/change-role")
async def change_user_role(target_user_id: int, request: Request, db: DbSession):
    body = await request.json()
    role = body.get("new_role") or body.get("role")
    if source_mysql_service.is_source_mysql(db):
        fields: dict[str, Any] = {}
        if role:
            fields["role"] = role
        if body.get("target_operator_id") is not None:
            fields["parent_user_id"] = body.get("target_operator_id")
        target = source_mysql_service.update_user_fields(db, target_user_id, fields)
        if target is None:
            return _success(None, message="用户不存在")
        return _success(_user_payload(target))
    target = db.get(User, target_user_id)
    if target is None:
        return _success(None, message="用户不存在")
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
    body = await request.json()
    if source_mysql_service.is_source_mysql(db):
        current = source_mysql_service.get_user_by_id(db, target_user_id)
        if current is None:
            return _success(None, message="用户不存在")
        rate = _as_float(body.get("commission_rate"), current.commission_rate)
        target = source_mysql_service.update_user_fields(
            db,
            target_user_id,
            {"commission_rate": rate if rate > 1 else rate * 100},
        )
        return _success(_user_payload(target))
    target = db.get(User, target_user_id)
    if target is None:
        return _success(None, message="用户不存在")
    rate = float(body.get("commission_rate") or target.commission_rate)
    target.commission_rate = rate / 100 if rate > 1 else rate
    db.commit()
    return _success(_user_payload(target))


@router.put("/auth/users/{target_user_id}/commission-visibility")
async def update_user_commission_visibility(target_user_id: int, request: Request, db: DbSession):
    body = await request.json()
    if source_mysql_service.is_source_mysql(db):
        target = source_mysql_service.update_user_fields(
            db,
            target_user_id,
            {
                "commission_rate_visible": 1 if _as_bool(body.get("commission_rate_visible"), False) else 0,
                "commission_amount_visible": 1 if _as_bool(body.get("commission_amount_visible"), False) else 0,
                "total_income_visible": 1 if _as_bool(body.get("total_income_visible"), False) else 0,
            },
        )
        if target is None:
            return _success(None, message="用户不存在")
        return _success(_user_payload(target))
    target = db.get(User, target_user_id)
    if target is None:
        return _success(None, message="用户不存在")
    target.commission_rate_visible = bool(body.get("commission_rate_visible", target.commission_rate_visible))
    target.commission_amount_visible = bool(body.get("commission_amount_visible", target.commission_amount_visible))
    target.total_income_visible = bool(body.get("total_income_visible", target.total_income_visible))
    db.commit()
    return _success(_user_payload(target))


@router.put("/auth/users/{target_user_id}/quota")
async def update_user_quota(target_user_id: int, request: Request, db: DbSession):
    body = await request.json()
    quota = body.get("quota")
    if source_mysql_service.is_source_mysql(db):
        quota_value = -1 if quota in (None, -1, "-1") else int(quota)
        target = source_mysql_service.update_user_fields(
            db,
            target_user_id,
            {"quota": quota_value, "user_level": "enterprise" if quota_value == -1 else "normal"},
        )
        if target is None:
            return _success(None, message="用户不存在")
        return _success(_user_payload(target))
    target = db.get(User, target_user_id)
    if target is None:
        return _success(None, message="用户不存在")
    target.account_quota = None if quota in (None, -1, "-1") else int(quota)
    db.commit()
    return _success(_user_payload(target))


@router.put("/auth/users/{target_user_id}/level")
@router.post("/auth/users/{target_user_id}/upgrade")
@router.put("/auth/users/{target_user_id}/upgrade")
async def update_user_level(target_user_id: int, db: DbSession):
    if source_mysql_service.is_source_mysql(db):
        target = source_mysql_service.update_user_fields(
            db,
            target_user_id,
            {"quota": -1, "user_level": "enterprise"},
        )
        if target is None:
            return _success(None, message="用户不存在")
        return _success(_user_payload(target))
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
    return _success(ROLE_CATALOG)


@router.get("/auth/permissions")
async def permissions(db: DbSession):
    return _success(ROLE_FEATURES)


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
    pageSize: int | None = None,
    page_size: int | None = None,
    size: int | None = None,
    action: str | None = None,
    module: str | None = None,
):
    page, per_page = _page_size(page, page_size or pageSize, size)
    if source_mysql_service.is_source_mysql(db):
        where: list[str] = []
        params: dict[str, Any] = {}
        if action:
            where.append("action = :action")
            params["action"] = action
        if module:
            where.append("module = :module")
            params["module"] = module
        sql_where = " AND ".join(where) if where else "1=1"
        total = int(db.execute(text(f"SELECT COUNT(*) FROM admin_operation_logs WHERE {sql_where}"), params).scalar_one())
        rows = db.execute(
            text(f"SELECT * FROM admin_operation_logs WHERE {sql_where} ORDER BY id DESC LIMIT :limit OFFSET :offset"),
            {**params, "limit": per_page, "offset": (page - 1) * per_page},
        ).mappings().all()
        data = [
            {
                "id": row["id"],
                "user_id": row["user_id"],
                "username": row["username"],
                "organization_id": None,
                "action": row["action"],
                "module": row["module"],
                "target_type": row["target"],
                "target_id": row["target"],
                "detail": row["detail"],
                "ip": row["ip"],
                "user_agent": row["user_agent"],
                "success": 1 if row["status"] == "success" else 0,
                "status": row["status"],
                "created_at": _dt(row["created_at"]),
            }
            for row in rows
        ]
        return _success({"logs": data, "total": total}, total=total, pagination={"total": total, "page": page, "page_size": per_page})
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
    if source_mysql_service.is_source_mysql(db):
        row = db.execute(
            text(
                """
                SELECT COUNT(*) AS total,
                       SUM(CASE WHEN DATE(created_at) = CURDATE() THEN 1 ELSE 0 END) AS today,
                       SUM(CASE WHEN status <> 'success' THEN 1 ELSE 0 END) AS errors
                FROM admin_operation_logs
                """
            )
        ).mappings().one()
        return _success({"today": int(row["today"] or 0), "total": int(row["total"] or 0), "errors": int(row["errors"] or 0)})
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
    if source_mysql_service.is_source_mysql(db):
        rows = db.execute(
            text(
                """
                SELECT role, perm_type, perm_key, is_allowed
                FROM role_default_permissions
                WHERE role = :role
                ORDER BY perm_type ASC, perm_key ASC
                """
            ),
            {"role": role},
        ).mappings().all()
        if role in {"super_admin", "superadmin", "admin"} and not rows:
            rows = db.execute(
                text(
                    """
                    SELECT :role AS role, perm_type, perm_key, 1 AS is_allowed
                    FROM (
                        SELECT DISTINCT perm_type, perm_key
                        FROM role_default_permissions
                    ) p
                    ORDER BY perm_type ASC, perm_key ASC
                    """
                ),
                {"role": role},
            ).mappings().all()
        all_rows = db.execute(
            text("SELECT DISTINCT perm_type, perm_key FROM role_default_permissions ORDER BY perm_type ASC, perm_key ASC")
        ).mappings().all()
        meta = {
            "account_buttons": [_permission_payload(row["perm_key"], 1) for row in all_rows if row["perm_type"] == "account_button"],
            "user_mgmt_buttons": [_permission_payload(row["perm_key"], 1) for row in all_rows if row["perm_type"] == "user_mgmt_button"],
            "web_pages": [_permission_payload(row["perm_key"], 1) for row in all_rows if row["perm_type"] == "web_page"],
            "client_pages": [_permission_payload(row["perm_key"], 1) for row in all_rows if row["perm_type"] == "client_page"],
        }
        return _success(
            {
                "role": role,
                "permissions": [
                    {
                        **_permission_payload(row["perm_key"], int(row["is_allowed"] or 0)),
                        "key": row["perm_key"],
                        "perm_key": row["perm_key"],
                        "permission_type": row["perm_type"],
                        "perm_type": row["perm_type"],
                        "is_allowed": int(row["is_allowed"] or 0),
                    }
                    for row in rows
                ],
                "meta": meta,
            }
        )
    rows = db.execute(
        select(DefaultRolePermission).where(DefaultRolePermission.role == role).order_by(DefaultRolePermission.permission_type.asc(), DefaultRolePermission.permission_code.asc())
    ).scalars().all()
    return _success(
        {
            "role": role,
            "permissions": [
                {
                    **_permission_payload(row.permission_code, row.granted),
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
    if source_mysql_service.is_source_mysql(db):
        updated = 0
        for item in req.permissions:
            code = item.get("perm_key") or item.get("button_key") or item.get("page_key") or item.get("key")
            code = str(code).strip() if code is not None else ""
            if not code:
                continue
            perm_type = str(item.get("perm_type") or item.get("permission_type") or ("web_page" if code.startswith("page:") else "account_button"))
            granted = 1 if item.get("is_allowed") in (True, 1, "1", "true", "True") else 0
            db.execute(
                text(
                    """
                    INSERT INTO role_default_permissions (role, perm_type, perm_key, is_allowed, created_at, updated_at)
                    VALUES (:role, :perm_type, :perm_key, :is_allowed, NOW(), NOW())
                    ON DUPLICATE KEY UPDATE is_allowed = VALUES(is_allowed), updated_at = NOW()
                    """
                ),
                {"role": role, "perm_type": perm_type, "perm_key": code, "is_allowed": granted},
            )
            updated += 1
        db.commit()
        return _success({"updated": updated})
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
    if source_mysql_service.is_source_mysql(db):
        rows = source_mysql_service.list_organizations(db, user)
        return _success([_organization_payload(row) for row in rows])
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
    if source_mysql_service.is_source_mysql(db):
        org = source_mysql_service.create_organization(
            db,
            {
                "name": name,
                "org_code": code,
                "description": body.get("notes") or body.get("description") or "",
                "is_active": 1 if _as_bool(body.get("is_active"), True) else 0,
            },
        )
        return _success(_organization_payload(org))
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
    body = await request.json()
    if source_mysql_service.is_source_mysql(db):
        fields = {
            "org_name": body.get("name") or body.get("org_name"),
            "org_code": body.get("org_code") or body.get("code"),
            "description": body.get("notes") or body.get("description"),
        }
        if "is_active" in body:
            fields["is_active"] = 1 if _as_bool(body.get("is_active")) else 0
        org = source_mysql_service.update_organization_fields(
            db, org_id, {key: value for key, value in fields.items() if value is not None}
        )
        if org is None:
            return _success(None, message="机构不存在")
        return _success(_organization_payload(org))
    org = db.get(Organization, org_id)
    if org is None:
        return _success(None, message="机构不存在")
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
    if source_mysql_service.is_source_mysql(db):
        current = source_mysql_service.get_organization_by_id(db, org_id)
        if current is None:
            return _success(None, message="机构不存在")
        org = source_mysql_service.update_organization_fields(
            db, org_id, {"is_active": 0 if current.is_active else 1}
        )
        return _success(_organization_payload(org))
    org = db.get(Organization, org_id)
    if org is None:
        return _success(None, message="机构不存在")
    org.is_active = not bool(org.is_active)
    db.commit()
    return _success(_organization_payload(org))


@router.put("/organizations/{org_id}/org-code")
async def update_organization_code(org_id: int, request: Request, db: DbSession):
    body = await request.json()
    if source_mysql_service.is_source_mysql(db):
        org = source_mysql_service.update_organization_fields(
            db, org_id, {"org_code": body.get("org_code")}
        )
        if org is None:
            return _success(None, message="机构不存在")
        return _success(_organization_payload(org))
    org = db.get(Organization, org_id)
    if org is None:
        return _success(None, message="机构不存在")
    org.org_code = body.get("org_code") or org.org_code
    db.commit()
    return _success(_organization_payload(org))


@router.delete("/organizations/{org_id}")
async def delete_organization(org_id: int, db: DbSession):
    if source_mysql_service.is_source_mysql(db):
        org = source_mysql_service.update_organization_fields(db, org_id, {"is_active": 0})
        if org is None:
            return _success(None, message="机构不存在")
        return _success({"deleted": False, "disabled": True}, message="机构已停用，未从数据库删除")
    org = db.get(Organization, org_id)
    if org is None:
        return _success(None, message="机构不存在")
    # Business rule from production sync: organizations are preserved and only disabled.
    org.is_active = False
    db.commit()
    return _success({"deleted": False, "disabled": True}, message="机构已停用，未从数据库删除")


@router.get("/groups")
async def groups(db: DbSession, user: CurrentUser):
    if source_mysql_service.is_source_mysql(db):
        rows, counts, ungrouped = source_mysql_service.list_groups(db, user)
        group_rows = [_group_payload(row, counts.get(row.id, 0)) for row in rows]
        return _success({"groups": group_rows, "tree_data": group_rows, "ungrouped_count": ungrouped})
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
    if source_mysql_service.is_source_mysql(db):
        group = source_mysql_service.create_group(
            db,
            {
                "group_name": name,
                "color": body.get("color"),
                "owner_id": body.get("owner_id") or body.get("owner_user_id") or user.id,
                "description": body.get("description") or "",
            },
        )
        return _success(_group_payload(group))
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
    body = await request.json()
    if source_mysql_service.is_source_mysql(db):
        fields = {
            "group_name": body.get("group_name") or body.get("name"),
            "color": body.get("color"),
            "owner_id": body.get("owner_id"),
        }
        group = source_mysql_service.update_group_fields(
            db, group_id, {key: value for key, value in fields.items() if value is not None}
        )
        if group is None:
            return _success(None, message="分组不存在")
        return _success(_group_payload(group))
    group = db.get(AccountGroup, group_id)
    if group is None:
        return _success(None, message="分组不存在")
    group.name = body.get("group_name") or body.get("name") or group.name
    group.color = body.get("color", group.color)
    if body.get("owner_id") is not None:
        group.owner_user_id = body.get("owner_id")
    db.commit()
    return _success(_group_payload(group))


@router.delete("/groups/{group_id}")
async def delete_group(group_id: int, db: DbSession):
    if source_mysql_service.is_source_mysql(db):
        source_mysql_service.delete_group(db, group_id)
        return _success({"deleted": True})
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
    if source_mysql_service.is_source_mysql(db):
        updated = source_mysql_service.assign_accounts_to_group(db, group_id, uids)
        return _success({"updated": updated})
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
    pageSize: int | None = None,
    page_size: int | None = None,
    size: int | None = None,
    search: str | None = None,
    keyword: str | None = None,
    organization_id: int | None = None,
    org_id: int | None = None,
    group_id: int | None = None,
    owner_id: int | None = None,
):
    if source_mysql_service.is_source_mysql(db):
        page, per_page = _page_size(page, page_size or pageSize, size)
        rows, total, mcn_count = source_mysql_service.list_accounts(
            db,
            viewer=user,
            page=page,
            per_page=per_page,
            term=search or keyword,
            organization_id=organization_id or org_id,
            group_id=group_id,
            owner_id=owner_id,
        )
        data = {
            "accounts": [_account_payload(row) for row in rows],
            "total": total,
            "mcn_count": mcn_count,
            "normal_count": max(total - mcn_count, 0),
            "user_role": "super_admin" if user.is_superadmin else user.role,
        }
        return _success(data)
    page, per_page = _page_size(page, page_size or pageSize, size)
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
    if source_mysql_service.is_source_mysql(db):
        account = source_mysql_service.create_account(
            db,
            {
                "uid": str(body.get("kuaishou_id") or uid),
                "uid_real": str(body.get("real_uid") or body.get("uid_real") or uid),
                "device_serial": body.get("device_serial") or body.get("device_code"),
                "nickname": body.get("nickname"),
                "is_mcm_member": 1 if _as_bool(body.get("is_mcm_member") or body.get("is_mcn_member"), False) else 0,
                "group_id": body.get("group_id"),
                "owner_id": body.get("owner_id") or body.get("user_id") or body.get("assigned_user_id"),
                "account_status": body.get("status") or body.get("account_status") or "normal",
                "status_note": body.get("remark"),
                "contract_status": body.get("sign_status") or body.get("contract_status"),
                "org_note": body.get("remark"),
                "organization_id": org_id,
                "commission_rate": _as_float(body.get("commission_rate") or body.get("account_commission_rate"), 80.0),
            },
        )
        return _success(_account_payload(account))
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
    if source_mysql_service.is_source_mysql(db):
        for item in raw_accounts:
            if isinstance(item, str):
                item = {"uid": item}
            uid = str(item.get("uid") or item.get("kuaishou_id") or item.get("real_uid") or "").strip()
            if not uid:
                continue
            result = source_mysql_service.create_or_update_account_by_uid(
                db,
                uid,
                {
                    "uid": str(item.get("kuaishou_id") or uid),
                    "uid_real": str(item.get("real_uid") or item.get("uid_real") or uid),
                    "device_serial": item.get("device_serial") or item.get("device_code"),
                    "nickname": item.get("nickname"),
                    "is_mcm_member": 1 if _as_bool(item.get("is_mcm_member") or item.get("is_mcn_member"), False) else 0,
                    "group_id": item.get("group_id"),
                    "owner_id": item.get("owner_id") or item.get("user_id") or item.get("assigned_user_id"),
                    "account_status": item.get("status") or item.get("account_status") or "normal",
                    "status_note": item.get("remark"),
                    "contract_status": item.get("sign_status") or item.get("contract_status"),
                    "org_note": item.get("remark"),
                    "organization_id": int(item.get("organization_id") or org_id),
                    "commission_rate": _as_float(item.get("commission_rate") or item.get("account_commission_rate"), 80.0),
                },
            )
            if result == "created":
                created += 1
            else:
                updated += 1
        return _success({"created": created, "updated": updated})
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
    if source_mysql_service.is_source_mysql(db):
        updated = source_mysql_service.batch_update_accounts(
            db, _body_ids(body), {"owner_id": target_user_id}
        )
        return _success({"updated": updated})
    accounts_to_update = db.execute(_account_stmt_for_ids(_body_ids(body))).scalars().all()
    for account in accounts_to_update:
        account.assigned_user_id = target_user_id
    db.commit()
    return _success({"updated": len(accounts_to_update)})


@router.post("/accounts/batch-assign-organization")
async def batch_assign_account_organization(request: Request, db: DbSession):
    body = await request.json()
    org_id = body.get("organization_id") or body.get("org_id")
    if source_mysql_service.is_source_mysql(db):
        updated = source_mysql_service.batch_update_accounts(
            db, _body_ids(body), {"organization_id": org_id}
        )
        return _success({"updated": updated})
    accounts_to_update = db.execute(_account_stmt_for_ids(_body_ids(body))).scalars().all()
    for account in accounts_to_update:
        account.organization_id = org_id
    db.commit()
    return _success({"updated": len(accounts_to_update)})


@router.post("/accounts/batch-commission-rate")
async def batch_account_commission_rate(request: Request, db: DbSession):
    body = await request.json()
    rate = body.get("commission_rate") or body.get("account_commission_rate")
    if source_mysql_service.is_source_mysql(db):
        source_rate = _as_float(rate, 0.0)
        updated = source_mysql_service.batch_update_accounts(
            db, _body_ids(body), {"commission_rate": source_rate if source_rate > 1 else source_rate * 100}
        )
        return _success({"updated": updated})
    rate = float(rate) / 100 if rate and float(rate) > 1 else float(rate or 0)
    accounts_to_update = db.execute(_account_stmt_for_ids(_body_ids(body))).scalars().all()
    for account in accounts_to_update:
        account.commission_rate = rate
    db.commit()
    return _success({"updated": len(accounts_to_update)})


@router.post("/accounts/batch-delete")
async def batch_delete_accounts(request: Request, db: DbSession):
    body = await request.json()
    if source_mysql_service.is_source_mysql(db):
        updated = source_mysql_service.batch_update_accounts(
            db, _body_ids(body), {"account_status": "deleted", "status_note": "deleted"}
        )
        return _success({"deleted": updated})
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
    if source_mysql_service.is_source_mysql(db):
        updated = source_mysql_service.batch_update_accounts(
            db, _body_ids(body), {"account_status": status}
        )
        return _success({"updated": updated, "status": status})
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
    if source_mysql_service.is_source_mysql(db):
        for item in mappings:
            uid = str(item.get("uid") or item.get("kuaishou_id") or "").strip()
            real_uid = str(item.get("real_uid") or item.get("uid_real") or "").strip()
            if not uid or not real_uid:
                continue
            updated += source_mysql_service.batch_update_accounts(db, [uid], {"uid_real": real_uid})
        return _success({"updated": updated})
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
    if source_mysql_service.is_source_mysql(db):
        updated = source_mysql_service.batch_update_accounts(
            db,
            _body_ids(body),
            {"is_mcm_member": 1 if is_member else 0},
        )
        return _success({"updated": updated})
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
    if source_mysql_service.is_source_mysql(db):
        orgs = source_mysql_service.list_organizations(db, user)
        counts_by_org: dict[int, int] = {}
        rows, total, _mcn = source_mysql_service.list_accounts(db, viewer=user, page=1, per_page=100000)
        counts_by_org = {}
        for row in rows:
            counts_by_org[row.organization_id] = counts_by_org.get(row.organization_id, 0) + 1
        return _success([{**_organization_payload(org), "account_count": counts_by_org.get(org.id, 0)} for org in orgs])
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
    if source_mysql_service.is_source_mysql(db):
        account = source_mysql_service.get_account_by_id(db, account_id)
        return _success(_account_payload(account) if account else None)
    account = db.get(Account, account_id)
    return _success(_account_payload(account) if account else None)


@router.put("/accounts/{account_id}")
@router.put("/accounts/by-id/{account_id}")
async def update_account(account_id: int, request: Request, db: DbSession):
    body = await request.json()
    if source_mysql_service.is_source_mysql(db):
        fields: dict[str, Any] = {
            "uid": body.get("kuaishou_id") or body.get("uid"),
            "uid_real": body.get("real_uid") or body.get("uid_real"),
            "nickname": body.get("nickname"),
            "device_serial": body.get("device_serial"),
            "account_status": body.get("status") or body.get("account_status"),
            "contract_status": body.get("sign_status") or body.get("contract_status"),
            "status_note": body.get("remark"),
            "org_note": body.get("remark"),
        }
        if body.get("organization_id") is not None:
            fields["organization_id"] = body.get("organization_id")
        if body.get("group_id") is not None:
            fields["group_id"] = body.get("group_id")
        if body.get("owner_id") is not None or body.get("user_id") is not None:
            fields["owner_id"] = body.get("owner_id") or body.get("user_id")
        account = source_mysql_service.update_account_fields(
            db,
            account_id,
            {key: value for key, value in fields.items() if value is not None},
        )
        if account is None:
            return _success(None, message="账号不存在")
        return _success(_account_payload(account))
    account = db.get(Account, account_id)
    if account is None:
        return _success(None, message="账号不存在")
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
    if source_mysql_service.is_source_mysql(db):
        source_mysql_service.update_account_fields(
            db, account_id, {"account_status": "deleted", "status_note": "deleted"}
        )
        return _success({"deleted": True})
    account = db.get(Account, account_id)
    if account:
        account.status = "deleted"
        account.deleted_at = datetime.utcnow()
        db.commit()
    return _success({"deleted": True})


@router.put("/accounts/{account_id}/commission-rate")
async def update_account_commission_rate(account_id: int, request: Request, db: DbSession):
    body = await request.json()
    if source_mysql_service.is_source_mysql(db):
        current = source_mysql_service.get_account_by_id(db, account_id)
        if current is None:
            return _success(None, message="账号不存在")
        rate = _as_float(body.get("commission_rate") or body.get("account_commission_rate"), current.commission_rate)
        account = source_mysql_service.update_account_fields(
            db,
            account_id,
            {"commission_rate": rate if rate > 1 else rate * 100},
        )
        return _success(_account_payload(account))
    account = db.get(Account, account_id)
    if account is None:
        return _success(None, message="账号不存在")
    rate = float(body.get("commission_rate") or body.get("account_commission_rate") or account.commission_rate)
    account.commission_rate = rate / 100 if rate > 1 else rate
    db.commit()
    return _success(_account_payload(account))


@router.put("/accounts/{account_id}/uid-real")
async def update_account_uid_real(account_id: int, request: Request, db: DbSession):
    body = await request.json()
    if source_mysql_service.is_source_mysql(db):
        account = source_mysql_service.update_account_fields(
            db,
            account_id,
            {"uid_real": body.get("uid_real") or body.get("real_uid")},
        )
        if account is None:
            return _success(None, message="账号不存在")
        return _success(_account_payload(account))
    account = db.get(Account, account_id)
    if account is None:
        return _success(None, message="账号不存在")
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
    if source_mysql_service.is_source_mysql(db):
        page, per_page = _page_size(page, page_size or pageSize, size)
        rows, total = source_mysql_service.list_ks_accounts(
            db,
            viewer=user,
            page=page,
            per_page=per_page,
            keyword=keyword,
        )
        return _success(
            [_ks_account_payload(row) for row in rows],
            pagination={"total": total, "page": page, "page_size": per_page},
        )
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
    if source_mysql_service.is_source_mysql(db):
        orgs = source_mysql_service.list_organizations(db, user)
        rows, _total, _mcn = source_mysql_service.list_accounts(db, viewer=user, page=1, per_page=100000)
        counts_by_org: dict[int, int] = {}
        for row in rows:
            counts_by_org[row.organization_id] = counts_by_org.get(row.organization_id, 0) + 1
        return _success([{"organization_id": org.id, "organization_name": org.name, "total": counts_by_org.get(org.id, 0)} for org in orgs])
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
    if source_mysql_service.is_source_mysql(db):
        where, params = _source_org_clause(user, "org_id")
        if search:
            where.append("(CAST(member_id AS CHAR) LIKE :search OR member_name LIKE :search OR comment LIKE :search)")
            params["search"] = f"%{search}%"
        if broker_name:
            where.append("broker_name = :broker_name")
            params["broker_name"] = broker_name
        if contract_renew_status:
            where.append("CAST(contract_renew_status AS CHAR) = :contract_renew_status")
            params["contract_renew_status"] = str(contract_renew_status)
        if agreement_type:
            where.append("agreement_types LIKE :agreement_type")
            params["agreement_type"] = f"%{agreement_type}%"
        total = _source_count(db, "spark_org_members", where, params)
        sql_where = " AND ".join(where) if where else "1=1"
        rows = db.execute(
            text(f"SELECT * FROM spark_org_members WHERE {sql_where} ORDER BY id DESC LIMIT :limit OFFSET :offset"),
            {**params, "limit": per_page, "offset": (page - 1) * per_page},
        ).mappings().all()
        return _success([_source_org_member_payload(dict(row)) for row in rows], total=total)
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
    return _success(_org_member_payloads(db, rows), total=total)


@router.get("/org-members/brokers")
async def org_member_brokers(db: DbSession, user: CurrentUser):
    if source_mysql_service.is_source_mysql(db):
        where, params = _source_org_clause(user, "org_id")
        where.append("broker_name IS NOT NULL")
        where.append("broker_name <> ''")
        sql_where = " AND ".join(where)
        rows = db.execute(text(f"SELECT DISTINCT broker_name FROM spark_org_members WHERE {sql_where} ORDER BY broker_name ASC"), params).scalars().all()
        return _success([name for name in rows if name])
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
    if source_mysql_service.is_source_mysql(db):
        where, params = _source_org_clause(user, "org_id")
        if search:
            where.append("(CAST(photo_id AS CHAR) LIKE :search OR CAST(user_id AS CHAR) LIKE :search OR username LIKE :search OR caption LIKE :search)")
            params["search"] = f"%{search}%"
        if sub_biz:
            where.append("sub_biz = :sub_biz")
            params["sub_biz"] = sub_biz
        if broker_name:
            where.append("broker_name = :broker_name")
            params["broker_name"] = broker_name
        total = _source_count(db, "spark_violation_photos", where, params)
        sql_where = " AND ".join(where) if where else "1=1"
        rows = db.execute(
            text(f"SELECT * FROM spark_violation_photos WHERE {sql_where} ORDER BY id DESC LIMIT :limit OFFSET :offset"),
            {**params, "limit": per_page, "offset": (page - 1) * per_page},
        ).mappings().all()
        return _success(
            [
                {
                    "id": row["id"],
                    "source_id": None,
                    "work_id": row["photo_id"],
                    "photo_id": row["photo_id"],
                    "uid": str(row["user_id"]) if row["user_id"] is not None else "",
                    "user_id": row["user_id"],
                    "username": row["username"],
                    "nickname": row["username"],
                    "thumbnail": row["thumb_url"],
                    "thumb_url": row["thumb_url"],
                    "media_url": row["media_url"],
                    "avatar_url": row["avatar_url"],
                    "description": row["caption"],
                    "caption": row["caption"],
                    "business_type": row["sub_biz"],
                    "sub_biz": row["sub_biz"],
                    "violation_reason": row["reason"],
                    "reason": row["reason"],
                    "suggestion": row["suggestion"],
                    "status": row["status"],
                    "status_desc": row["status_desc"],
                    "view_count": row["view_count"] or 0,
                    "like_count": row["like_count"] or 0,
                    "forward_count": row["forward_count"] or 0,
                    "comment_count": row["comment_count"] or 0,
                    "fans_count": row["fans_count"] or 0,
                    "broker_name": row["broker_name"],
                    "broker_id": row["broker_id"],
                    "appeal_status": row["appeal_status_desc"] or row["appeal_status"],
                    "appeal_reason": row["appeal_detail"],
                    "published_at": _dt(row["publish_date"]),
                    "publish_date": _dt(row["publish_date"]),
                    "publish_time": row["publish_time"],
                    "organization_id": row["org_id"],
                    "org_id": row["org_id"],
                    "created_at": _dt(row["created_at"]),
                    "updated_at": _dt(row["updated_at"]),
                }
                for row in rows
            ],
            total=total,
        )
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
async def firefly_members(
    db: DbSession,
    user: CurrentUser,
    page: int = 1,
    page_size: int | None = None,
    size: int | None = None,
    search: str | None = None,
    org_id: int | None = None,
    organization_id: int | None = None,
    group_id: int | None = None,
    owner_id: int | None = None,
    broker_name: str | None = None,
    sort_field: str | None = None,
    sort_order: str | None = None,
):
    page, per_page = _page_size(page, page_size, size)
    if source_mysql_service.is_source_mysql(db):
        data, total = _source_member_list(
            db,
            user,
            table="fluorescent_members",
            program="firefly",
            page=page,
            per_page=per_page,
            search=search,
            broker_name=broker_name,
            org_id=org_id or organization_id,
            sort_field=sort_field,
            sort_order=sort_order,
        )
        return _success(data, total=total)
    # The demo labels this page "firefly", but its real data source is fluorescent_members.
    stmt = select(FluorescentMember)
    stmt = _apply_org_scope(stmt, FluorescentMember, user)
    if search:
        like = f"%{search}%"
        stmt = stmt.where(or_(FluorescentMember.nickname.like(like), FluorescentMember.member_id.cast(String).like(like)))
    target_org = org_id or organization_id
    if target_org and user.is_superadmin:
        stmt = stmt.where(FluorescentMember.organization_id == target_org)
    if broker_name:
        stmt = stmt.where(FluorescentMember.broker_name == broker_name)
    account_filter = select(Account.id).where(Account.deleted_at.is_(None))
    use_account_filter = False
    if group_id is not None:
        use_account_filter = True
        if int(group_id) == 0:
            account_filter = account_filter.where(Account.group_id.is_(None))
        else:
            account_filter = account_filter.where(Account.group_id == group_id)
    if owner_id:
        use_account_filter = True
        account_filter = account_filter.where(Account.assigned_user_id == owner_id)
    if use_account_filter:
        stmt = stmt.where(FluorescentMember.account_id.in_(account_filter))
    total = _count(db, stmt)
    order_col = {
        "member_id": FluorescentMember.member_id,
        "member_name": FluorescentMember.nickname,
        "fans_count": FluorescentMember.fans_count,
        "org_task_num": FluorescentMember.org_task_num,
        "total_amount": FluorescentMember.total_amount,
        "created_at": FluorescentMember.created_at,
    }.get(sort_field or "total_amount", FluorescentMember.total_amount)
    order_expr = order_col.asc() if sort_order == "ascending" else order_col.desc()
    rows = db.execute(stmt.order_by(order_expr).offset((page - 1) * per_page).limit(per_page)).scalars().all()
    return _success(_member_payloads(db, rows), total=total)


@router.get("/firefly/members/stats")
async def firefly_member_stats(
    db: DbSession,
    user: CurrentUser,
    search: str | None = None,
    org_id: int | None = None,
    organization_id: int | None = None,
    group_id: int | None = None,
    owner_id: int | None = None,
):
    if source_mysql_service.is_source_mysql(db):
        where, params = _source_org_clause(user, "org_id")
        target_org = org_id or organization_id
        if target_org and user.is_superadmin:
            where.append("org_id = :org_id")
            params["org_id"] = target_org
        if search:
            where.append("(CAST(member_id AS CHAR) LIKE :search OR member_name LIKE :search)")
            params["search"] = f"%{search}%"
        sql_where = " AND ".join(where) if where else "1=1"
        row = db.execute(
            text(
                f"""
                SELECT COUNT(*) AS total_members,
                       COALESCE(SUM(total_amount), 0) AS total_amount,
                       COALESCE(SUM(org_task_num), 0) AS total_tasks
                FROM fluorescent_members
                WHERE {sql_where}
                """
            ),
            params,
        ).mappings().one()
        amount = float(row["total_amount"] or 0)
        return _success(
            {
                "total_members": int(row["total_members"] or 0),
                "total_amount": round(amount, 2),
                "total_tasks": int(row["total_tasks"] or 0),
                "period_income": round(amount, 2),
                "period_commission": 0,
            }
        )
    stmt = select(FluorescentMember)
    stmt = _apply_org_scope(stmt, FluorescentMember, user)
    if search:
        like = f"%{search}%"
        stmt = stmt.where(or_(FluorescentMember.nickname.like(like), FluorescentMember.member_id.cast(String).like(like)))
    target_org = org_id or organization_id
    if target_org and user.is_superadmin:
        stmt = stmt.where(FluorescentMember.organization_id == target_org)
    account_filter = select(Account.id).where(Account.deleted_at.is_(None))
    use_account_filter = False
    if group_id is not None:
        use_account_filter = True
        account_filter = account_filter.where(Account.group_id.is_(None) if int(group_id) == 0 else Account.group_id == group_id)
    if owner_id:
        use_account_filter = True
        account_filter = account_filter.where(Account.assigned_user_id == owner_id)
    if use_account_filter:
        stmt = stmt.where(FluorescentMember.account_id.in_(account_filter))
    rows = db.execute(stmt).scalars().all()
    amount = sum(row.total_amount for row in rows)
    tasks = sum(row.org_task_num for row in rows)
    return _success(
        {
            "total_members": len(rows),
            "total_amount": round(amount, 2),
            "total_tasks": tasks,
            "period_income": round(amount, 2),
            "period_commission": 0,
        }
    )


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
    if source_mysql_service.is_source_mysql(db):
        source_total = _source_count(db, "spark_members", *_source_org_clause(user, "org_id"))
        if source_total:
            data, total = _source_member_list(
                db,
                user,
                table="spark_members",
                program="spark",
                page=page,
                per_page=per_page,
                search=search,
                broker_name=broker_name,
                sort_field="org_task_num",
            )
            return _success(data, total=total)
        where, params = _source_org_clause(user, "org_id")
        if search:
            where.append("(CAST(member_id AS CHAR) LIKE :search OR member_name LIKE :search OR comment LIKE :search)")
            params["search"] = f"%{search}%"
        if broker_name:
            where.append("broker_name = :broker_name")
            params["broker_name"] = broker_name
        total = _source_count(db, "spark_org_members", where, params)
        sql_where = " AND ".join(where) if where else "1=1"
        rows = db.execute(
            text(f"SELECT * FROM spark_org_members WHERE {sql_where} ORDER BY id DESC LIMIT :limit OFFSET :offset"),
            {**params, "limit": per_page, "offset": (page - 1) * per_page},
        ).mappings().all()
        return _success([_source_org_member_payload(dict(row)) for row in rows], total=total)
    stmt = select(SparkMember)
    stmt = _apply_org_scope(stmt, SparkMember, user)
    if search:
        like = f"%{search}%"
        stmt = stmt.where(or_(SparkMember.nickname.like(like), SparkMember.member_id.cast(String).like(like)))
    if broker_name:
        stmt = stmt.where(SparkMember.broker_name == broker_name)
    total = _count(db, stmt)
    rows = db.execute(stmt.order_by(SparkMember.task_count.desc()).offset((page - 1) * per_page).limit(per_page)).scalars().all()
    return _success(_member_payloads(db, rows), total=total)


@router.get("/spark/members/stats")
async def spark_member_stats(db: DbSession, user: CurrentUser):
    if source_mysql_service.is_source_mysql(db):
        table = "spark_members"
        source_total = _source_count(db, table, *_source_org_clause(user, "org_id"))
        if not source_total:
            table = "spark_org_members"
        where, params = _source_org_clause(user, "org_id")
        sql_where = " AND ".join(where) if where else "1=1"
        amount_expr = "COALESCE(SUM(total_amount), 0)" if table == "spark_members" else "0"
        task_expr = "COALESCE(SUM(org_task_num), 0)" if table == "spark_members" else "COUNT(*)"
        row = db.execute(
            text(f"SELECT COUNT(*) AS total_members, {task_expr} AS total_tasks, {amount_expr} AS period_income FROM {table} WHERE {sql_where}"),
            params,
        ).mappings().one()
        return _success(
            {
                "total_members": int(row["total_members"] or 0),
                "total_tasks": int(row["total_tasks"] or 0),
                "period_income": float(row["period_income"] or 0),
                "period_commission": 0,
                "monthly_period": "",
            }
        )
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
    if source_mysql_service.is_source_mysql(db):
        table = "spark_members"
        if not _source_count(db, table, *_source_org_clause(user, "org_id")):
            table = "spark_org_members"
        where, params = _source_org_clause(user, "org_id")
        where.append("broker_name IS NOT NULL")
        where.append("broker_name <> ''")
        sql_where = " AND ".join(where)
        rows = db.execute(
            text(f"SELECT DISTINCT broker_name FROM {table} WHERE {sql_where}"),
            params,
        ).scalars().all()
        return _success([name for name in rows if name])
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
    if source_mysql_service.is_source_mysql(db):
        page, per_page = _page_size(page, page_size, size)
        data, total = _source_income_list(
            db, user, table="fluorescent_income_archive", program="firefly", page=page, per_page=per_page, task_name=task_name, org_column="org_id"
        )
        return _success(data, total=total)
    data, total = _income_list(db, user, FireflyIncome, page, page_size, size, task_name)
    return _success(data, total=total)


@router.get("/spark/income")
async def spark_income(db: DbSession, user: CurrentUser, page: int = 1, page_size: int | None = None, size: int | None = None, task_name: str | None = None):
    if source_mysql_service.is_source_mysql(db):
        page, per_page = _page_size(page, page_size, size)
        data, total = _source_income_list(
            db, user, table="spark_income", program="spark", page=page, per_page=per_page, task_name=task_name, org_column="org_id"
        )
        return _success(data, total=total)
    data, total = _income_list(db, user, SparkIncome, page, page_size, size, task_name)
    return _success(data, total=total)


@router.get("/fluorescent/income")
async def fluorescent_income(db: DbSession, user: CurrentUser, page: int = 1, page_size: int | None = None, size: int | None = None, task_name: str | None = None):
    if source_mysql_service.is_source_mysql(db):
        page, per_page = _page_size(page, page_size, size)
        data, total = _source_income_list(
            db, user, table="fluorescent_income_archive", program="fluorescent", page=page, per_page=per_page, task_name=task_name, org_column="org_id"
        )
        return _success(data, total=total)
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
    return _income_payloads(db, rows), total


@router.get("/firefly/income/stats")
async def firefly_income_stats(db: DbSession, user: CurrentUser):
    if source_mysql_service.is_source_mysql(db):
        return _success(_source_income_stats(db, user, table="fluorescent_income_archive", amount_column="total_amount", org_column="org_id"))
    return _success(_sum_income(db, user, FireflyIncome))


@router.get("/spark/income/stats")
async def spark_income_stats(db: DbSession, user: CurrentUser):
    if source_mysql_service.is_source_mysql(db):
        return _success(_source_income_stats(db, user, table="spark_income", amount_column="income", org_column="org_id"))
    return _success(_sum_income(db, user, SparkIncome))


@router.get("/fluorescent/income/stats")
async def fluorescent_income_stats(db: DbSession, user: CurrentUser):
    if source_mysql_service.is_source_mysql(db):
        return _success(_source_income_stats(db, user, table="fluorescent_income_archive", amount_column="total_amount", org_column="org_id"))
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
    if source_mysql_service.is_source_mysql(db):
        data, total = _source_income_list(
            db, user, table="spark_income_archive", program="spark", page=page, per_page=per_page, org_column="org_id"
        )
        return _success(data, total=total)
    stmt = select(IncomeArchive).where(IncomeArchive.program_type == "spark")
    stmt = _apply_org_scope(stmt, IncomeArchive, user)
    total = _count(db, stmt)
    rows = db.execute(stmt.order_by(IncomeArchive.id.desc()).offset((page - 1) * per_page).limit(per_page)).scalars().all()
    return _success(_income_payloads(db, rows), total=total)


@router.get("/spark/archive/stats")
async def spark_archive_stats(db: DbSession, user: CurrentUser):
    if source_mysql_service.is_source_mysql(db):
        return _success(_source_income_stats(db, user, table="spark_income_archive", amount_column="total_amount", org_column="org_id"))
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
    if source_mysql_service.is_source_mysql(db):
        where: list[str] = []
        params: dict[str, Any] = {}
        if search:
            where.append("(name LIKE :search OR url LIKE :search)")
            params["search"] = f"%{search}%"
        if platform not in (None, ""):
            raw_platform = 1 if str(platform).lower() in {"kuaishou", "1"} else platform
            where.append("platform = :platform")
            params["platform"] = raw_platform
        if username:
            where.append("username = :username")
            params["username"] = username
        total = _source_count(db, "wait_collect_videos", where, params)
        sql_where = " AND ".join(where) if where else "1=1"
        rows = db.execute(
            text(f"SELECT * FROM wait_collect_videos WHERE {sql_where} ORDER BY id DESC LIMIT :limit OFFSET :offset"),
            {**params, "limit": per_page, "offset": (page - 1) * per_page},
        ).mappings().all()
        return _success([_source_collect_pool_payload(dict(row)) for row in rows], total=total)
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
    if source_mysql_service.is_source_mysql(db):
        row = db.execute(
            text(
                """
                SELECT COUNT(*) AS total,
                       SUM(CASE WHEN url IS NOT NULL AND url <> '' THEN 1 ELSE 0 END) AS active,
                       SUM(CASE WHEN url IS NULL OR url = '' THEN 1 ELSE 0 END) AS abnormal
                FROM wait_collect_videos
                """
            )
        ).mappings().one()
        return _success({"total": int(row["total"] or 0), "active": int(row["active"] or 0), "abnormal": int(row["abnormal"] or 0)})
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
    if source_mysql_service.is_source_mysql(db):
        rows = db.execute(text("SELECT * FROM collect_pool_auth_codes ORDER BY id ASC")).mappings().all()
        return _success([
            {
                "id": row["id"],
                "auth_code": row["auth_code"],
                "name": row["name"] or row["auth_code"],
                "is_active": int(row["is_active"] or 0),
                "expire_at": _dt(row["expire_at"]),
                "created_by": row["created_by"],
                "created_at": _dt(row["created_at"]),
                "updated_at": _dt(row["updated_at"]),
            }
            for row in rows
        ])
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
    if source_mysql_service.is_source_mysql(db):
        where: list[str] = []
        params: dict[str, Any] = {}
        if keyword:
            where.append("title LIKE :keyword")
            params["keyword"] = f"%{keyword}%"
        total = _source_count(db, "spark_highincome_dramas", where, params)
        sql_where = " AND ".join(where) if where else "1=1"
        rows = db.execute(
            text(f"SELECT * FROM spark_highincome_dramas WHERE {sql_where} ORDER BY id DESC LIMIT :limit OFFSET :offset"),
            {**params, "limit": per_page, "offset": (page - 1) * per_page},
        ).mappings().all()
        data = [
            {
                "id": row["id"],
                "title": row["title"],
                "name": row["title"],
                "task_name": row["title"],
                "drama_name": row["title"],
                "source_program": "spark",
                "income": None,
                "income_amount": None,
                "notes": None,
                "organization_id": None,
                "created_at": _dt(row["created_at"]),
            }
            for row in rows
        ]
        return _success({"list": data, "total": total}, total=total)
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
async def high_income_drama_links(db: DbSession, user: CurrentUser, title: str | None = None):
    if source_mysql_service.is_source_mysql(db):
        names = [item.strip() for item in str(title or "").split(",") if item.strip()]
        where: list[str] = []
        params: dict[str, Any] = {}
        if names:
            where.append("name LIKE :title")
            params["title"] = f"%{names[0]}%"
        sql_where = " AND ".join(where) if where else "1=1"
        rows = db.execute(
            text(
                f"""
                SELECT id, name AS drama_name, url AS drama_url,
                       COUNT(*) OVER (PARTITION BY name) AS reference_count
                FROM kuaishou_urls
                WHERE {sql_where}
                ORDER BY id DESC
                LIMIT 500
                """
            ),
            params,
        ).mappings().all()
        return _success(
            [
                {
                    "id": row["id"],
                    "drama_name": row["drama_name"],
                    "title": row["drama_name"],
                    "task_type": "高转化短剧",
                    "drama_link": row["drama_url"],
                    "drama_url": row["drama_url"],
                    "total_count": int(row["reference_count"] or 0),
                    "execute_count": int(row["reference_count"] or 0),
                    "success_count": 0,
                    "failed_count": 0,
                    "account_count": 0,
                    "success_rate": 0,
                    "source": "kuaishou_urls",
                    "organization_id": None,
                    "last_executed_at": None,
                    "created_at": None,
                }
                for row in rows
            ]
        )
    names = [item.strip() for item in str(title or "").split(",") if item.strip()]
    link_stmt = select(HighIncomeDramaLink)
    link_stmt = _apply_org_scope(link_stmt, HighIncomeDramaLink, user)
    if names:
        if len(names) == 1:
            link_stmt = link_stmt.where(HighIncomeDramaLink.drama_name.like(f"%{names[0]}%"))
        else:
            link_stmt = link_stmt.where(HighIncomeDramaLink.drama_name.in_(names))
    link_rows = db.execute(
        link_stmt.order_by(HighIncomeDramaLink.reference_count.desc()).limit(500)
    ).scalars().all()
    if link_rows:
        return _success([_high_income_link_payload(row) for row in link_rows])

    stmt = select(DramaLinkStatistic)
    stmt = _apply_org_scope(stmt, DramaLinkStatistic, user)
    if names:
        if len(names) == 1:
            stmt = stmt.where(DramaLinkStatistic.drama_name.like(f"%{names[0]}%"))
        else:
            stmt = stmt.where(DramaLinkStatistic.drama_name.in_(names))
    rows = db.execute(stmt.order_by(DramaLinkStatistic.execute_count.desc()).limit(500)).scalars().all()
    return _success([_drama_link_payload(row) for row in rows])


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
    task_type: str | None = None,
    start_date: str | None = None,
    end_date: str | None = None,
    export: bool = False,
):
    page, per_page = _page_size(page, page_size, size)
    if export:
        per_page = 10000
    if source_mysql_service.is_source_mysql(db):
        where: list[str] = []
        params: dict[str, Any] = {}
        if search:
            where.append("(drama_name LIKE :search OR drama_link LIKE :search)")
            params["search"] = f"%{search}%"
        if task_type:
            where.append("task_type = :task_type")
            params["task_type"] = task_type
        if start_date:
            where.append("created_at >= :start_date")
            params["start_date"] = start_date
        if end_date:
            where.append("created_at <= :end_date")
            params["end_date"] = end_date
        sql_where = " AND ".join(where) if where else "1=1"
        total = int(
            db.execute(
                text(f"SELECT COUNT(*) FROM (SELECT drama_link FROM task_statistics WHERE {sql_where} GROUP BY drama_link) t"),
                params,
            ).scalar_one()
        )
        rows = db.execute(
            text(
                f"""
                SELECT MIN(id) AS id,
                       drama_name,
                       drama_link AS drama_url,
                       task_type,
                       COUNT(*) AS execute_count,
                       SUM(CASE WHEN status IN ('success', 'completed', 'done', 'ok', '1') THEN 1 ELSE 0 END) AS success_count,
                       SUM(CASE WHEN status IN ('failed', 'fail', 'error', '0') THEN 1 ELSE 0 END) AS failed_count,
                       COUNT(DISTINCT uid) AS account_count,
                       MAX(created_at) AS last_executed_at
                FROM task_statistics
                WHERE {sql_where}
                GROUP BY drama_link, drama_name, task_type
                ORDER BY execute_count DESC
                LIMIT :limit OFFSET :offset
                """
            ),
            {**params, "limit": per_page, "offset": (page - 1) * per_page},
        ).mappings().all()
        summary_row = db.execute(
            text(
                f"""
                SELECT COUNT(DISTINCT drama_name) AS drama_count,
                       COUNT(*) AS execute_count,
                       SUM(CASE WHEN status IN ('success', 'completed', 'done', 'ok', '1') THEN 1 ELSE 0 END) AS success_count,
                       SUM(CASE WHEN status IN ('failed', 'fail', 'error', '0') THEN 1 ELSE 0 END) AS failed_count,
                       COUNT(DISTINCT uid) AS account_count
                FROM task_statistics
                WHERE {sql_where}
                """
            ),
            params,
        ).mappings().one()
        data = [
            {
                "id": row["id"],
                "drama_name": row["drama_name"],
                "task_type": row["task_type"],
                "drama_link": row["drama_url"],
                "drama_url": row["drama_url"],
                "total_count": int(row["execute_count"] or 0),
                "execute_count": int(row["execute_count"] or 0),
                "success_count": int(row["success_count"] or 0),
                "failed_count": int(row["failed_count"] or 0),
                "account_count": int(row["account_count"] or 0),
                "success_rate": round((int(row["success_count"] or 0) / int(row["execute_count"] or 1)) * 100, 2),
                "organization_id": None,
                "last_executed_at": _dt(row["last_executed_at"]),
                "created_at": _dt(row["last_executed_at"]),
            }
            for row in rows
        ]
        summary = {
            "drama_count": int(summary_row["drama_count"] or 0),
            "total_count": int(summary_row["execute_count"] or 0),
            "execute_count": int(summary_row["execute_count"] or 0),
            "success_count": int(summary_row["success_count"] or 0),
            "failed_count": int(summary_row["failed_count"] or 0),
            "account_count": int(summary_row["account_count"] or 0),
        }
        return _success({"list": data, "summary": summary, "total": total})
    stmt = select(DramaLinkStatistic)
    stmt = _apply_org_scope(stmt, DramaLinkStatistic, user)
    if search:
        like = f"%{search}%"
        stmt = stmt.where(or_(DramaLinkStatistic.drama_name.like(like), DramaLinkStatistic.drama_url.like(like)))
    if task_type:
        stmt = stmt.where(DramaLinkStatistic.task_type == task_type)
    if start_date:
        stmt = stmt.where(DramaLinkStatistic.last_executed_at >= start_date)
    if end_date:
        stmt = stmt.where(DramaLinkStatistic.last_executed_at <= end_date)
    total = _count(db, stmt)
    rows = db.execute(stmt.order_by(DramaLinkStatistic.execute_count.desc()).offset((page - 1) * per_page).limit(per_page)).scalars().all()
    summary_subq = stmt.subquery()
    summary_row = db.execute(
        select(
            func.count(func.distinct(func.trim(summary_subq.c.drama_name))),
            func.coalesce(func.sum(summary_subq.c.execute_count), 0),
            func.coalesce(func.sum(summary_subq.c.success_count), 0),
            func.coalesce(func.sum(summary_subq.c.failed_count), 0),
            func.coalesce(func.sum(summary_subq.c.account_count), 0),
        ).select_from(summary_subq)
    ).one()
    summary = {
        "drama_count": int(summary_row[0] or 0),
        "total_count": int(summary_row[1] or 0),
        "execute_count": int(summary_row[1] or 0),
        "success_count": int(summary_row[2] or 0),
        "failed_count": int(summary_row[3] or 0),
        "account_count": int(summary_row[4] or 0),
    }
    return _success({"list": [_drama_link_payload(row) for row in rows], "summary": summary, "total": total})


@router.get("/collections/accounts")
async def collection_accounts(db: DbSession, user: CurrentUser):
    if source_mysql_service.is_source_mysql(db):
        rows = db.execute(
            text(
                """
                SELECT MIN(id) AS id,
                       kuaishou_uid,
                       kuaishou_name,
                       device_serial,
                       COUNT(*) AS total_count,
                       SUM(CASE WHEN plan_mode = 'spark' THEN 1 ELSE 0 END) AS spark_count,
                       SUM(CASE WHEN plan_mode IN ('firefly', 'fluorescent', 'yingguang') THEN 1 ELSE 0 END) AS firefly_count,
                       MAX(collected_at) AS last_collected_at,
                       MAX(updated_at) AS updated_at
                FROM drama_collections
                GROUP BY kuaishou_uid, kuaishou_name, device_serial
                ORDER BY total_count DESC
                LIMIT 1000
                """
            )
        ).mappings().all()
        return _success(
            [
                {
                    "id": row["id"],
                    "kuaishou_uid": row["kuaishou_uid"],
                    "uid": row["kuaishou_uid"],
                    "kuaishou_name": row["kuaishou_name"],
                    "nickname": row["kuaishou_name"],
                    "device_serial": row["device_serial"],
                    "total_count": int(row["total_count"] or 0),
                    "spark_count": int(row["spark_count"] or 0),
                    "firefly_count": int(row["firefly_count"] or 0),
                    "fluorescent_count": int(row["firefly_count"] or 0),
                    "last_collected_at": _dt(row["last_collected_at"]),
                    "updated_at": _dt(row["updated_at"]),
                }
                for row in rows
            ]
        )
    stmt = select(DramaCollectionRecord)
    stmt = _apply_org_scope(stmt, DramaCollectionRecord, user)
    rows = db.execute(stmt.order_by(DramaCollectionRecord.total_count.desc()).limit(1000)).scalars().all()
    return _success([_drama_collection_payload(row) for row in rows])


@router.get("/collections/stats/overview")
async def collection_stats(db: DbSession, user: CurrentUser):
    if source_mysql_service.is_source_mysql(db):
        row = db.execute(
            text(
                """
                SELECT COUNT(DISTINCT kuaishou_uid) AS total_accounts,
                       COUNT(*) AS total_count,
                       SUM(CASE WHEN plan_mode = 'spark' THEN 1 ELSE 0 END) AS spark_count,
                       SUM(CASE WHEN plan_mode IN ('firefly', 'fluorescent', 'yingguang') THEN 1 ELSE 0 END) AS firefly_count
                FROM drama_collections
                """
            )
        ).mappings().one()
        firefly_count = int(row["firefly_count"] or 0)
        return _success(
            {
                "total_accounts": int(row["total_accounts"] or 0),
                "total_count": int(row["total_count"] or 0),
                "spark_count": int(row["spark_count"] or 0),
                "firefly_count": firefly_count,
                "fluorescent_count": firefly_count,
            }
        )
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
    if source_mysql_service.is_source_mysql(db):
        where = ["drama_link IS NOT NULL", "drama_link <> ''"]
        params: dict[str, Any] = {}
        if search:
            where.append("drama_link LIKE :search")
            params["search"] = f"%{search}%"
        if not user.is_superadmin:
            where.append(
                """
                EXISTS (
                    SELECT 1 FROM kuaishou_accounts ka
                    WHERE ka.organization_id = :viewer_org_id
                      AND (ka.uid = ts.uid OR ka.uid_real = ts.uid)
                )
                """
            )
            params["viewer_org_id"] = user.organization_id
        sql_where = " AND ".join(where)
        total = int(
            db.execute(
                text(f"SELECT COUNT(*) FROM (SELECT drama_link FROM task_statistics ts WHERE {sql_where} GROUP BY drama_link) t"),
                params,
            ).scalar_one()
        )
        summary_row = db.execute(
            text(f"SELECT COUNT(*) AS ref_count FROM task_statistics ts WHERE {sql_where}"),
            params,
        ).mappings().one()
        rows = db.execute(
            text(
                f"""
                SELECT drama_link AS url,
                       COUNT(*) AS reference_count,
                       MAX(created_at) AS last_seen_at
                FROM task_statistics ts
                WHERE {sql_where}
                GROUP BY drama_link
                ORDER BY reference_count DESC, last_seen_at DESC
                LIMIT :limit OFFSET :offset
                """
            ),
            {**params, "limit": per_page, "offset": (page - 1) * per_page},
        ).mappings().all()
        data = [
            {
                "id": index + (page - 1) * per_page + 1,
                "url": row["url"],
                "source_platform": "kuaishou",
                "reference_count": int(row["reference_count"] or 0),
                "last_seen_at": _dt(row["last_seen_at"]),
                "created_at": _dt(row["last_seen_at"]),
                "updated_at": _dt(row["last_seen_at"]),
                "source": "task_statistics.drama_link",
            }
            for index, row in enumerate(rows)
        ]
        summary = {"total": total, "url_count": int(summary_row["ref_count"] or 0)}
        return _success({"list": data, "summary": summary, "total": total})
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
    if source_mysql_service.is_source_mysql(db):
        total = _source_count(db, "cloud_cookie_accounts", [], {})
        rows = db.execute(
            text("SELECT * FROM cloud_cookie_accounts ORDER BY id DESC LIMIT :limit OFFSET :offset"),
            {"limit": per_page, "offset": (page - 1) * per_page},
        ).mappings().all()
        data = [
            {
                "id": row["id"],
                "uid": row["kuaishou_uid"] or row["account_id"],
                "nickname": row["kuaishou_name"] or row["account_name"],
                "owner_code": row["owner_code"],
                "login_status": row["login_status"],
                "cookies": (row["cookies"][:77] + "...") if row["cookies"] and len(row["cookies"]) > 80 else row["cookies"],
                "device_serial": row["device_serial"],
                "success_count": row["success_count"],
                "fail_count": row["fail_count"],
                "created_at": _dt(row["created_at"]),
                "updated_at": _dt(row["updated_at"]),
            }
            for row in rows
        ]
        return _success(data, pagination={"total": total, "page": page, "page_size": per_page})
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
    if source_mysql_service.is_source_mysql(db):
        rows = db.execute(
            text("SELECT DISTINCT owner_code FROM cloud_cookie_accounts WHERE owner_code IS NOT NULL ORDER BY owner_code ASC")
        ).scalars().all()
        return _success(rows)
    rows = db.execute(select(CloudCookieAccount.owner_code).where(CloudCookieAccount.owner_code.is_not(None)).distinct()).scalars().all()
    return _success(rows)


@router.get("/cxt-user")
async def cxt_users(db: DbSession, user: CurrentUser, page: int = 1, page_size: int | None = None, size: int | None = None, search: str | None = None, status: str | None = None):
    page, per_page = _page_size(page, page_size, size)
    try:
        where = ["1=1"]
        params: dict[str, Any] = {}
        if search:
            where.append("(uid LIKE :search OR note LIKE :search OR auth_code LIKE :search)")
            params["search"] = f"%{search}%"
        if status not in (None, ""):
            where.append("status = :status")
            params["status"] = status
        where_sql = " AND ".join(where)
        total = int(db.execute(text(f"SELECT COUNT(*) FROM cxt_user WHERE {where_sql}"), params).scalar() or 0)
        rows = db.execute(
            text(
                f"""
                SELECT id, uid, note, auth_code, status
                FROM cxt_user
                WHERE {where_sql}
                ORDER BY id DESC
                LIMIT :limit OFFSET :offset
                """
            ),
            {**params, "limit": per_page, "offset": (page - 1) * per_page},
        ).mappings().all()
        data = [
            {
                "id": row["id"],
                "uid": row["uid"],
                "sec_user_id": row["uid"],
                "nickname": row["note"],
                "note": row["note"],
                "auth_code": row["auth_code"],
                "status": row["status"],
            }
            for row in rows
        ]
        return _success({"list": data, "total": total})
    except Exception:
        # Fall back to the ORM compatibility table if a future install does not
        # have the legacy huoshijie cxt_user table.
        pass

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
    if source_mysql_service.is_source_mysql(db):
        where: list[str] = []
        params: dict[str, Any] = {}
        if title:
            where.append("title LIKE :title")
            params["title"] = f"%{title}%"
        if author:
            where.append("author LIKE :author")
            params["author"] = f"%{author}%"
        if aweme_id:
            where.append("aweme_id LIKE :aweme_id")
            params["aweme_id"] = f"%{aweme_id}%"
        total = _source_count(db, "cxt_videos", where, params)
        sql_where = " AND ".join(where) if where else "1=1"
        rows = db.execute(
            text(f"SELECT * FROM cxt_videos WHERE {sql_where} ORDER BY id DESC LIMIT :limit OFFSET :offset"),
            {**params, "limit": per_page, "offset": (page - 1) * per_page},
        ).mappings().all()
        data = [
            {
                "id": row["id"],
                "title": row["title"],
                "author": row["author"],
                "sec_user_id": row["sec_user_id"],
                "aweme_id": row["aweme_id"],
                "description": row["description"],
                "video_url": row["video_url"],
                "cover_url": row["cover_url"],
                "thumbnail": row["cover_url"],
                "duration": row["duration"],
                "play_count": row["play_count"] or 0,
                "digg_count": row["digg_count"] or 0,
                "comment_count": row["comment_count"] or 0,
                "collect_count": row["collect_count"] or 0,
                "share_count": row["share_count"] or 0,
                "recommend_count": row["recommend_count"] or 0,
                "platform": row["platform"],
                "status": "active",
                "created_at": _dt(row["created_at"]),
            }
            for row in rows
        ]
        stats = {
            "totalCount": total,
            "totalPlay": sum(item["play_count"] for item in data),
            "totalDigg": sum(item["digg_count"] for item in data),
            "totalComment": sum(item["comment_count"] for item in data),
        }
        return _success({"list": data, "total": total, "stats": stats})
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
            "description": row.description,
            "video_url": row.video_url,
            "cover_url": row.cover_url,
            "thumbnail": row.cover_url,
            "duration": row.duration,
            "play_count": row.play_count,
            "digg_count": row.digg_count,
            "comment_count": row.comment_count,
            "collect_count": row.collect_count,
            "share_count": row.share_count,
            "recommend_count": row.recommend_count,
            "platform": row.platform,
            "status": row.status,
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
    if source_mysql_service.is_source_mysql(db):
        row = db.execute(
            text("SELECT * FROM cxt_videos WHERE id = :video_id LIMIT 1"),
            {"video_id": video_id},
        ).mappings().first()
        return _success({} if row is None else {
            "id": row["id"],
            "title": row["title"],
            "author": row["author"],
            "sec_user_id": row["sec_user_id"],
            "aweme_id": row["aweme_id"],
            "video_url": row["video_url"],
            "cover_url": row["cover_url"],
            "created_at": _dt(row["created_at"]),
        })
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
    if source_mysql_service.is_source_mysql(db):
        rows = db.execute(
            text(
                """
                SELECT *
                FROM system_announcements
                WHERE is_enabled = 1
                  AND platform IN ('web', 'both')
                ORDER BY priority DESC, id DESC
                LIMIT 5
                """
            )
        ).mappings().all()
        return _success([
            {
                "id": row["id"],
                "title": row["title"],
                "content": row["content"],
                "level": "warning" if int(row["priority"] or 0) > 0 else "info",
                "priority": row["priority"],
                "pinned": 1 if int(row["priority"] or 0) > 0 else 0,
                "active": row["is_enabled"],
                "is_enabled": row["is_enabled"],
                "platform": row["platform"],
                "link_url": row["link_url"],
                "link_text": row["link_text"],
                "target_roles": row["target_roles"],
                "target_users": row["target_users"],
                "attachments": row["attachments"],
                "created_at": _dt(row["created_at"]),
                "updated_at": _dt(row["updated_at"]),
            }
            for row in rows
        ])
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
    if source_mysql_service.is_source_mysql(db):
        where = []
        params: dict[str, Any] = {}
        if platform:
            where.append("platform = :platform")
            params["platform"] = platform
        sql_where = " AND ".join(where) if where else "1=1"
        total = int(db.execute(text(f"SELECT COUNT(*) FROM system_announcements WHERE {sql_where}"), params).scalar_one())
        rows = db.execute(
            text(f"SELECT * FROM system_announcements WHERE {sql_where} ORDER BY priority DESC, id DESC LIMIT :limit OFFSET :offset"),
            {**params, "limit": per_page, "offset": (page - 1) * per_page},
        ).mappings().all()
        data = [
            {
                "id": row["id"],
                "title": row["title"],
                "content": row["content"],
                "level": "warning" if int(row["priority"] or 0) > 0 else "info",
                "priority": row["priority"],
                "pinned": 1 if int(row["priority"] or 0) > 0 else 0,
                "active": row["is_enabled"],
                "is_enabled": row["is_enabled"],
                "platform": row["platform"],
                "link_url": row["link_url"],
                "link_text": row["link_text"],
                "target_roles": row["target_roles"],
                "target_users": row["target_users"],
                "attachments": row["attachments"],
                "organization_id": None,
                "created_at": _dt(row["created_at"]),
                "updated_at": _dt(row["updated_at"]),
            }
            for row in rows
        ]
        return _success({"announcements": data, "total": total}, total=total)
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
    return _success(
        {
            "auth_code": getattr(user, "default_auth_code", None) or user.phone or user.username,
            "source": "user.default_auth_code_or_phone_or_username",
        }
    )


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
    if source_mysql_service.is_source_mysql(db):
        where: list[str] = []
        params: dict[str, Any] = {}
        if operator_account:
            where.append("operator_account = :operator_account")
            params["operator_account"] = operator_account
        if status:
            where.append("status = :status")
            params["status"] = status
        if search:
            where.append("(kuaishou_id LIKE :search OR machine_id LIKE :search OR operator_account LIKE :search)")
            params["search"] = f"%{search}%"
        total = _source_count(db, "kuaishou_account_bindings", where, params)
        sql_where = " AND ".join(where) if where else "1=1"
        rows = db.execute(
            text(f"SELECT * FROM kuaishou_account_bindings WHERE {sql_where} ORDER BY id DESC LIMIT :limit OFFSET :offset"),
            {**params, "limit": per_page, "offset": (page - 1) * per_page},
        ).mappings().all()
        data = [
            {
                "id": row["id"],
                "source_id": None,
                "account_id": None,
                "user_id": None,
                "kuaishou_id": row["kuaishou_id"],
                "uid": row["kuaishou_id"],
                "machine_id": row["machine_id"],
                "operator_account": row["operator_account"],
                "operator": row["operator_account"],
                "status": row["status"],
                "remark": row["remark"],
                "bind_time": _dt(row["bind_time"]),
                "last_used_time": _dt(row["last_used_time"]),
                "created_at": None,
                "updated_at": None,
            }
            for row in rows
        ]
        return _success({"list": data, "total": total}, total=total)
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
    if source_mysql_service.is_source_mysql(db):
        rows = db.execute(
            text(
                """
                SELECT operator_account, COUNT(*) AS c
                FROM kuaishou_account_bindings
                GROUP BY operator_account
                ORDER BY operator_account ASC
                """
            )
        ).mappings().all()
        return _success([{"operator_account": row["operator_account"], "username": row["operator_account"], "binding_count": row["c"]} for row in rows])
    rows = db.execute(
        select(KuaishouAccountBinding.operator_account, func.count(KuaishouAccountBinding.id))
        .group_by(KuaishouAccountBinding.operator_account)
        .order_by(KuaishouAccountBinding.operator_account.asc())
    ).all()
    return _success([{"operator_account": name, "username": name, "binding_count": count} for name, count in rows])


@router.get("/bindings/operator/{operator_id}")
async def operator_bindings(operator_id: str, db: DbSession, user: CurrentUser):
    if source_mysql_service.is_source_mysql(db):
        target = source_mysql_service.get_user_by_id(db, _as_int(operator_id, -1))
        operator_account = target.username if target else operator_id
        rows = db.execute(
            text("SELECT * FROM kuaishou_account_bindings WHERE operator_account = :operator_account"),
            {"operator_account": operator_account},
        ).mappings().all()
        return _success([
            {
                "id": row["id"],
                "kuaishou_id": row["kuaishou_id"],
                "uid": row["kuaishou_id"],
                "machine_id": row["machine_id"],
                "operator_account": row["operator_account"],
                "operator": row["operator_account"],
                "status": row["status"],
                "remark": row["remark"],
                "bind_time": _dt(row["bind_time"]),
                "last_used_time": _dt(row["last_used_time"]),
            }
            for row in rows
        ])
    target = db.get(User, _as_int(operator_id, -1))
    operator_account = target.username if target else operator_id
    rows = db.execute(
        select(KuaishouAccountBinding).where(KuaishouAccountBinding.operator_account == operator_account)
    ).scalars().all()
    return _success([_binding_payload(row) for row in rows])


@router.get("/bindings/stats")
async def binding_stats(db: DbSession):
    if source_mysql_service.is_source_mysql(db):
        row = db.execute(
            text(
                """
                SELECT COUNT(*) AS total,
                       SUM(CASE WHEN status = 'active' THEN 1 ELSE 0 END) AS active
                FROM kuaishou_account_bindings
                """
            )
        ).mappings().one()
        total = int(row["total"] or 0)
        active = int(row["active"] or 0)
        return _success({"total": total, "active": active, "disabled": max(total - active, 0)})
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
    if source_mysql_service.is_source_mysql(db):
        where, params = _source_org_clause(user, "org_id")
        sql_where = " AND ".join(where) if where else "1=1"
        row = db.execute(
            text(
                f"""
                SELECT COUNT(*) AS total,
                       SUM(CASE WHEN contract_renew_status IN (1, 8, 'active') THEN 1 ELSE 0 END) AS active
                FROM spark_org_members
                WHERE {sql_where}
                """
            ),
            params,
        ).mappings().one()
        total = int(row["total"] or 0)
        active = int(row["active"] or 0)
        return _success({"total": total, "active": active, "pending": max(total - active, 0)})
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
async def account_stats(db: DbSession, user: CurrentUser, uid: str | None = None):
    if not uid:
        return _success({"uid": "", "total": 0, "success": 0, "failed": 0, "tasks": []})
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
    if source_mysql_service.is_source_mysql(db):
        return _success(_source_income_role_stats(db, user, table="fluorescent_income_archive", amount_column="total_amount", org_column="org_id"))
    return _success(_income_stats_by_role(db, user, FireflyIncome))


@router.get("/firefly/income/stats/operators-summary")
async def firefly_income_operators_summary(db: DbSession, user: CurrentUser):
    if source_mysql_service.is_source_mysql(db):
        stats = _source_income_stats(db, user, table="fluorescent_income_archive", amount_column="total_amount", org_column="org_id")
        return _success({"operators": [], **stats})
    return _success(_income_operators_summary(db, user, FireflyIncome))


@router.get("/firefly/income/wallet-stats")
async def firefly_income_wallet_stats(db: DbSession, user: CurrentUser):
    if source_mysql_service.is_source_mysql(db):
        return _success(_source_income_wallet_stats(db, user, table="fluorescent_income_archive", amount_column="total_amount", org_column="org_id"))
    return _success(_income_wallet_stats(db, user, FireflyIncome))


@router.post("/firefly/income/search-by-uids")
async def search_firefly_income_by_uids(request: Request, db: DbSession, user: CurrentUser):
    body = await request.json()
    uids = [int(item) for item in body.get("uids", []) if str(item).isdigit()]
    stmt = select(FireflyIncome).where(FireflyIncome.member_id.in_(uids))
    stmt = _apply_org_scope(stmt, FireflyIncome, user)
    rows = db.execute(stmt.limit(1000)).scalars().all()
    return _success(_income_payloads(db, rows))


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
        db.add(
            FluorescentMember(
                organization_id=_as_int(item.get("org_id") or item.get("organization_id"), user.organization_id),
                member_id=member_id,
                nickname=item.get("nickname") or item.get("member_name"),
                avatar=item.get("member_head") or item.get("avatar"),
                fans_count=_as_int(item.get("fans_count")),
                in_limit=_as_bool(item.get("in_limit")),
                broker_name=item.get("broker_name"),
                org_task_num=_as_int(item.get("org_task_num")),
                total_amount=_as_float(item.get("total_amount")),
            )
        )
        created += 1
    db.commit()
    return _success({"created": created})


@router.post("/firefly/members/sync")
async def sync_firefly_members():
    return _external_not_connected("firefly_members_sync")


@router.put("/firefly/members/{member_id}")
async def update_firefly_member(member_id: int, request: Request, db: DbSession):
    row = db.get(FluorescentMember, member_id)
    if row is None:
        return _success(None, message="member not found")
    body = await request.json()
    if "nickname" in body or "member_name" in body:
        row.nickname = body.get("nickname") or body.get("member_name")
    if "member_head" in body or "avatar" in body:
        row.avatar = body.get("member_head") or body.get("avatar")
    if "fans_count" in body:
        row.fans_count = _as_int(body.get("fans_count"))
    if "in_limit" in body:
        row.in_limit = _as_bool(body.get("in_limit"))
    if "broker_name" in body:
        row.broker_name = body.get("broker_name")
    if "org_task_num" in body:
        row.org_task_num = _as_int(body.get("org_task_num"))
    if "total_amount" in body:
        row.total_amount = _as_float(body.get("total_amount"))
    db.commit()
    return _success(_member_payloads(db, [row])[0])


@router.delete("/firefly/members/{member_id}")
async def delete_firefly_member(member_id: int, db: DbSession):
    row = db.get(FluorescentMember, member_id)
    if row:
        db.delete(row)
        db.commit()
    return _success({"deleted": True})


@router.get("/firefly/members/{member_id}/all-records")
async def firefly_member_all_records(member_id: int, db: DbSession):
    member = db.get(FluorescentMember, member_id)
    real_member_id = member.member_id if member else member_id
    rows = db.execute(select(FluorescentIncome).where(FluorescentIncome.member_id == real_member_id).order_by(FluorescentIncome.id.desc()).limit(1000)).scalars().all()
    return _success(_income_payloads(db, rows))


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
    if source_mysql_service.is_source_mysql(db):
        return _success(_source_income_role_stats(db, user, table="spark_income_archive", amount_column="total_amount", org_column="org_id"))
    return _success(_income_stats_by_role(db, user, IncomeArchive))


@router.get("/spark/archive/stats/operators-summary")
async def spark_archive_operators_summary(db: DbSession, user: CurrentUser):
    if source_mysql_service.is_source_mysql(db):
        stats = _source_income_stats(db, user, table="spark_income_archive", amount_column="total_amount", org_column="org_id")
        return _success({"operators": [], **stats})
    return _success(_income_operators_summary(db, user, IncomeArchive))


@router.get("/spark/archive/wallet-stats")
async def spark_archive_wallet_stats(db: DbSession, user: CurrentUser):
    if source_mysql_service.is_source_mysql(db):
        return _success(_source_income_wallet_stats(db, user, table="spark_income_archive", amount_column="total_amount", org_column="org_id"))
    return _success(_income_wallet_stats(db, user, IncomeArchive))


@router.post("/spark/archive/search-by-uids")
async def search_spark_archive_by_uids(request: Request, db: DbSession, user: CurrentUser):
    body = await request.json()
    uids = [int(item) for item in body.get("uids", []) if str(item).isdigit()]
    stmt = select(IncomeArchive).where(IncomeArchive.member_id.in_(uids), IncomeArchive.program_type == "spark")
    stmt = _apply_org_scope(stmt, IncomeArchive, user)
    rows = db.execute(stmt.limit(1000)).scalars().all()
    return _success(_income_payloads(db, rows))


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
    if source_mysql_service.is_source_mysql(db):
        where, params = _source_org_clause(user, "org_id")
        if search:
            where.append("(photo_id LIKE :search OR title LIKE :search OR member_name LIKE :search)")
            params["search"] = f"%{search}%"
        total = _source_count(db, "spark_photos", where, params)
        sql_where = " AND ".join(where) if where else "1=1"
        if total:
            rows = db.execute(
                text(f"SELECT * FROM spark_photos WHERE {sql_where} ORDER BY id DESC LIMIT :limit OFFSET :offset"),
                {**params, "limit": per_page, "offset": (page - 1) * per_page},
            ).mappings().all()
            data = [
                    {
                        "id": row["id"],
                        "source_id": None,
                        "photo_id": row["photo_id"],
                        "work_id": row["photo_id"],
                        "member_id": str(row["member_id"]) if row["member_id"] is not None else None,
                        "uid": str(row["member_id"]) if row["member_id"] is not None else None,
                        "member_name": row["member_name"],
                        "nickname": row["member_name"],
                        "title": row["title"],
                        "description": row["title"],
                        "view_count": row["view_count"] or 0,
                        "like_count": row["like_count"] or 0,
                        "comment_count": row["comment_count"] or 0,
                        "duration": row["duration"],
                        "publish_time": row["publish_time"],
                        "publish_date": _dt(row["publish_date"]),
                        "cover_url": row["cover_url"],
                        "thumbnail": row["cover_url"],
                        "play_url": row["play_url"],
                        "avatar_url": row["avatar_url"],
                        "organization_id": row["org_id"],
                        "account_id": None,
                        "created_at": _dt(row["created_at"]),
                        "updated_at": _dt(row["updated_at"]),
                    }
                    for row in rows
                ]
        else:
            fallback_where, fallback_params = _source_org_clause(user, "org_id")
            if search:
                fallback_where.append("(photo_id LIKE :search OR caption LIKE :search OR username LIKE :search)")
                fallback_params["search"] = f"%{search}%"
            fallback_sql_where = " AND ".join(fallback_where) if fallback_where else "1=1"
            total = _source_count(db, "spark_violation_photos", fallback_where, fallback_params)
            rows = db.execute(
                text(f"SELECT * FROM spark_violation_photos WHERE {fallback_sql_where} ORDER BY id DESC LIMIT :limit OFFSET :offset"),
                {**fallback_params, "limit": per_page, "offset": (page - 1) * per_page},
            ).mappings().all()
            data = [
                {
                    "id": row["id"],
                    "source_id": row["id"],
                    "photo_id": row["photo_id"],
                    "work_id": row["photo_id"],
                    "member_id": str(row["user_id"]) if row["user_id"] is not None else None,
                    "uid": str(row["user_id"]) if row["user_id"] is not None else None,
                    "member_name": row["username"],
                    "nickname": row["username"],
                    "title": row["caption"],
                    "description": row["reason"] or row["caption"],
                    "view_count": row["view_count"] or 0,
                    "like_count": row["like_count"] or 0,
                    "comment_count": row["comment_count"] or 0,
                    "duration": None,
                    "publish_time": row["publish_time"],
                    "publish_date": _dt(row["publish_date"]),
                    "cover_url": row["thumb_url"],
                    "thumbnail": row["thumb_url"],
                    "play_url": row["media_url"],
                    "avatar_url": row["avatar_url"],
                    "organization_id": row["org_id"],
                    "account_id": None,
                    "status": row["status_desc"] or row["status"],
                    "created_at": _dt(row["created_at"]),
                    "updated_at": _dt(row["updated_at"]),
                    "source": "spark_violation_photos",
                }
                for row in rows
            ]
        return _success(
            data,
            total=total,
        )
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
    if source_mysql_service.is_source_mysql(db):
        where, params = _source_org_clause(user, "org_id")
        if search:
            where.append("(drama_title LIKE :search OR username LIKE :search OR reason LIKE :search)")
            params["search"] = f"%{search}%"
        total = _source_count(db, "spark_violation_dramas", where, params)
        sql_where = " AND ".join(where) if where else "1=1"
        rows = db.execute(
            text(f"SELECT * FROM spark_violation_dramas WHERE {sql_where} ORDER BY violation_count DESC, id DESC LIMIT :limit OFFSET :offset"),
            {**params, "limit": per_page, "offset": (page - 1) * per_page},
        ).mappings().all()
        return _success(
            [
                {
                    "id": row["id"],
                    "source_id": None,
                    "drama_title": row["drama_title"],
                    "title": row["drama_title"],
                    "drama_name": row["drama_title"],
                    "source_photo_id": row["source_photo_id"],
                    "source_caption": row["source_caption"],
                    "user_id": row["user_id"],
                    "uid": str(row["user_id"]) if row["user_id"] is not None else None,
                    "username": row["username"],
                    "violation_count": row["violation_count"],
                    "last_violation_time": row["last_violation_time"],
                    "last_violation_date": _dt(row["last_violation_date"]),
                    "sub_biz": row["sub_biz"],
                    "status_desc": row["status_desc"],
                    "reason": row["reason"],
                    "media_url": row["media_url"],
                    "thumb_url": row["thumb_url"],
                    "thumbnail": row["thumb_url"],
                    "broker_name": row["broker_name"],
                    "is_blacklisted": 1 if _as_bool(row["is_blacklisted"]) else 0,
                    "blacklisted_at": _dt(row["blacklisted_at"]),
                    "organization_id": row["org_id"],
                    "created_at": _dt(row["created_at"]),
                    "updated_at": _dt(row["updated_at"]),
                }
                for row in rows
            ],
            total=total,
        )
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
async def config(db: DbSession):
    if source_mysql_service.is_source_mysql(db):
        rows = db.execute(
            text("SELECT config_key, config_value, description, updated_at FROM system_config ORDER BY id ASC")
        ).mappings().all()
        return _success(
            {
                row["config_key"]: {
                    "value": row["config_value"],
                    "description": row["description"],
                    "updated_at": _dt(row["updated_at"]),
                }
                for row in rows
            }
        )
    return _success({})


@router.post("/config")
async def update_config(request: Request, db: DbSession):
    body = await request.json()
    if source_mysql_service.is_source_mysql(db):
        items = body.get("items") if isinstance(body, dict) else None
        if not items:
            key = body.get("key") or body.get("config_key")
            if key:
                items = [{"config_key": key, "config_value": body.get("value", body.get("config_value")), "description": body.get("description")}]
            else:
                items = [
                    {"config_key": key, "config_value": value.get("value") if isinstance(value, dict) else value}
                    for key, value in body.items()
                    if key not in {"items"}
                ]
        updated = 0
        for item in items:
            key = str(item.get("config_key") or item.get("key") or "").strip()
            if not key:
                continue
            db.execute(
                text(
                    """
                    INSERT INTO system_config (config_key, config_value, description, created_at, updated_at)
                    VALUES (:key, :value, :description, NOW(), NOW())
                    ON DUPLICATE KEY UPDATE config_value = VALUES(config_value), description = VALUES(description), updated_at = NOW()
                    """
                ),
                {"key": key, "value": item.get("config_value", item.get("value")), "description": item.get("description")},
            )
            updated += 1
        db.commit()
        return _success({"updated": updated})
    return _success({"updated": 0})
