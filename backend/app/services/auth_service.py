"""认证业务逻辑.

集中处理:
  - login (用户名/手机号 + 密码)
  - activate (卡密首次激活, 自动建 user)
  - refresh (refresh_token → 新 access)
  - heartbeat (校验 license 有效期 + fingerprint)
"""
from __future__ import annotations

import secrets
import string
from datetime import datetime, timedelta, timezone

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.core.errors import (
    AUTH_401,
    AUTH_402,
    AUTH_423,
    AUTH_498,
    AuthError,
    BizError,
    ConflictError,
    ResourceNotFound,
)
from app.core.logging import logger
from app.core.security import (
    encode_token,
    fingerprint_match,
    hash_password,
    normalize_fingerprint,
    verify_password,
)
from app.models import License, Organization, User, UserSession
from app.services import source_mysql_service


_now = lambda: datetime.now(timezone.utc)  # noqa: E731


def _ensure_aware(dt: datetime | None) -> datetime | None:
    """SQLite 存 datetime 时丢失时区, 取出来变 naive. 统一补 UTC tz."""
    if dt is None:
        return None
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt


# ============================================================
# Login
# ============================================================

def login(
    db: Session,
    *,
    username: str | None,
    phone: str | None,
    password: str,
    fingerprint: str | None = None,
    user_agent: str | None = None,
    ip: str | None = None,
) -> tuple[User, str, str, datetime]:
    """返 (user, access_token, refresh_token, refresh_expires_at)."""
    if not username and not phone:
        raise AuthError(AUTH_401, message="请提供用户名或手机号")

    if source_mysql_service.is_source_mysql(db):
        user = source_mysql_service.get_user_by_login(db, username=username, phone=phone)
    else:
        stmt = select(User).where(User.deleted_at.is_(None))
        if username:
            stmt = stmt.where(User.username == username)
        else:
            stmt = stmt.where(User.phone == phone)
        user = db.execute(stmt).scalar_one_or_none()
    if not user:
        raise AuthError(AUTH_401, message="用户名或密码错误")

    if user.locked_until and _ensure_aware(user.locked_until) > _now():
        raise AuthError(AUTH_423, message="账号已被锁定, 请稍后再试")

    if not user.is_active:
        raise AuthError(AUTH_423, message="账号已停用, 请联系客服")

    if not verify_password(password, user.password_hash):
        if source_mysql_service.is_source_mysql(db):
            raise AuthError(AUTH_401, message="鐢ㄦ埛鍚嶆垨瀵嗙爜閿欒")
        user.failed_login_count = (user.failed_login_count or 0) + 1
        if user.failed_login_count >= 5:
            user.locked_until = _now() + timedelta(minutes=15)
            user.failed_login_count = 0
            logger.warning(f"User {user.username} locked 15min for 5 failed logins")
        db.commit()
        raise AuthError(AUTH_401, message="用户名或密码错误")

    # 校验硬件指纹 — 仅对绑定了 license 的 user 生效
    if fingerprint:
        license = _find_active_license_for_user(db, user.id)
        if license and license.device_fingerprint:
            if not fingerprint_match(fingerprint, license.device_fingerprint):
                logger.warning(
                    f"Fingerprint mismatch for user {user.username}: "
                    f"client={fingerprint[:8]}... expected={license.device_fingerprint[:8]}..."
                )
                raise AuthError(AUTH_498, message="登录设备已变更, 请重新激活")

    # 成功: 重置失败计数, 记 last_login
    source_mysql = source_mysql_service.is_source_mysql(db)
    if source_mysql:
        user = source_mysql_service.update_user_fields(
            db,
            user.id,
            {
                "last_login": _now(),
                "login_count": int(getattr(user, "login_count", 0) or 0) + 1,
                "is_active": 1,
            },
        ) or user
    else:
        user.failed_login_count = 0
        user.last_login_at = _now()
        user.last_login_ip = ip

    plan_tier = None
    license = _find_active_license_for_user(db, user.id)
    if license:
        plan_tier = license.plan_tier

    access, _, _ = encode_token(
        user_id=user.id,
        organization_id=user.organization_id,
        token_type="access",
        fingerprint=fingerprint,
        plan_tier=plan_tier,
    )
    refresh, jti, refresh_exp = encode_token(
        user_id=user.id,
        organization_id=user.organization_id,
        token_type="refresh",
        fingerprint=fingerprint,
        plan_tier=plan_tier,
    )

    sess = UserSession(
        user_id=user.id,
        jti=jti,
        fingerprint=fingerprint,
        user_agent=user_agent,
        ip=ip,
        expires_at=refresh_exp,
        last_seen_at=_now(),
    )
    db.add(sess)
    db.commit()
    if not source_mysql:
        db.refresh(user)

    logger.info(f"login ok: user={user.username} ip={ip} fp={fingerprint and fingerprint[:8]}")
    return user, access, refresh, refresh_exp


