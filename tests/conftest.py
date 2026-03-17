"""Shared test fixtures."""

from __future__ import annotations

import pytest
from spectrum.config import DatabaseConfig
from spectrum.db.engine import init_engine, create_tables, close_engine, get_session_factory
from spectrum.db.operations import DatabaseOps


@pytest.fixture(autouse=True)
async def db():
    """Provide a fresh in-memory SQLite database for each test."""
    init_engine(DatabaseConfig(url="sqlite+aiosqlite:///:memory:"))
    await create_tables()
    ops = DatabaseOps()
    yield ops
    await close_engine()
