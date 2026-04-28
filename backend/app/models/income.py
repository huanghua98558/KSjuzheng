"""L6 收益结算层 — 萤光 / 星火 / 荧光收益 + 归档 + 结算 + 钱包.

对应 MODULE_SPEC §10-§16 + §9 钱包.
KS184 表: spark_income / firefly_income / fluorescent_income /
income_archives / settlement_records / wallet_profiles.
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
# 通用收益记录 (KS184 income_records 通配字段)
# ============================================================

class IncomeRecord(Base, IDMixin, TimestampMixin):
    """跨 program 的统一明细 — 多数情况下走专表 (Spark/Firefly/Fluorescent),
    本表保留兼容 KS184 现网."""

    __tablename__ = "income_records"

    organization_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("organizations.id"), nullable=False, index=True
    )
    program_type: Mapped[str] = mapped_column(
        String(20), nullable=False, index=True
    )  # spark / firefly / fluorescent
    member_id: Mapped[int] = mapped_column(BigInteger, nullable=False, index=True)
    account_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("accounts.id"), nullable=True, index=True
    )

    task_id: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    task_name: Mapped[str | None] = mapped_column(String(200), nullable=True)

    gross_amount: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    commission_rate: Mapped[float | None] = mapped_column(Float, nullable=True)
    commission_amount: Mapped[float | None] = mapped_column(Float, nullable=True)

    income_date: Mapped[date | None] = mapped_column(Date, nullable=True, index=True)


# ============================================================
# 萤光收益明细
# ============================================================

class FireflyIncome(Base, IDMixin, TimestampMixin):
    __tablename__ = "firefly_income"

    organization_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("organizations.id"), nullable=False, index=True
    )
    member_id: Mapped[int] = mapped_column(BigInteger, nullable=False, index=True)
    account_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("accounts.id"), nullable=True, index=True
    )

    task_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    task_name: Mapped[str | None] = mapped_column(String(200), nullable=True)

    income_amount: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    commission_rate: Mapped[float | None] = mapped_column(Float, nullable=True)
    commission_amount: Mapped[float | None] = mapped_column(Float, nullable=True)

    income_date: Mapped[date | None] = mapped_column(Date, nullable=True, index=True)
    settlement_status: Mapped[str] = mapped_column(
        String(20), default="pending", nullable=False, index=True
    )  # pending / settled / partial
    archived_year_month: Mapped[str | None] = mapped_column(String(7), nullable=True, index=True)
    # '2026-04'


# ============================================================
# 星火收益明细
# ============================================================

class SparkIncome(Base, IDMixin, TimestampMixin):
    __tablename__ = "spark_income"

    organization_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("organizations.id"), nullable=False, index=True
    )
    member_id: Mapped[int] = mapped_column(BigInteger, nullable=False, index=True)
    account_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("accounts.id"), nullable=True, index=True
    )

    task_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    task_name: Mapped[str | None] = mapped_column(String(200), nullable=True)

    income_amount: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    commission_rate: Mapped[float | None] = mapped_column(Float, nullable=True)
    commission_amount: Mapped[float | None] = mapped_column(Float, nullable=True)

    start_date: Mapped[date | None] = mapped_column(Date, nullable=True, index=True)
    end_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    settlement_status: Mapped[str] = mapped_column(
        String(20), default="pending", nullable=False, index=True
    )
    archived_year_month: Mapped[str | None] = mapped_column(String(7), nullable=True, index=True)


# ============================================================
# 荧光收益明细 (流水, 不归档)
# ============================================================

class FluorescentIncome(Base, IDMixin, TimestampMixin):
    __tablename__ = "fluorescent_income"

    organization_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("organizations.id"), nullable=False, index=True
    )
    member_id: Mapped[int] = mapped_column(BigInteger, nullable=False, index=True)
    account_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("accounts.id"), nullable=True, index=True
    )

    task_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    task_name: Mapped[str | None] = mapped_column(String(200), nullable=True)

    income_amount: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    total_amount: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    org_task_num: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    income_date: Mapped[date | None] = mapped_column(Date, nullable=True, index=True)


# ============================================================
# 归档 (年/月聚合)
# ============================================================

class IncomeArchive(Base, IDMixin, TimestampMixin):
    __tablename__ = "income_archives"

    organization_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("organizations.id"), nullable=False, index=True
    )
    program_type: Mapped[str] = mapped_column(
        String(20), nullable=False, index=True
    )  # spark / firefly / fluorescent
    year: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    month: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    member_id: Mapped[int] = mapped_column(BigInteger, nullable=False, index=True)
    account_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("accounts.id"), nullable=True, index=True
    )

    total_amount: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    commission_rate: Mapped[float | None] = mapped_column(Float, nullable=True)
    commission_amount: Mapped[float | None] = mapped_column(Float, nullable=True)

    settlement_status: Mapped[str] = mapped_column(
        String(20), default="pending", nullable=False, index=True
    )  # pending / settled
    archived_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    __table_args__ = (
        UniqueConstraint(
            "organization_id", "program_type", "year", "month", "member_id",
            name="uq_archive_unique",
        ),
    )


# ============================================================
# 结算记录
# ============================================================

class SettlementRecord(Base, IDMixin, TimestampMixin):
    __tablename__ = "settlement_records"

    archive_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("income_archives.id"), nullable=False, index=True
    )
    settled_by_user_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("users.id"), nullable=True
    )
    settled_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    status: Mapped[str] = mapped_column(String(20), default="settled", nullable=False)
    remark: Mapped[str | None] = mapped_column(Text, nullable=True)


# ============================================================
# 钱包
# ============================================================

class WalletProfile(Base, IDMixin, TimestampMixin):
    """支付宝结算资料. 一个 user 一条 (user_id 唯一)."""

    __tablename__ = "wallet_profiles"

    user_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("users.id"), unique=True, nullable=False, index=True
    )
    alipay_name: Mapped[str | None] = mapped_column(String(100), nullable=True)
    alipay_account: Mapped[str | None] = mapped_column(String(100), nullable=True)
    bank_name: Mapped[str | None] = mapped_column(String(100), nullable=True)
    bank_account: Mapped[str | None] = mapped_column(String(100), nullable=True)
    real_name: Mapped[str | None] = mapped_column(String(100), nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
