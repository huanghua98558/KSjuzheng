"""通用 mixin: TimestampMixin / SoftDeleteMixin."""
from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import DateTime, Integer
from sqlalchemy.orm import Mapped, mapped_column


def _now() -> datetime:
    return datetime.now(timezone.utc)


class TimestampMixin:
    """统一 created_at / updated_at."""

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_now, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_now, onupdate=_now, nullable=False
    )


class SoftDeleteMixin:
    """软删除 — deleted_at not null = 已删."""

    deleted_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), default=None, nullable=True
    )

    @property
    def is_deleted(self) -> bool:
        return self.deleted_at is not None


class IDMixin:
    """整数自增主键."""

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
