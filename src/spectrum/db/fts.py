"""FTS5 full-text search — rebuild, upsert, search."""

from __future__ import annotations

import logging
from typing import Optional

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from spectrum.db.engine import get_session_factory
from spectrum.db.models import Output, Source, WikiCard

logger = logging.getLogger(__name__)


async def rebuild_fts_index() -> int:
    """Drop and rebuild full FTS index from all 3 tables. Returns total indexed count."""
    session_factory = get_session_factory()
    total = 0
    async with session_factory() as session:
        # Clear existing index
        await session.execute(text("DELETE FROM fts_index"))

        # Index sources
        from sqlalchemy import select
        sources = (await session.execute(select(Source))).scalars().all()
        for s in sources:
            body = " ".join(filter(None, [s.extracted_summary, s.key_questions, s.why_it_matters]))
            if s.title or body:
                await session.execute(
                    text("INSERT INTO fts_index(entity_type, entity_id, title, body, domain) VALUES (:t, :id, :title, :body, :domain)"),
                    {"t": "source", "id": str(s.id), "title": s.title, "body": body, "domain": s.domain or ""},
                )
                total += 1

        # Index wiki cards
        cards = (await session.execute(select(WikiCard))).scalars().all()
        for c in cards:
            body = " ".join(filter(None, [c.definition, c.explanation, c.key_points, c.example]))
            if c.concept or body:
                await session.execute(
                    text("INSERT INTO fts_index(entity_type, entity_id, title, body, domain) VALUES (:t, :id, :title, :body, :domain)"),
                    {"t": "wiki_card", "id": str(c.id), "title": c.concept, "body": body, "domain": c.domain or ""},
                )
                total += 1

        # Index outputs
        outputs = (await session.execute(select(Output))).scalars().all()
        for o in outputs:
            if o.name or o.content:
                await session.execute(
                    text("INSERT INTO fts_index(entity_type, entity_id, title, body, domain) VALUES (:t, :id, :title, :body, :domain)"),
                    {"t": "output", "id": str(o.id), "title": o.name, "body": o.content or "", "domain": o.domain or ""},
                )
                total += 1

        await session.commit()

    logger.info("FTS index rebuilt: %d entries", total)
    return total


async def upsert_fts_entry(
    entity_type: str, entity_id: int, title: str, body: str, domain: str = "",
) -> None:
    """Insert or replace a single FTS entry."""
    session_factory = get_session_factory()
    async with session_factory() as session:
        # Delete existing entry for this entity
        await session.execute(
            text("DELETE FROM fts_index WHERE entity_type = :t AND entity_id = :id"),
            {"t": entity_type, "id": str(entity_id)},
        )
        # Insert new
        await session.execute(
            text("INSERT INTO fts_index(entity_type, entity_id, title, body, domain) VALUES (:t, :id, :title, :body, :domain)"),
            {"t": entity_type, "id": str(entity_id), "title": title, "body": body, "domain": domain},
        )
        await session.commit()


async def search_fts(
    query: str, entity_type: Optional[str] = None, limit: int = 20,
) -> list[dict]:
    """Search FTS index. Returns list of {entity_type, entity_id, title, snippet, rank}."""
    session_factory = get_session_factory()
    async with session_factory() as session:
        if entity_type:
            sql = text("""
                SELECT entity_type, entity_id, title,
                       snippet(fts_index, 3, '<mark>', '</mark>', '...', 32) as snippet,
                       rank
                FROM fts_index
                WHERE fts_index MATCH :query AND entity_type = :etype
                ORDER BY rank
                LIMIT :limit
            """)
            result = await session.execute(sql, {"query": query, "etype": entity_type, "limit": limit})
        else:
            sql = text("""
                SELECT entity_type, entity_id, title,
                       snippet(fts_index, 3, '<mark>', '</mark>', '...', 32) as snippet,
                       rank
                FROM fts_index
                WHERE fts_index MATCH :query
                ORDER BY rank
                LIMIT :limit
            """)
            result = await session.execute(sql, {"query": query, "limit": limit})

        return [
            {
                "entity_type": row[0],
                "entity_id": int(row[1]),
                "title": row[2],
                "snippet": row[3],
                "rank": row[4],
            }
            for row in result.fetchall()
        ]


async def fts_is_empty() -> bool:
    """Check if the FTS index has any entries."""
    session_factory = get_session_factory()
    async with session_factory() as session:
        result = await session.execute(text("SELECT COUNT(*) FROM fts_index"))
        count = result.scalar_one()
        return count == 0