# ============================================================
# Activate (卡密首次激活)
# ============================================================

def activate(
    db: Session,
    *,
    license_key: str,
    phone: str,
    fingerprint: str,
    client_version: str | None = None,
    os_info: str | None = None,
    user_agent: str | None = None,
    ip: str | None = None,
) -> tuple[User, License, str, str, datetime, str | None]:
    """卡密首次激活.

    返 (user, license, access, refresh, refresh_exp, initial_password_or_None).

    流程:
      1. 校验 license_key 存在 + 未过期 + status='unused' or (active 且 fingerprint 匹配重激活)
      2. 查 phone 是否已有 user (同手机号续卡场景)
      3. 否则: 创建新 organization (org_code=phone) + user (username=phone)
      4. 绑定 license.device_fingerprint
      5. 签 token
    """
    fingerprint = normalize_fingerprint(fingerprint)

    license = db.execute(
        select(License).where(License.license_key == license_key)
    ).scalar_one_or_none()

    if not license:
        raise ResourceNotFound("卡密不存在或已作废")

    now = _now()
    if _ensure_aware(license.expires_at) < now:
        raise BizError(AUTH_402, message="卡密已过期, 请购买新卡")

    if license.status == "revoked":
        raise BizError(AUTH_402, message="卡密已被作废, 请联系客服")
    if license.status == "locked":
        raise AuthError(AUTH_423, message="卡密已锁定, 请联系客服")

    # 重激活场景: 同 fingerprint 可重新拿 token
    if license.status == "active":
        if fingerprint_match(fingerprint, license.device_fingerprint):
            user = db.get(User, license.bound_user_id) if license.bound_user_id else None
            if user:
                logger.info(f"reactivate license {license_key[-8:]} for user={user.username}")
                return _issue_after_activation(
                    db, user, license, fingerprint, user_agent=user_agent, ip=ip,
                    initial_password=None,
                )
        raise BizError(
            AUTH_498,
            message="该卡密已在另一设备激活, 如需换机请联系客服",
        )

    # status == 'unused' → 首次激活
    org, user, initial_pw = _ensure_user_for_phone(db, phone)
    license.activated_at = now
    license.device_fingerprint = fingerprint
    license.device_os_info = os_info
    license.client_version = client_version
    license.bound_user_id = user.id
    license.bound_organization_id = org.id
    license.bound_phone = phone
    license.status = "active"
    db.flush()

    return _issue_after_activation(
        db, user, license, fingerprint, user_agent=user_agent, ip=ip,
        initial_password=initial_pw,
    )


def _issue_after_activation(
    db: Session,
    user: User,
    license: License,
    fingerprint: str,
    *,
    user_agent: str | None,
    ip: str | None,
    initial_password: str | None,
) -> tuple[User, License, str, str, datetime, str | None]:
    access, _, _ = encode_token(
        user_id=user.id,
        organization_id=user.organization_id,
        token_type="access",
        fingerprint=fingerprint,
        plan_tier=license.plan_tier,
    )
    refresh, jti, refresh_exp = encode_token(
        user_id=user.id,
        organization_id=user.organization_id,
        token_type="refresh",
        fingerprint=fingerprint,
        plan_tier=license.plan_tier,
    )
    sess = UserSession(
        user_id=user.id,
        jti=jti,
        fingerprint=fingerprint,
        user_agent=user_agent,
        ip=ip,
        expires_at=refresh_exp,
        last_seen_at=_now(),
    )
    db.add(sess)
    user.last_login_at = _now()
    user.last_login_ip = ip
    db.commit()
    db.refresh(user)
    db.refresh(license)
    return user, license, access, refresh, refresh_exp, initial_password


