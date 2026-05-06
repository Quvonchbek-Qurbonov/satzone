from __future__ import annotations

from collections import defaultdict

from fastapi import APIRouter

from app.db.deps import DbSession
from app.schemas.category import CategoryRead, CategoryTreeNode
from app.services import course_service

router = APIRouter(prefix="/categories", tags=["categories"])


@router.get("", response_model=list[CategoryRead])
async def list_categories(session: DbSession) -> list[CategoryRead]:
    cats = await course_service.list_categories(session)
    return [CategoryRead.model_validate(c) for c in cats]


@router.get("/tree", response_model=list[CategoryTreeNode])
async def category_tree(session: DbSession) -> list[CategoryTreeNode]:
    cats = await course_service.list_categories(session)
    by_parent: dict[object, list] = defaultdict(list)
    nodes: dict[object, CategoryTreeNode] = {
        c.id: CategoryTreeNode.model_validate(c) for c in cats
    }
    for c in cats:
        by_parent[c.parent_id].append(c.id)
    for parent_id, child_ids in by_parent.items():
        if parent_id is None:
            continue
        parent_node = nodes.get(parent_id)
        if parent_node is None:
            continue
        parent_node.children = [nodes[cid] for cid in child_ids]
    return [nodes[cid] for cid in by_parent.get(None, [])]
