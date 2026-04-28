"""L11 AI 记忆层 — 三层记忆 + Bandit 奖励矩阵.

Layer 1: account_decision_history   事件级 append-only
Layer 2: account_strategy_memory    聚合级, 每账号 1 行
Layer 3: account_diary_entries      文本级, LLM 周记
+ strategy_rewards                  Bandit Thompson Sampling
+ research_notes                    LLM 研究产出 (审批后入库)
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
# Layer 1: 决策历史
# ============================================================

class AccountDecisionHistory(Base, IDMixin, TimestampMixin):
    __tablename__ = "account_decision_history"

    account_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("accounts.id"), nullable=False, index=True
    )
    organization_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("organizations.id"), nullable=False, index=True
    )
    plan_item_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    task_id: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)

    drama_name: Mapped[str] = mapped_column(String(200), nullable=False)
    recipe: Mapped[str | None] = mapped_column(String(50), nullable=True)
    image_mode: Mapped[str | None] = mapped_column(String(50), nullable=True)

    hypothesis: Mapped[str | None] = mapped_column(Text, nullable=True)
    expected_income: Mapped[float | None] = mapped_column(Float, nullable=True)
    expected_views: Mapped[int | None] = mapped_column(Integer, nullable=True)
    confidence: Mapped[float | None] = mapped_column(Float, nullable=True)

    # 实际结果 (analyzer 回填)
    actual_income: Mapped[float | None] = mapped_column(Float, nullable=True)
    actual_views: Mapped[int | None] = mapped_column(Integer, nullable=True)
    verdict: Mapped[str | None] = mapped_column(String(20), nullable=True, index=True)
    # correct / over_optimistic / under_confident / wrong / pending

    decided_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    verdicted_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    reason: Mapped[str | None] = mapped_column(Text, nullable=True)


# ============================================================
# Layer 2: 策略记忆 (聚合, 每账号 1 行)
# ============================================================

class AccountStrategyMemory(Base, IDMixin, TimestampMixin):
    __tablename__ = "account_strategy_memory"

    account_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("accounts.id"), unique=True, nullable=False, index=True
    )
    organization_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("organizations.id"), nullable=False, index=True
    )

    total_decisions: Mapped[int] = mapped_column(Integer, default=0)
    correct_count: Mapped[int] = mapped_column(Integer, default=0)
    over_optimistic_count: Mapped[int] = mapped_column(Integer, default=0)
    wrong_count: Mapped[int] = mapped_column(Integer, default=0)

    ai_trust_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    # correct / total, ≥ 5 \u6837\u672c\u624d\u7ed9

    income_7d: Mapped[float] = mapped_column(Float, default=0.0)
    income_30d: Mapped[float] = mapped_column(Float, default=0.0)

    preferred_recipes: Mapped[str | None] = mapped_column(Text, nullable=True)
    # JSON {recipe: hit_rate}
    preferred_image_modes: Mapped[str | None] = mapped_column(Text, nullable=True)
    avoid_drama_ids: Mapped[str | None] = mapped_column(Text, nullable=True)
    # JSON array
    avoid_recipes: Mapped[str | None] = mapped_column(Text, nullable=True)

    last_aggregated_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )


# ============================================================
# Layer 3: 周记
# ============================================================

class AccountDiaryEntry(Base, IDMixin, TimestampMixin):
    __tablename__ = "account_diary_entries"

    account_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("accounts.id"), nullable=False, index=True
    )
    organization_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("organizations.id"), nullable=False, index=True
    )
    week_start: Mapped[date | None] = mapped_column(Date, nullable=True)
    week_end: Mapped[date | None] = mapped_column(Date, nullable=True)

    summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    performance_review: Mapped[str | None] = mapped_column(Text, nullable=True)
    lessons_learned: Mapped[str | None] = mapped_column(Text, nullable=True)
    next_week_strategy: Mapped[str | None] = mapped_column(Text, nullable=True)
    raw_llm_output: Mapped[str | None] = mapped_column(Text, nullable=True)

    approved: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    approved_by_user_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("users.id"), nullable=True
    )
    approved_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    generated_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )


# ============================================================
# Bandit 奖励矩阵
# ============================================================

class StrategyReward(Base, IDMixin, TimestampMixin):
    __tablename__ = "strategy_rewards"

    organization_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("organizations.id"), nullable=False, index=True
    )
    account_tier: Mapped[str] = mapped_column(String(20), nullable=False, index=True)
    recipe: Mapped[str] = mapped_column(String(50), nullable=False)
    image_mode: Mapped[str | None] = mapped_column(String(50), nullable=True)

    total_trials: Mapped[int] = mapped_column(Integer, default=0)
    total_reward: Mapped[float] = mapped_column(Float, default=0.0)
    avg_reward: Mapped[float | None] = mapped_column(Float, nullable=True)

    last_updated: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    __table_args__ = (
        UniqueConstraint(
            "organization_id", "account_tier", "recipe", "image_mode",
            name="uq_reward_unique",
        ),
    )


# ============================================================
# LLM 研究笔记
# ============================================================

class ResearchNote(Base, IDMixin, TimestampMixin):
    __tablename__ = "research_notes"

    organization_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("organizations.id"), nullable=True, index=True
    )
    note_key: Mapped[str | None] = mapped_column(String(100), unique=True, nullable=True, index=True)
    # e.g. '2026-04-22_§27_A'
    topic: Mapped[str] = mapped_column(String(100), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    approved: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    approved_by_user_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("users.id"), nullable=True
    )
    source: Mapped[str | None] = mapped_column(String(50), nullable=True)
    # llm / human / scrape
