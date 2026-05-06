from __future__ import annotations

from typing import Annotated, Generic, TypeVar

from fastapi import Query
from pydantic import BaseModel, Field
from sqlalchemy import Select, func, select
from sqlalchemy.ext.asyncio import AsyncSession

T = TypeVar("T")


class PageParams(BaseModel):
    page: int = Field(default=1, ge=1)
    size: int = Field(default=20, ge=1, le=100)

    @property
    def offset(self) -> int:
        return (self.page - 1) * self.size

    @property
    def limit(self) -> int:
        return self.size


def page_params(
    page: Annotated[int, Query(ge=1)] = 1,
    size: Annotated[int, Query(ge=1, le=100)] = 20,
) -> PageParams:
    return PageParams(page=page, size=size)


class Page(BaseModel, Generic[T]):
    items: list[T]
    total: int
    page: int
    size: int
    pages: int


async def paginate(
    session: AsyncSession,
    stmt: Select,
    params: PageParams,
) -> tuple[list, int]:
    count_stmt = select(func.count()).select_from(stmt.order_by(None).subquery())
    total = (await session.execute(count_stmt)).scalar_one()
    result = await session.execute(stmt.limit(params.limit).offset(params.offset))
    items = list(result.scalars().all())
    return items, int(total)


def to_page(items: list[T], total: int, params: PageParams) -> Page[T]:
    pages = (total + params.size - 1) // params.size if total else 0
    return Page[T](items=items, total=total, page=params.page, size=params.size, pages=pages)