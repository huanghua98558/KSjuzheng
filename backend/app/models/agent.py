"""L10 Agent 自动化层.

ks_automation/core/agents/* 9 个 agent 的元数据 + 运行历史.
"""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base
from app.models._mixins import IDMixin, TimestampMixin


# ============================================================
# Agent 运行 (一个 agent 跑一次记一条)
# ============================================================

class AgentRun(Base, IDMixin, TimestampMixin):
    __tablename__ = "agent_runs"

    run_id: Mapped[str] = mapped_column(String(36), unique=True, nullable=False, index=True)
    # uuid hex
    agent_name: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    organization_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("organizations.id"), nullable=True, index=True
    )

    trigger_type: Mapped[str] = mapped_column(String(20), default="schedule", nullable=False)
    # schedule / manual / replay
    triggered_by_user_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("users.id"), nullable=True
    )

    started_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    finished_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    duration_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)

    status: Mapped[str] = mapped_column(
        String(20), default="running", nullable=False, index=True
    )  # running / success / failed / canceled

    input_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    output_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)

    cycle_id: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)


# ============================================================
# AutoPilot 主循环 cycle
# ============================================================

class AutopilotCycle(Base, IDMixin, TimestampMixin):
    __tablename__ = "autopilot_cycles"

    cycle_id: Mapped[int] = mapped_column(Integer, unique=True, nullable=False, index=True)
    organization_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("organizations.id"), nullable=True, index=True
    )

    started_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    finished_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    duration_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)

    status: Mapped[str] = mapped_column(
        String(20), default="ok", nullable=False, index=True
    )  # ok / degraded / error / stuck_reset

    steps_executed: Mapped[int] = mapped_column(Integer, default=0)
    steps_skipped: Mapped[int] = mapped_column(Integer, default=0)
    errors_json: Mapped[str | None] = mapped_column(Text, nullable=True)


# ============================================================
# AutoPilot 诊断流 (摘要级)
# ============================================================

class AutopilotDiagnosis(Base, IDMixin, TimestampMixin):
    __tablename__ = "autopilot_diagnoses"

    organization_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("organizations.id"), nullable=True, index=True
    )

    diagnosis_type: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    # account_issue / drama_issue / system_issue
    severity: Mapped[str] = mapped_column(String(20), default="medium", index=True)
    # low / medium / high / critical

    summary: Mapped[str] = mapped_column(Text, nullable=False)
    affected_object: Mapped[str | None] = mapped_column(String(100), nullable=True)

    detected_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    resolved_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    auto_resolved: Mapped[bool] = mapped_column(Boolean, default=False)

    confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    playbook_code: Mapped[str | None] = mapped_column(String(100), nullable=True, index=True)


# ============================================================
# AutoPilot 自动动作
# ============================================================

class AutopilotAction(Base, IDMixin, TimestampMixin):
    __tablename__ = "autopilot_actions"

    organization_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("organizations.id"), nullable=True, index=True
    )
    action_type: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    # relogin / throttle / freeze / retry / cookie_refresh ...
    target_type: Mapped[str | None] = mapped_column(String(50), nullable=True)
    target_id: Mapped[str | None] = mapped_column(String(100), nullable=True)

    triggered_by_diagnosis_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("autopilot_diagnoses.id"), nullable=True
    )
    result: Mapped[str | None] = mapped_column(String(20), nullable=True)
    executed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )


# ============================================================
# 报告 (LLM 日报 / 周报)
# ============================================================

class AutopilotReport(Base, IDMixin, TimestampMixin):
    __tablename__ = "autopilot_reports"

    organization_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("organizations.id"), nullable=True, index=True
    )
    period: Mapped[str] = mapped_column(String(20), default="daily")
    start_date: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    end_date: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    summary_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    stats_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    generated_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
