"""通用 schema: 分页 / 列表查询基础参数."""
from __future__ import annotations

from typing import Generic, TypeVar

from pydantic import BaseModel, ConfigDict, Field


T = TypeVar("T")


class Pagination(BaseModel):
    page: int
    size: int
    total: int
    total_pages: int
    has_next: bool


class PageQuery(BaseModel):
    """通用 ?page= &size= &sort= 查询参数."""

    page: int = Field(1, ge=1)
    size: int = Field(20, ge=1, le=200)
    sort: str | None = None
    keyword: str | None = None


class PageResult(BaseModel, Generic[T]):
    items: list[T]
    pagination: Pagination


def make_pagination(total: int, page: int, size: int) -> Pagination:
    total_pages = (total + size - 1) // size if size > 0 else 0
    return Pagination(
        page=page,
        size=size,
        total=total,
        total_pages=total_pages,
        has_next=page < total_pages,
    )


class IdListRequest(BaseModel):
    """通用批量 ID 列表."""

    ids: list[int] = Field(..., min_length=1, max_length=500)


class BatchResult(BaseModel):
    """批量操作结果."""

    success_count: int
    failed_count: int
    failed_ids: list[int] = Field(default_factory=list)
    message: str | None = None
