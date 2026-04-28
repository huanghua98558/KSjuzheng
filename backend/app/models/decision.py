"""L9 AI 决策层 — 候选池 / 匹配评分 / 爆款 / 账号分层迁移.

来源: docs/服务器后端完整蓝图_含AI自动化v1.md §3.3.
对齐 ks_automation/CLAUDE.md §31 candidate_builder.
"""
from __future__ import annotations

from datetime import date, datetime

from sqlalchemy import (
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
# 每日候选池 (5 层漏斗 + 6 维评分产物)
# ============================================================

class DailyCandidatePool(Base, IDMixin, TimestampMixin):
    __tablename__ = "daily_candidate_pool"

    pool_date: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    organization_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("organizations.id"), nullable=False, index=True
    )
    drama_name: Mapped[str] = mapped_column(String(200), nullable=False, index=True)
    banner_task_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    biz_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    commission_rate: Mapped[float | None] = mapped_column(Float, nullable=True)

    freshness_tier: Mapped[str | None] = mapped_column(
        String(20), nullable=True
    )  # today / within_48h / legacy
    w24h_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    w48h_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    cdn_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    pool_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    income_numeric: Mapped[float | None] = mapped_column(Float, nullable=True)
    violation_status: Mapped[str | None] = mapped_column(String(20), nullable=True)
    # none / flagged / restricted

    score_freshness: Mapped[float] = mapped_column(Float, default=0.0)
    score_url_ready: Mapped[float] = mapped_column(Float, default=0.0)
    score_commission: Mapped[float] = mapped_column(Float, default=0.0)
    score_heat: Mapped[float] = mapped_column(Float, default=0.0)
    score_matrix: Mapped[float] = mapped_column(Float, default=0.0)
    score_penalty: Mapped[float] = mapped_column(Float, default=0.0)
    composite_score: Mapped[float] = mapped_column(Float, default=0.0, index=True)

    status: Mapped[str] = mapped_column(
        String(20), default="pending", nullable=False, index=True
    )  # pending / assigned / finished
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    __table_args__ = (
        UniqueConstraint(
            "pool_date", "drama_name", "organization_id",
            name="uq_dcp_date_drama_org",
        ),
    )


# ============================================================
# 匹配评分历史 (账号 × 剧 × 时间)
# ============================================================

class MatchScoreHistory(Base, IDMixin, TimestampMixin):
    __tablename__ = "match_score_history"

    organization_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("organizations.id"), nullable=False, index=True
    )
    account_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("accounts.id"), nullable=False, index=True
    )
    drama_name: Mapped[str] = mapped_column(String(200), nullable=False, index=True)
    score_total: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    breakdown_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    computed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )


# ============================================================
# 爆款检测
# ============================================================

class BurstDetection(Base, IDMixin, TimestampMixin):
    __tablename__ = "burst_detections"

    organization_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("organizations.id"), nullable=False, index=True
    )
    drama_name: Mapped[str] = mapped_column(String(200), nullable=False, index=True)
    views_24h: Mapped[int] = mapped_column(Integer, default=0)
    growth_pct: Mapped[float] = mapped_column(Float, default=0.0)
    income_24h: Mapped[float] = mapped_column(Float, default=0.0)
    competition_score: Mapped[float] = mapped_column(Float, default=0.0)
    recommended_accounts: Mapped[str | None] = mapped_column(Text, nullable=True)
    # JSON array
    detected_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    acted_upon: Mapped[bool] = mapped_column(Boolean, default=False)


# ============================================================
# 账号分层迁移
# ============================================================

class AccountTierTransition(Base, IDMixin, TimestampMixin):
    __tablename__ = "account_tier_transitions"

    account_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("accounts.id"), nullable=False, index=True
    )
    organization_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("organizations.id"), nullable=False, index=True
    )
    old_tier: Mapped[str | None] = mapped_column(String(20), nullable=True)
    new_tier: Mapped[str] = mapped_column(String(20), nullable=False)
    reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    triggered_by: Mapped[str | None] = mapped_column(String(20), nullable=True)
    # auto / manual / watchdog
    transitioned_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )


# ============================================================
# 每日 plan items + 任务 (复用 KS184 \u4e2d\u95f4\u8868)
# ============================================================

class DailyPlan(Base, IDMixin, TimestampMixin):
    __tablename__ = "daily_plans"

    organization_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("organizations.id"), nullable=False, index=True
    )
    plan_date: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    total_items: Mapped[int] = mapped_column(Integer, default=0)
    finished_items: Mapped[int] = mapped_column(Integer, default=0)
    status: Mapped[str] = mapped_column(String(20), default="active")
    # active / completed / cancelled


class DailyPlanItem(Base, IDMixin, TimestampMixin):
    __tablename__ = "daily_plan_items"

    plan_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("daily_plans.id"), nullable=False, index=True
    )
    organization_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("organizations.id"), nullable=False, index=True
    )
    account_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("accounts.id"), nullable=False, index=True
    )
    drama_name: Mapped[str] = mapped_column(String(200), nullable=False)

    recipe: Mapped[str | None] = mapped_column(String(50), nullable=True)
    image_mode: Mapped[str | None] = mapped_column(String(50), nullable=True)
    recipe_config_json: Mapped[str | None] = mapped_column(Text, nullable=True)

    sched_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, index=True
    )
    priority: Mapped[int] = mapped_column(Integer, default=50, index=True)
    status: Mapped[str] = mapped_column(
        String(20), default="pending", nullable=False, index=True
    )  # pending / queued / running / finished / failed / blacklisted / account_frozen
    reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    experiment_group: Mapped[str | None] = mapped_column(String(20), nullable=True)
    # A / B / C
    task_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
