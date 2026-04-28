"""Chengxing/CXT external project models."""
from __future__ import annotations

from sqlalchemy import BigInteger, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base
from app.models._mixins import IDMixin, TimestampMixin


class CxtUser(Base, IDMixin, TimestampMixin):
    __tablename__ = "cxt_users"

    organization_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("organizations.id"), nullable=False, index=True
    )
    platform_uid: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    username: Mapped[str | None] = mapped_column(String(100), nullable=True)
    auth_code: Mapped[str | None] = mapped_column(String(50), nullable=True, index=True)
    note: Mapped[str | None] = mapped_column(String(200), nullable=True)
    status: Mapped[str] = mapped_column(String(20), default="active", nullable=False, index=True)

    __table_args__ = (
        UniqueConstraint("organization_id", "platform_uid", name="uq_cxt_user_org_uid"),
    )


class CxtVideo(Base, IDMixin, TimestampMixin):
    __tablename__ = "cxt_videos"

    organization_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("organizations.id"), nullable=False, index=True
    )
    cxt_user_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("cxt_users.id"), nullable=True, index=True
    )

    title: Mapped[str | None] = mapped_column(String(500), nullable=True, index=True)
    author: Mapped[str | None] = mapped_column(String(100), nullable=True, index=True)
    sec_user_id: Mapped[str | None] = mapped_column(String(200), nullable=True, index=True)
    aweme_id: Mapped[str | None] = mapped_column(String(100), nullable=True, index=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    video_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    cover_url: Mapped[str | None] = mapped_column(Text, nullable=True)

    duration: Mapped[int | None] = mapped_column(Integer, nullable=True)
    comment_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    collect_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    recommend_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    share_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    play_count: Mapped[int] = mapped_column(BigInteger, default=0, nullable=False)
    digg_count: Mapped[int] = mapped_column(BigInteger, default=0, nullable=False)

    platform: Mapped[str] = mapped_column(String(20), default="unknown", nullable=False, index=True)
    status: Mapped[str] = mapped_column(String(20), default="active", nullable=False, index=True)

    __table_args__ = (
        UniqueConstraint("platform", "aweme_id", name="uq_cxt_video_platform_aweme"),
    )
