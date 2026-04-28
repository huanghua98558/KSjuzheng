"""L7 内容资产层 — 短剧池 / 高转化 / 链接统计 / 收藏记录 / 外部 URL.

对应文档: docs/MODULE_SPEC.md §17-§21.
"""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    BigInteger,
    Boolean,
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
from app.models._mixins import IDMixin, SoftDeleteMixin, TimestampMixin


# ============================================================
# 17. 短剧收藏池 (CollectPool)
# ============================================================

class CollectPool(Base, IDMixin, TimestampMixin, SoftDeleteMixin):
    """短剧候选池 — 标题 / URL / 平台 / 授权码 / 状态 / 异常原因."""

    __tablename__ = "collect_pool"

    organization_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("organizations.id"), nullable=False, index=True
    )
    drama_name: Mapped[str] = mapped_column(String(200), nullable=False, index=True)
    drama_url: Mapped[str] = mapped_column(String(1000), nullable=False)
    platform: Mapped[str | None] = mapped_column(String(50), nullable=True, index=True)
    # kuaishou / douyin / chengxing / other
    auth_code: Mapped[str | None] = mapped_column(String(50), nullable=True, index=True)

    status: Mapped[str] = mapped_column(
        String(20), default="active", nullable=False, index=True
    )  # active / abnormal / deleted
    abnormal_reason: Mapped[str | None] = mapped_column(String(100), nullable=True)
    # 例: "url_empty" / "non_kuaishou" / "chinese_in_url" / "404" / "rate_limited"

    imported_by_user_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("users.id"), nullable=True
    )

    # 同一 URL 可在不同 auth_code 下重复出现 (deduplicate-and-copy 场景),
    # 因此 UNIQUE 含 auth_code. App 层另做 (org+url) 防重 (per auth_code).
    __table_args__ = ()


# ============================================================
# 18. 高转化短剧 (HighIncomeDramas)
# ============================================================

class CollectPoolAuthCode(Base, IDMixin, TimestampMixin):
    __tablename__ = "collect_pool_auth_codes"

    auth_code: Mapped[str] = mapped_column(String(100), unique=True, nullable=False, index=True)
    name: Mapped[str | None] = mapped_column(String(100), nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False, index=True)
    expire_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_by_user_id: Mapped[int | None] = mapped_column(
        "created_by", Integer, ForeignKey("users.id"), nullable=True
    )


class HighIncomeDrama(Base, IDMixin, TimestampMixin):
    """收益高的剧 — 来源是 firefly_income / spark_income / fluorescent_income 的"加入"动作."""

    __tablename__ = "high_income_dramas"

    organization_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("organizations.id"), nullable=False, index=True
    )
    drama_name: Mapped[str] = mapped_column(String(200), nullable=False, index=True)
    source_program: Mapped[str | None] = mapped_column(String(20), nullable=True)
    # firefly / spark / fluorescent / manual
    source_income_id: Mapped[int | None] = mapped_column(Integer, nullable=True)

    income_amount: Mapped[float | None] = mapped_column(Float, nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    added_by_user_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("users.id"), nullable=True
    )

    __table_args__ = (
        UniqueConstraint("organization_id", "drama_name", name="uq_hid_org_name"),
    )


class HighIncomeDramaLink(Base, IDMixin, TimestampMixin):
    __tablename__ = "high_income_drama_links"

    organization_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("organizations.id"), nullable=False, index=True
    )
    drama_name: Mapped[str] = mapped_column(String(200), nullable=False, index=True)
    drama_url: Mapped[str] = mapped_column(String(1000), nullable=False)
    source: Mapped[str | None] = mapped_column(String(50), nullable=True, index=True)
    reference_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    account_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    last_seen_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


# ============================================================
# 19. 短剧链接统计 (DramaLinkStatistics)
# ============================================================

