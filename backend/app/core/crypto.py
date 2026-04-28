"""轻量加密 helper — Cookie / 敏感字段 AES-GCM.

依赖: `cryptography` (requirements.txt 含). 若 dev 临时缺失会 fallback base64.
Phase 4: 切 KMS / HSM (key 不落地, 由 KMS 加签).
"""
from __future__ import annotations

import base64
import hashlib
import os
import warnings

from app.core.config import settings


try:
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM  # type: ignore
    HAS_CRYPTO = True
except ImportError:
    AESGCM = None  # type: ignore
    HAS_CRYPTO = False
    warnings.warn(
        "cryptography 未装, Cookie 走 base64 fallback (仅 dev). "
        "生产请 pip install cryptography>=42",
        RuntimeWarning,
        stacklevel=2,
    )


def _key_bytes() -> bytes:
    """从 SECRET_KEY 派生 256-bit AES key."""
    return hashlib.sha256(settings.SECRET_KEY.encode("utf-8")).digest()


def encrypt_str(plain: str) -> tuple[bytes, bytes, bytes, str]:
    """加密字符串.

    返 (ciphertext, iv, tag, preview)
    Phase 1 dev (无 cryptography): ciphertext = base64 of plain, iv/tag 占位.
    Phase 1 prod: AES-GCM, IV 12 bytes random, tag 16 bytes.
    """
    preview = _make_preview(plain)
    if not HAS_CRYPTO:
        return (
            base64.b64encode(plain.encode("utf-8")),
            b"\x00" * 12,
            b"\x00" * 16,
            preview,
        )

    aes = AESGCM(_key_bytes())
    iv = os.urandom(12)
    raw = aes.encrypt(iv, plain.encode("utf-8"), None)
    # AESGCM 把 tag 拼在 ciphertext 末尾, 这里拆开存便于 schema 清晰
    ciphertext, tag = raw[:-16], raw[-16:]
    return ciphertext, iv, tag, preview


def decrypt_str(ciphertext: bytes, iv: bytes, tag: bytes) -> str:
    """解密. 返明文."""
    if not HAS_CRYPTO:
        # Phase 1 dev fallback
        return base64.b64decode(ciphertext).decode("utf-8")

    aes = AESGCM(_key_bytes())
    raw = ciphertext + tag
    return aes.decrypt(iv, raw, None).decode("utf-8")


def _make_preview(plain: str, head_len: int = 8, tail_len: int = 8) -> str:
    """脱敏 preview.

    例: "abcdef0123456789xyz" -> "abcdef01***6789xyz"
    """
    if not plain:
        return ""
    s = plain.strip()
    if len(s) <= head_len + tail_len + 3:
        return "***"
    head = s[:head_len]
    tail = s[-tail_len:]
    return f"{head}***{tail}"
