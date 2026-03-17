"""Async SQLAlchemy engine and session factory."""

from __future__ import annotations

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


async def close_engine() -> None:
    global _engine, _session_factory
    if _engine:
        await _engine.dispose()
        _engine = None
        _session_factory = None