class DramaLinkStatistic(Base, IDMixin, TimestampMixin):
    """链接级聚合 — 由 worker 从 account_task_records 聚合, 增量维护."""

    __tablename__ = "drama_link_statistics"

    organization_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("organizations.id"), nullable=False, index=True
    )
    drama_url: Mapped[str] = mapped_column(String(1000), nullable=False)
    drama_name: Mapped[str | None] = mapped_column(String(200), nullable=True)
    task_type: Mapped[str | None] = mapped_column(String(50), nullable=True, index=True)

    execute_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    success_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    failed_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    account_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    last_executed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, index=True
    )

    @property
    def success_rate(self) -> float:
        if self.execute_count == 0:
            return 0.0
        return self.success_count / self.execute_count


# ============================================================
# 20. 短剧收藏记录 (DramaCollectionRecord)
# ============================================================

class DramaCollectionRecord(Base, IDMixin, TimestampMixin):
    """按账号统计 — 用于"账号收藏总数" 页. 由 worker 聚合."""

    __tablename__ = "drama_collection_records"

    organization_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("organizations.id"), nullable=False, index=True
    )
    account_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("accounts.id"), nullable=True, index=True
    )
    account_uid: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    account_name: Mapped[str | None] = mapped_column(String(100), nullable=True)

    total_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    spark_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    firefly_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    fluorescent_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    last_collected_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    __table_args__ = (
        UniqueConstraint("organization_id", "account_uid", name="uq_dcr_org_uid"),
    )


# ============================================================
# 21. 外部 URL 统计 (ExternalUrlStat)
# ============================================================

class SparkPhoto(Base, IDMixin, TimestampMixin):
    __tablename__ = "spark_photos"

    source_id: Mapped[int | None] = mapped_column(BigInteger, unique=True, nullable=True, index=True)
    organization_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("organizations.id"), nullable=True, index=True
    )
    account_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("accounts.id"), nullable=True, index=True
    )
    photo_id: Mapped[str] = mapped_column(String(50), unique=True, nullable=False, index=True)
    member_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True, index=True)
    member_name: Mapped[str | None] = mapped_column(String(100), nullable=True)
    title: Mapped[str | None] = mapped_column(String(500), nullable=True)
    view_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False, index=True)
    like_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    comment_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    duration: Mapped[str | None] = mapped_column(String(20), nullable=True)
    publish_time: Mapped[int | None] = mapped_column(BigInteger, nullable=True, index=True)
    publish_date: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    cover_url: Mapped[str | None] = mapped_column(String(500), nullable=True)
    play_url: Mapped[str | None] = mapped_column(String(500), nullable=True)
    avatar_url: Mapped[str | None] = mapped_column(String(500), nullable=True)


class SparkViolationDrama(Base, IDMixin, TimestampMixin):
    __tablename__ = "spark_violation_dramas"

    source_id: Mapped[int | None] = mapped_column(Integer, unique=True, nullable=True, index=True)
    organization_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("organizations.id"), nullable=False, index=True
    )
    drama_title: Mapped[str] = mapped_column(String(200), nullable=False, index=True)
    source_photo_id: Mapped[str | None] = mapped_column(String(50), nullable=True)
    source_caption: Mapped[str | None] = mapped_column(Text, nullable=True)
    user_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True, index=True)
    username: Mapped[str | None] = mapped_column(String(100), nullable=True)
    violation_count: Mapped[int] = mapped_column(Integer, default=1, nullable=False, index=True)
    last_violation_time: Mapped[int | None] = mapped_column(BigInteger, nullable=True, index=True)
    last_violation_date: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    sub_biz: Mapped[str | None] = mapped_column(String(50), nullable=True)
    status_desc: Mapped[str | None] = mapped_column(String(50), nullable=True)
    reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    media_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    thumb_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    broker_name: Mapped[str | None] = mapped_column(String(100), nullable=True)
    is_blacklisted: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False, index=True)
    blacklisted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class ExternalUrlStat(Base, IDMixin, TimestampMixin):
    __tablename__ = "external_url_stats"

    organization_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("organizations.id"), nullable=True, index=True
    )
    url: Mapped[str] = mapped_column(String(1000), nullable=False)
    source_platform: Mapped[str | None] = mapped_column(String(50), nullable=True)
    # douyin / xigua / wechat / weibo / unknown
    reference_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    last_seen_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
