"""Server-side search and pagination shared by every list endpoint."""

from math import ceil
from typing import Generic, TypeVar

from fastapi import Query
from pydantic import BaseModel
from sqlalchemy import ColumnElement, Select, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

T = TypeVar("T")

MAX_PAGE_SIZE = 100


class Page(BaseModel, Generic[T]):
    items: list[T]
    total: int
    page: int
    page_size: int
    pages: int


class PageParams:
    """Query parameters every list endpoint accepts: ?page=1&page_size=20&q=text"""

    def __init__(
        self,
        page: int = Query(1, ge=1),
        page_size: int = Query(20, ge=1, le=MAX_PAGE_SIZE),
        q: str = Query("", max_length=100, description="Search text"),
    ):
        self.page = page
        self.page_size = page_size
        self.q = q.strip()


def contains(q: str, *columns) -> ColumnElement[bool]:
    """Case-insensitive 'contains' over several columns. % and _ in the search text match literally."""
    escaped = q.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    pattern = f"%{escaped}%"
    return or_(*(column.ilike(pattern, escape="\\") for column in columns))


async def paginate(session: AsyncSession, query: Select, params: PageParams) -> dict:
    """Run `query` for one page and count the full result. The query must already be ordered."""
    total = await session.scalar(select(func.count()).select_from(query.order_by(None).subquery())) or 0
    rows = await session.scalars(query.limit(params.page_size).offset((params.page - 1) * params.page_size))
    return {
        "items": list(rows),
        "total": total,
        "page": params.page,
        "page_size": params.page_size,
        "pages": max(ceil(total / params.page_size), 1),
    }
