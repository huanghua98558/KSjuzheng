"""Schemas for Chengxing/CXT external project data."""
from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class CxtUserPublic(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    organization_id: int
    platform_uid: str
    username: str | None = None
    auth_code: str | None = None
    note: str | None = None
    status: str
    created_at: datetime
    updated_at: datetime


class CxtUserImportItem(BaseModel):
    platform_uid: str = Field(..., min_length=1, max_length=64)
    username: str | None = Field(None, max_length=100)
    auth_code: str | None = Field(None, max_length=50)
    note: str | None = Field(None, max_length=200)
    status: str = "active"


class CxtUserImportRequest(BaseModel):
    items: list[CxtUserImportItem] = Field(..., min_length=1, max_length=10000)


class CxtVideoPublic(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    organization_id: int
    cxt_user_id: int | None = None
    title: str | None = None
    author: str | None = None
    sec_user_id: str | None = None
    aweme_id: str | None = None
    description: str | None = None
    video_url: str | None = None
    cover_url: str | None = None
    duration: int | None = None
    comment_count: int = 0
    collect_count: int = 0
    recommend_count: int = 0
    share_count: int = 0
    play_count: int = 0
    digg_count: int = 0
    platform: str = "unknown"
    status: str = "active"
    created_at: datetime
    updated_at: datetime


class CxtVideoImportItem(BaseModel):
    title: str | None = Field(None, max_length=500)
    author: str | None = Field(None, max_length=100)
    sec_user_id: str | None = Field(None, max_length=200)
    aweme_id: str | None = Field(None, max_length=100)
    description: str | None = None
    video_url: str | None = None
    cover_url: str | None = None
    duration: int | None = None
    comment_count: int = 0
    collect_count: int = 0
    recommend_count: int = 0
    share_count: int = 0
    play_count: int = 0
    digg_count: int = 0
    platform: str = "unknown"
    status: str = "active"


class CxtVideoImportRequest(BaseModel):
    items: list[CxtVideoImportItem] = Field(..., min_length=1, max_length=10000)
