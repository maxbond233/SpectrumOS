"""Tests for card-tag junction operations."""

from __future__ import annotations

import pytest
from spectrum.db.operations import DatabaseOps


async def _make_card(db: DatabaseOps, concept: str = "TestConcept") -> int:
    card = await db.create_wiki_card(concept=concept, type="概念", domain="测试")
    return card.id


async def test_tag_card(db: DatabaseOps):
    card_id = await _make_card(db)
    tag = await db.create_tag(name="ML")
    ct = await db.tag_card(card_id, tag.id)
    assert ct is not None
    assert ct.card_id == card_id
    assert ct.tag_id == tag.id


async def test_duplicate_tag_idempotent(db: DatabaseOps):
    card_id = await _make_card(db)
    tag = await db.create_tag(name="ML")
    ct1 = await db.tag_card(card_id, tag.id)
    ct2 = await db.tag_card(card_id, tag.id)
    # Should return existing, not create duplicate
    assert ct1.id == ct2.id


async def test_get_card_tags(db: DatabaseOps):
    card_id = await _make_card(db)
    t1 = await db.create_tag(name="A")
    t2 = await db.create_tag(name="B")
    await db.tag_card(card_id, t1.id)
    await db.tag_card(card_id, t2.id)

    tags = await db.get_card_tags(card_id)
    assert len(tags) == 2
    names = {t.name for t in tags}
    assert names == {"A", "B"}


async def test_untag_card(db: DatabaseOps):
    card_id = await _make_card(db)
    tag = await db.create_tag(name="ML")
    await db.tag_card(card_id, tag.id)

    removed = await db.untag_card(card_id, tag.id)
    assert removed is True

    tags = await db.get_card_tags(card_id)
    assert len(tags) == 0

    # Card and tag still exist
    assert await db.get_wiki_card(card_id) is not None
    assert await db.get_tag(tag.id) is not None


async def test_untag_nonexistent(db: DatabaseOps):
    removed = await db.untag_card(999, 999)
    assert removed is False


async def test_get_cards_by_tag_with_descendants(db: DatabaseOps):
    root = await db.create_tag(name="ML")
    child = await db.create_tag(name="DL", parent_id=root.id)

    card1_id = await _make_card(db, "Card1")
    card2_id = await _make_card(db, "Card2")
    await db.tag_card(card1_id, root.id)
    await db.tag_card(card2_id, child.id)

    # With descendants: should find both
    cards, total = await db.get_cards_by_tag(root.id, include_descendants=True)
    assert total == 2

    # Without descendants: only root-tagged card
    cards, total = await db.get_cards_by_tag(root.id, include_descendants=False)
    assert total == 1
