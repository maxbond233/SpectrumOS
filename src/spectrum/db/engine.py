"""Async SQLAlchemy engine and session factory."""

from __future__ import annotations

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from spectrum.config import DatabaseConfig

_engine = None
_session_factory: async_sessionmaker[AsyncSession] | None = None


def init_engine(config: DatabaseConfig) -> None:
    """Initialize the global async engine + session factory."""
    global _engine, _session_factory
    _engine = create_async_engine(config.url, echo=False)
    _session_factory = async_sessionmaker(_engine, expire_on_commit=False)


def get_session_factory() -> async_sessionmaker[AsyncSession]:
    if _session_factory is None:
        raise RuntimeError("Database not initialized — call init_engine() first")
    return _session_factory


def get_engine():
    if _engine is None:
        raise RuntimeError("Database not initialized — call init_engine() first")
    return _engine


async def create_tables() -> None:
    """Create all tables from ORM metadata."""
    from spectrum.db.models import Base

    engine = get_engine()
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    await _migrate_schema()


async def _migrate_schema() -> None:
    """Add columns introduced after initial schema creation."""
    engine = get_engine()
    migrations = [
        # v0.3: Research project fields
        "ALTER TABLE research_projects ADD COLUMN research_brief TEXT DEFAULT ''",
        "ALTER TABLE research_projects ADD COLUMN review_round INTEGER DEFAULT 0",
        "ALTER TABLE research_projects ADD COLUMN completion_review TEXT DEFAULT ''",
        # v0.4: Source URL dedup
        "ALTER TABLE sources ADD COLUMN url_hash TEXT",
    ]
    async with engine.begin() as conn:
        for sql in migrations:
            try:
                await conn.execute(text(sql))
            except Exception:
                pass  # Column already exists

    # v0.4: Knowledge layer tables + indexes (idempotent)
    v04_ddl = [
        # Tags
        "CREATE TABLE IF NOT EXISTS tags (id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT NOT NULL, parent_id INTEGER, level INTEGER DEFAULT 1, description TEXT, created_at TEXT DEFAULT (datetime('now')), updated_at TEXT DEFAULT (datetime('now')))",
        "CREATE UNIQUE INDEX IF NOT EXISTS idx_tags_name_parent ON tags(name, COALESCE(parent_id, -1))",
        # Card-Tag junction
        "CREATE TABLE IF NOT EXISTS card_tags (id INTEGER PRIMARY KEY AUTOINCREMENT, card_id INTEGER NOT NULL, tag_id INTEGER NOT NULL, source TEXT DEFAULT 'ai', created_at TEXT DEFAULT (datetime('now')))",
        "CREATE UNIQUE INDEX IF NOT EXISTS idx_card_tags_unique ON card_tags(card_id, tag_id)",
        "CREATE INDEX IF NOT EXISTS idx_card_tags_tag ON card_tags(tag_id)",
        # Card links
        "CREATE TABLE IF NOT EXISTS card_links (id INTEGER PRIMARY KEY AUTOINCREMENT, from_id INTEGER NOT NULL, to_id INTEGER NOT NULL, relation TEXT DEFAULT '相关', source TEXT DEFAULT 'ai', note TEXT, created_at TEXT DEFAULT (datetime('now')))",
        "CREATE UNIQUE INDEX IF NOT EXISTS idx_card_links_unique ON card_links(from_id, to_id, relation)",
        "CREATE INDEX IF NOT EXISTS idx_card_links_to ON card_links(to_id)",
        # FTS5
        "CREATE VIRTUAL TABLE IF NOT EXISTS fts_index USING fts5(entity_type, entity_id UNINDEXED, title, body, domain, tokenize='unicode61')",
        # Source URL dedup index
        "CREATE INDEX IF NOT EXISTS idx_sources_url_hash ON sources(url_hash)",
    ]
    async with engine.begin() as conn:
        for sql in v04_ddl:
            try:
                await conn.execute(text(sql))
            except Exception:
                pass


async def close_engine() -> None:
    global _engine, _session_factory
    if _engine:
        await _engine.dispose()
        _engine = None
        _session_factory = None
