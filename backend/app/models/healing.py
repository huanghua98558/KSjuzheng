"""L12 风控自愈层 — playbook + diagnoses + proposals."""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
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
from app.models._mixins import IDMixin, TimestampMixin


# ============================================================
# Playbook 规则
# ============================================================

class HealingPlaybook(Base, IDMixin, TimestampMixin):
    __tablename__ = "healing_playbook"

    code: Mapped[str] = mapped_column(String(100), unique=True, nullable=False, index=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)

    symptom_pattern: Mapped[str] = mapped_column(Text, nullable=False)
    # regex 或描述
    remedy_action: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    # COOKIE_REFRESH / FREEZE_ACCOUNT / COOLDOWN_DRAMA / ENQUEUE_FREEZE_ACCOUNT ...
    params_json: Mapped[str | None] = mapped_column(Text, nullable=True)

    confidence: Mapped[float] = mapped_column(Float, default=0.5)
    success_count: Mapped[int] = mapped_column(Integer, default=0)
    fail_count: Mapped[int] = mapped_column(Integer, default=0)

    enabled: Mapped[bool] = mapped_column(Boolean, default=True, index=True)
    proposed_by: Mapped[str | None] = mapped_column(String(50), nullable=True)
    # 'seed' / 'llm' / 'manual'
    last_triggered_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    llm_analyzed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )


# ============================================================
# 诊断
# ============================================================

class HealingDiagnosis(Base, IDMixin, TimestampMixin):
    __tablename__ = "healing_diagnoses"

    organization_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("organizations.id"), nullable=True, index=True
    )
    playbook_code: Mapped[str | None] = mapped_column(
        String(100), ForeignKey("healing_playbook.code"), nullable=True, index=True
    )
    severity: Mapped[str] = mapped_column(String(20), default="medium", index=True)
    summary: Mapped[str] = mapped_column(Text, nullable=False)
    detail_json: Mapped[str | None] = mapped_column(Text, nullable=True)

    target_type: Mapped[str | None] = mapped_column(String(50), nullable=True)
    target_id: Mapped[str | None] = mapped_column(String(100), nullable=True)

    auto_resolved: Mapped[bool] = mapped_column(Boolean, default=False)
    resolved_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    detected_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )


# ============================================================
# LLM 提议: 新规则
# ============================================================

class RuleProposal(Base, IDMixin, TimestampMixin):
    __tablename__ = "rule_proposals"

    organization_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("organizations.id"), nullable=True, index=True
    )

    proposed_code: Mapped[str] = mapped_column(String(100), nullable=False)
    symptom_pattern: Mapped[str] = mapped_column(Text, nullable=False)
    remedy_action: Mapped[str] = mapped_column(String(50), nullable=False)
    params_json: Mapped[str | None] = mapped_column(Text, nullable=True)

    rationale: Mapped[str | None] = mapped_column(Text, nullable=True)
    sample_count: Mapped[int] = mapped_column(Integer, default=0)
    llm_confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    target_playbook_id: Mapped[int | None] = mapped_column(Integer, nullable=True)

    status: Mapped[str] = mapped_column(
        String(20), default="pending", index=True
    )  # pending / approved / rejected / applied
    decided_by_user_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("users.id"), nullable=True
    )
    decided_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    applied_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )


# ============================================================
# LLM 提议: 升级现有规则
# ============================================================

class UpgradeProposal(Base, IDMixin, TimestampMixin):
    __tablename__ = "upgrade_proposals"

    target_playbook_code: Mapped[str] = mapped_column(
        String(100), ForeignKey("healing_playbook.code"), nullable=False, index=True
    )
    suggestion_type: Mapped[str] = mapped_column(String(50), nullable=False)
    # refine_pattern / change_action / adjust_params / deprecate
    suggested_pattern: Mapped[str | None] = mapped_column(Text, nullable=True)
    suggested_action: Mapped[str | None] = mapped_column(String(50), nullable=True)
    suggested_params_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    rationale: Mapped[str | None] = mapped_column(Text, nullable=True)
    llm_confidence: Mapped[float | None] = mapped_column(Float, nullable=True)

    status: Mapped[str] = mapped_column(
        String(20), default="pending", index=True
    )
    decided_by_user_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("users.id"), nullable=True
    )
    decided_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