def _ensure_user_for_phone(db: Session, phone: str) -> tuple[Organization, User, str | None]:
    """如果手机号已存在, 复用; 否则建组织 + user.

    返 (org, user, initial_password_or_None_if_existing).
    """
    user = db.execute(select(User).where(User.phone == phone)).scalar_one_or_none()
    if user:
        org = db.get(Organization, user.organization_id)
        return org, user, None

    # 新建 org + user
    org_code = f"u_{phone[-8:]}"  # 简单后 8 位
    org = Organization(
        name=f"{phone} 工作室",
        org_code=org_code,
        org_type="personal",
        contact_phone=phone,
        plan_tier="basic",
    )
    db.add(org)
    db.flush()

    initial_pw = _gen_initial_password()
    user = User(
        organization_id=org.id,
        username=phone,
        phone=phone,
        password_hash=hash_password(initial_pw),
        display_name=phone,
        is_active=True,
        must_change_pw=True,
    )
    db.add(user)
    db.flush()
    return org, user, initial_pw


def _gen_initial_password() -> str:
    chars = string.ascii_letters + string.digits
    return "".join(secrets.choice(chars) for _ in range(12))


# ============================================================
# Refresh
# ============================================================

def refresh(
    db: Session, *, refresh_token: str, fingerprint: str | None = None
) -> tuple[str, str, datetime]:
    """返 (new_access, new_refresh, refresh_exp). 滚动续期, 老 refresh 作废."""
    from app.core.security import decode_token

    payload = decode_token(refresh_token)
    if payload.get("typ") != "refresh":
        raise AuthError(AUTH_401, message="凭证类型不正确")

    jti = payload.get("jti")
    user_id = int(payload.get("sub"))

    sess = db.execute(
        select(UserSession).where(UserSession.jti == jti)
    ).scalar_one_or_none()
    if not sess or sess.revoked:
        raise AuthError(AUTH_401, message="登录会话已失效, 请重新登录")
    if _ensure_aware(sess.expires_at) < _now():
        raise AuthError(AUTH_401, message="登录会话已过期, 请重新登录")

    user = source_mysql_service.get_user_by_id(db, user_id) if source_mysql_service.is_source_mysql(db) else db.get(User, user_id)
    if not user or getattr(user, "deleted_at", None) is not None or not user.is_active:
        raise AuthError(AUTH_401, message="账号不可用")

    plan_tier = None
    license = _find_active_license_for_user(db, user.id)
    if license:
        plan_tier = license.plan_tier

    new_access, _, _ = encode_token(
        user_id=user.id,
        organization_id=user.organization_id,
        token_type="access",
        fingerprint=fingerprint,
        plan_tier=plan_tier,
    )
    new_refresh, new_jti, new_exp = encode_token(
        user_id=user.id,
        organization_id=user.organization_id,
        token_type="refresh",
        fingerprint=fingerprint,
        plan_tier=plan_tier,
    )

    # 旧 session 作废, 创建新 session
    sess.revoked = True
    new_sess = UserSession(
        user_id=user.id,
        jti=new_jti,
        fingerprint=fingerprint or sess.fingerprint,
        user_agent=sess.user_agent,
        ip=sess.ip,
        expires_at=new_exp,
        last_seen_at=_now(),
    )
    db.add(new_sess)
    db.commit()

    return new_access, new_refresh, new_exp


# ============================================================
# Heartbeat
# ============================================================

def heartbeat(
    db: Session,
    *,
    user: User,
    fingerprint: str | None = None,
) -> dict:
    """返 license 状态摘要."""
    license = _find_active_license_for_user(db, user.id)

    if not license:
        # basic 用户 (无 license)
        return {
            "license_status": "active",
            "expires_at": None,
            "days_left": None,
        }

    # 校验指纹 (如客户端传了)
    if fingerprint and license.device_fingerprint:
        if not fingerprint_match(fingerprint, license.device_fingerprint):
            raise AuthError(AUTH_498, message="登录设备已变更, 请重新激活")

    now = _now()
    exp_aware = _ensure_aware(license.expires_at)
    days_left = max(0, (exp_aware - now).days)

    if exp_aware < now:
        status = "expired"
    elif days_left <= 7:
        status = "expiring_soon"
    else:
        status = "active"

    return {
        "license_status": status,
        "expires_at": license.expires_at,
        "days_left": days_left,
    }


# ============================================================
# Helpers
# ============================================================

def _find_active_license_for_user(db: Session, user_id: int) -> License | None:
    return db.execute(
        select(License)
        .where(License.bound_user_id == user_id)
        .where(License.status == "active")
        .order_by(License.expires_at.desc())
    ).scalar_one_or_none()
