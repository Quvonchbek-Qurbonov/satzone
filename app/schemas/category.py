from __future__ import annotations

import uuid

from app.schemas.base import ORMModel


class CategoryRead(ORMModel):
    id: uuid.UUID
    slug: str
    name: str
    description: str | None = None
    icon_url: str | None = None
    parent_id: uuid.UUID | None = None
    sort_order: int = 0


class CategoryTreeNode(CategoryRead):
    children: list["CategoryTreeNode"] = []


CategoryTreeNode.model_rebuild()
