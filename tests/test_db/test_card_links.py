"""Tests for card link operations."""

from __future__ import annotations

import pytest
from spectrum.db.operations import DatabaseOps


async def _make_card(db: DatabaseOps, concept: str) -> int:
    card = await db.create_wiki_card(concept=concept, type="概念", domain="测试")
    return card.id


async def test_create_symmetric_link(db: DatabaseOps):
    a = await _make_card(db, "A")
    b = await _make_card(db, "B")

    link = await db.create_card_link(a, b, relation="相关")
    assert link is not None

    # Reverse link should be auto-created
    links = await db.get_card_links(b)
    assert len(links["outgoing"]) == 1
    assert links["outgoing"][0]["to_id"] == a


async def test_create_directional_link(db: DatabaseOps):
    a = await _make_card(db, "A")
    b = await _make_card(db, "B")

    await db.create_card_link(a, b, relation="前置")

    # No reverse link for directional relations
    links_b = await db.get_card_links(b)
    assert len(links_b["outgoing"]) == 0
    assert len(links_b["incoming"]) == 1
    assert links_b["incoming"][0]["relation"] == "前置"


async def test_duplicate_link_idempotent(db: DatabaseOps):
    a = await _make_card(db, "A")
    b = await _make_card(db, "B")

    link1 = await db.create_card_link(a, b, relation="演进")
    link2 = await db.create_card_link(a, b, relation="演进")
    assert link1.id == link2.id


async def test_get_card_links(db: DatabaseOps):
    a = await _make_card(db, "A")
    b = await _make_card(db, "B")
    c = await _make_card(db, "C")

    await db.create_card_link(a, b, relation="前置")
    await db.create_card_link(c, a, relation="对比")

    links = await db.get_card_links(a)
    assert len(links["outgoing"]) == 1
    assert links["outgoing"][0]["to_id"] == b
    assert len(links["incoming"]) == 1
    assert links["incoming"][0]["from_id"] == c


async def test_link_graph_depth(db: DatabaseOps):
    a = await _make_card(db, "A")
    b = await _make_card(db, "B")
    c = await _make_card(db, "C")

    await db.create_card_link(a, b, relation="前置")
    await db.create_card_link(b, c, relation="前置")

    # Depth 1: should see A and B only
    graph = await db.get_link_graph(a, depth=1)
    node_ids = {n["id"] for n in graph["nodes"]}
    assert a in node_ids
    assert b in node_ids

    # Depth 2: should see A, B, and C
    graph2 = await db.get_link_graph(a, depth=2)
    node_ids2 = {n["id"] for n in graph2["nodes"]}
    assert {a, b, c} == node_ids2
