"""Tests for FTS5 full-text search."""

from __future__ import annotations

import pytest
from spectrum.db.operations import DatabaseOps
from spectrum.db.fts import rebuild_fts_index, upsert_fts_entry, search_fts, fts_is_empty


async def test_fts_initially_empty(db: DatabaseOps):
    assert await fts_is_empty() is True


async def test_index_and_search(db: DatabaseOps):
    # Create test data
    await db.create_source(title="Attention Is All You Need", extracted_summary="Transformer architecture paper")
    await db.create_wiki_card(concept="Transformer", definition="A neural network architecture based on self-attention")
    await db.create_output(name="Transformer综述", content="Transformer is a revolutionary architecture")

    count = await rebuild_fts_index()
    assert count == 3

    results = await search_fts("Transformer")
    assert len(results) >= 2  # card + output at minimum
    assert all("entity_type" in r for r in results)


async def test_search_type_filter(db: DatabaseOps):
    await db.create_source(title="Paper A", extracted_summary="attention mechanism")
    await db.create_wiki_card(concept="Attention", definition="attention mechanism in neural networks")

    await rebuild_fts_index()

    # Filter by type
    results = await search_fts("attention", entity_type="wiki_card")
    assert all(r["entity_type"] == "wiki_card" for r in results)
    assert len(results) >= 1


async def test_upsert_updates_existing(db: DatabaseOps):
    card = await db.create_wiki_card(concept="VAE", definition="Variational Autoencoder")
    await upsert_fts_entry("wiki_card", card.id, "VAE", "Variational Autoencoder")

    results1 = await search_fts("Variational")
    assert len(results1) == 1

    # Update the entry
    await upsert_fts_entry("wiki_card", card.id, "VAE", "Updated definition of VAE")

    results2 = await search_fts("Updated")
    assert len(results2) == 1
    assert results2[0]["entity_id"] == card.id

    # Old content should not match
    results3 = await search_fts("Variational")
    assert len(results3) == 0


async def test_rebuild_clears_and_reindexes(db: DatabaseOps):
    await db.create_wiki_card(concept="Test", definition="test content")
    count1 = await rebuild_fts_index()
    assert count1 == 1

    # Add more data and rebuild
    await db.create_wiki_card(concept="Test2", definition="more content")
    count2 = await rebuild_fts_index()
    assert count2 == 2

    assert await fts_is_empty() is False
