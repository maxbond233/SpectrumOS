"""Tests for tag CRUD operations."""

from __future__ import annotations

import pytest
from spectrum.db.operations import DatabaseOps


async def test_create_root_tag(db: DatabaseOps):
    tag = await db.create_tag(name="机器学习")
    assert tag.id is not None
    assert tag.name == "机器学习"
    assert tag.level == 1
    assert tag.parent_id is None


async def test_create_child_tag(db: DatabaseOps):
    root = await db.create_tag(name="机器学习")
    child = await db.create_tag(name="深度学习", parent_id=root.id)
    assert child.level == 2
    assert child.parent_id == root.id


async def test_create_grandchild_tag(db: DatabaseOps):
    root = await db.create_tag(name="机器学习")
    child = await db.create_tag(name="深度学习", parent_id=root.id)
    grandchild = await db.create_tag(name="Transformer", parent_id=child.id)
    assert grandchild.level == 3
    assert grandchild.parent_id == child.id


async def test_list_root_tags(db: DatabaseOps):
    await db.create_tag(name="A")
    await db.create_tag(name="B")
    child_parent = await db.create_tag(name="C")
    await db.create_tag(name="C1", parent_id=child_parent.id)

    roots = await db.list_tags()
    assert len(roots) == 3
    assert all(t.parent_id is None for t in roots)


async def test_list_child_tags(db: DatabaseOps):
    root = await db.create_tag(name="ML")
    await db.create_tag(name="DL", parent_id=root.id)
    await db.create_tag(name="RL", parent_id=root.id)

    children = await db.list_tags(parent_id=root.id)
    assert len(children) == 2


async def test_get_tag_tree(db: DatabaseOps):
    root = await db.create_tag(name="ML")
    child = await db.create_tag(name="DL", parent_id=root.id)
    await db.create_tag(name="CNN", parent_id=child.id)

    tree = await db.get_tag_tree()
    assert len(tree) == 1
    assert tree[0]["name"] == "ML"
    assert len(tree[0]["children"]) == 1
    assert tree[0]["children"][0]["name"] == "DL"
    assert len(tree[0]["children"][0]["children"]) == 1
    assert tree[0]["children"][0]["children"][0]["name"] == "CNN"


async def test_get_tag_descendants(db: DatabaseOps):
    root = await db.create_tag(name="ML")
    child1 = await db.create_tag(name="DL", parent_id=root.id)
    child2 = await db.create_tag(name="RL", parent_id=root.id)
    grandchild = await db.create_tag(name="CNN", parent_id=child1.id)

    descendants = await db.get_tag_descendants(root.id)
    assert set(descendants) == {root.id, child1.id, child2.id, grandchild.id}


async def test_update_tag(db: DatabaseOps):
    tag = await db.create_tag(name="Old Name")
    updated = await db.update_tag(tag.id, name="New Name", description="desc")
    assert updated.name == "New Name"
    assert updated.description == "desc"
