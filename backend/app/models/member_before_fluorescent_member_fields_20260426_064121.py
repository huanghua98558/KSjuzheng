"""L4 计划成员层 — 机构成员 / 星火 / 萤光 / 荧光 / 违规作品.

对应 MODULE_SPEC §5 §6 §7 §10 §13.
KS184 表名: org_members / spark_members / firefly_members /
fluorescent_members / violation_photos.
"""
from __future__ import annotations

from datetime import date, datetime

from sqlalchemy import (
    BigInteger,
    Boolean,
    Date,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base
from app.models._mixins import IDMixin, TimestampMixin


# ============================================================
# 5. 机构成员 (OrgMember)
# ============================================================

class OrgMember(Base, IDMixin, TimestampMixin):
    """MCN 机构成员 — 经纪人 / 续约状态 / 合同."""

    __tablename__ = "org_members"

    organization_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("organizations.id"), nullable=False, index=True
    )
    member_id: Mapped[int] = mapped_column(BigInteger, nullable=False, index=True)
    # MCN 端的 numeric member_id (numeric uid)

    user_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("users.id"), nullable=True
    )
    account_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("accounts.id"), nullable=True, index=True
    )

    nickname: Mapped[str | None] = mapped_column(String(100), nullable=True)
    avatar: Mapped[str | None] = mapped_column(String(500), nullable=True)

    fans_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    broker_name: Mapped[str | None] = mapped_column(String(100), nullable=True)
    cooperation_type: Mapped[str | None] = mapped_column(String(50), nullable=True)
    content_category: Mapped[str | None] = mapped_column(String(50), nullable=True)
    mcn_level: Mapped[str | None] = mapped_column(String(50), nullable=True)
    renewal_status: Mapped[str | None] = mapped_column(String(20), nullable=True, index=True)
    # active / expiring / expired / pending
    contract_expires_at: Mapped[date | None] = mapped_column(Date, nullable=True)

    synced_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    __table_args__ = (
        UniqueConstraint("organization_id", "member_id", name="uq_orgmem_org_mid"),
    )


# ============================================================
# 13. 星火成员 (SparkMember)
# ============================================================

class SparkMember(Base, IDMixin, TimestampMixin):
    __tablename__ = "spark_members"

    organization_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("organizations.id"), nullable=False, index=True
    )
    member_id: Mapped[int] = mapped_column(BigInteger, nullable=False, index=True)
    account_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("accounts.id"), nullable=True, index=True
    )
    nickname: Mapped[str | None] = mapped_column(String(100), nullable=True)
    fans_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    broker_name: Mapped[str | None] = mapped_column(String(100), nullable=True)
    task_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    hidden: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    first_release_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    # ★ 首播加 ID
    synced_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    __table_args__ = (
        UniqueConstraint("organization_id", "member_id", name="uq_sparkmem_org_mid"),
    )


# ============================================================
# 10. 萤光成员 (FireflyMember)
# ============================================================

class FireflyMember(Base, IDMixin, TimestampMixin):
    __tablename__ = "firefly_members"

    organization_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("organizations.id"), nullable=False, index=True
    )
    member_id: Mapped[int] = mapped_column(BigInteger, nullable=False, index=True)
    account_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("accounts.id"), nullable=True, index=True
    )
    nickname: Mapped[str | None] = mapped_column(String(100), nullable=True)
    fans_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    broker_name: Mapped[str | None] = mapped_column(String(100), nullable=True)
    total_amount: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    org_task_num: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    hidden: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    synced_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    __table_args__ = (
        UniqueConstraint("organization_id", "member_id", name="uq_fireflymem_org_mid"),
    )


# ============================================================
# 16. 荧光成员 (FluorescentMember)
# ============================================================

class FluorescentMember(Base, IDMixin, TimestampMixin):
    __tablename__ = "fluorescent_members"

    organization_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("organizations.id"), nullable=False, index=True
    )
    member_id: Mapped[int] = mapped_column(BigInteger, nullable=False, index=True)
    account_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("accounts.id"), nullable=True, index=True
    )
    nickname: Mapped[str | None] = mapped_column(String(100), nullable=True)
    fans_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    broker_name: Mapped[str | None] = mapped_column(String(100), nullable=True)
    total_amount: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    org_task_num: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    synced_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    __table_args__ = (
        UniqueConstraint("organization_id", "member_id", name="uq_fluormem_org_mid"),
    )


# ============================================================
# 7. 违规作品 (ViolationPhoto)
# ============================================================

class ViolationPhoto(Base, IDMixin, TimestampMixin):
    __tablename__ = "violation_photos"

    organization_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("organizations.id"), nullable=False, index=True
    )
    account_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("accounts.id"), nullable=True, index=True
    )
    work_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    uid: Mapped[str | None] = mapped_column(String(32), nullable=True, index=True)
    thumbnail: Mapped[str | None] = mapped_column(String(500), nullable=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    business_type: Mapped[str | None] = mapped_column(String(50), nullable=True, index=True)
    # spark / firefly / fluorescent
    violation_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    view_count: Mapped[int] = mapped_column(BigInteger, default=0, nullable=False)
    like_count: Mapped[int] = mapped_column(BigInteger, default=0, nullable=False)
    appeal_status: Mapped[str | None] = mapped_column(String(20), nullable=True, index=True)
    # none / submitted / approved / rejected
    appeal_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    published_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    detected_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    __table_args__ = (
        UniqueConstraint("organization_id", "work_id", name="uq_viol_org_workid"),
    )
