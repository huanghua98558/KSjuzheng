"""收益字段脱敏 helper.

按 user.commission_rate_visible / commission_amount_visible / total_income_visible
对收益相关字段返 None.

设计:
  - 调用方传 dict (model_dump 后), 返脱敏后的 dict
  - super_admin 不脱敏 (运维需看真值)
  - 自己看自己的钱包 / 收益 → 不脱敏
"""
from __future__ import annotations

from app.models import User


_INCOME_AMOUNT_KEYS = ("income_amount", "total_amount", "gross_amount")
_COMMISSION_RATE_KEYS = ("commission_rate",)
_COMMISSION_AMOUNT_KEYS = ("commission_amount",)


def mask_income_record(record: dict, viewer: User, owner_user_id: int | None = None) -> dict:
    """脱敏单条收益记录.

    `viewer` = 当前查看者
    `owner_user_id` = 该记录归属者 (如可知). None 时按 viewer 自己的可见性判断.

    规则:
      - super_admin / is_superadmin: 不脱敏
      - viewer == owner: 不脱敏 (自己的不藏)
      - 其他: 按 viewer.commission_*_visible 决定
    """
    if viewer.is_superadmin or viewer.role == "super_admin":
        return record
    if owner_user_id is not None and owner_user_id == viewer.id:
        return record

    if not viewer.commission_rate_visible:
        for k in _COMMISSION_RATE_KEYS:
            if k in record:
                record[k] = None

    if not viewer.commission_amount_visible:
        for k in _COMMISSION_AMOUNT_KEYS:
            if k in record:
                record[k] = None

    if not viewer.total_income_visible:
        for k in _INCOME_AMOUNT_KEYS:
            if k in record:
                record[k] = None

    return record


def mask_income_list(records: list[dict], viewer: User) -> list[dict]:
    """批量脱敏 (无 owner 信息时按 viewer 自己脱敏)."""
    return [mask_income_record(r, viewer) for r in records]
