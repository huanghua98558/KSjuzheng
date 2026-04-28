"""安全核心: 密码 hash + JWT 编码/解码 + 硬件指纹工具.

JWT payload 标准字段:
    sub      : user_id (str)
    org      : organization_id (int)
    typ      : 'access' / 'refresh'
    fp       : fingerprint (str, optional)
    plan     : plan_tier (str, optional)
    iat      : issued at (int unix)
    exp      : expire at (int unix)
    jti      : token id (uuid hex, refresh token 必须)
"""
from __future__ import annotations

import hashlib
import secrets
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Literal

import bcrypt
import jwt as jwt_lib

from app.core.config import settings
from app.core.errors import AUTH_401, AuthError


# ============================================================
# 密码 hash
# ============================================================

def hash_password(plain: str) -> str:
    """返 bcrypt utf-8 hash str."""
    return bcrypt.hashpw(plain.encode("utf-8"), bcrypt.gensalt(rounds=12)).decode("utf-8")


def verify_password(plain: str, hashed: str) -> bool:
    if not hashed:
        return False
    try:
        return bcrypt.checkpw(plain.encode("utf-8"), hashed.encode("utf-8"))
    except Exception:
        return False


# ============================================================
# JWT
# ============================================================

TokenType = Literal["access", "refresh"]


def _now_utc() -> datetime:
    return datetime.now(timezone.utc)


def encode_token(
    *,
    user_id: int,
    organization_id: int | None,
    token_type: TokenType,
    fingerprint: str | None = None,
    plan_tier: str | None = None,
    extra: dict[str, Any] | None = None,
) -> tuple[str, str, datetime]:
    """生成 JWT.

    返回 (token_str, jti, expires_at).
    """
    iat = _now_utc()
    if token_type == "access":
        exp = iat + timedelta(minutes=settings.JWT_ACCESS_TTL_MIN)
    else:
        exp = iat + timedelta(days=settings.JWT_REFRESH_TTL_DAYS)

    jti = uuid.uuid4().hex

    payload: dict[str, Any] = {
        "sub": str(user_id),
        "org": organization_id,
        "typ": token_type,
        "iat": int(iat.timestamp()),
        "exp": int(exp.timestamp()),
        "jti": jti,
    }
    if fingerprint:
        payload["fp"] = fingerprint
    if plan_tier:
        payload["plan"] = plan_tier
    if extra:
        payload.update(extra)

    token = jwt_lib.encode(payload, settings.SECRET_KEY, algorithm=settings.JWT_ALG)
    return token, jti, exp


def decode_token(token: str) -> dict[str, Any]:
    """解码并校验 JWT. 失败抛 AuthError(AUTH_401)."""
    try:
        payload = jwt_lib.decode(token, settings.SECRET_KEY, algorithms=[settings.JWT_ALG])
        return payload
    except jwt_lib.ExpiredSignatureError as ex:
        raise AuthError(AUTH_401, message="登录已过期, 请重新登录", details={"e": str(ex)})
    except jwt_lib.InvalidTokenError as ex:
        raise AuthError(AUTH_401, message="登录凭证无效, 请重新登录", details={"e": str(ex)})


# ============================================================
# 硬件指纹工具 (服务端只校验, 不计算; 计算由客户端做)
# ============================================================

def normalize_fingerprint(fp: str) -> str:
    """规范化客户端传来的指纹 — 保持 lowercase 64-char hex."""
    fp = (fp or "").strip().lower()
    if len(fp) > 64:
        fp = fp[:64]
    return fp


def fingerprint_match(client_fp: str, license_fp: str | None) -> bool:
    if not license_fp:
        return False  # license 未绑定, 任何指纹都不匹配
    return normalize_fingerprint(client_fp) == normalize_fingerprint(license_fp)


# ============================================================
# 卡密生成 (运维用)
# ============================================================

def generate_license_key(prefix: str = "KS") -> str:
    """生成卡密: KS-XXXX-XXXX-XXXX-XXXX (16 hex chars 分组).

    例: KS-A8F2-C7D4-9B1E-3F60
    """
    raw = secrets.token_hex(8).upper()  # 16 chars
    groups = [raw[i:i + 4] for i in range(0, 16, 4)]
    return f"{prefix}-" + "-".join(groups)


def hash_license_key(key: str) -> str:
    """卡密入库前可选 hash. Phase 1 直接存原值, Phase 4 改 hash."""
    return hashlib.sha256(key.encode("utf-8")).hexdigest()
