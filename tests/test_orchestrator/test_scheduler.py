"""Tests for the orchestrator scheduler."""

from __future__ import annotations

import pytest
from unittest.mock import AsyncMock

from spectrum.db.operations import DatabaseOps
from spectrum.orchestrator.event_bus import EventBus
from spectrum.orchestrator.scheduler import Scheduler


async def test_scheduler_resolves_deps_on_tick(db: DatabaseOps):
    """Scheduler tick should unlock waiting tasks."""
    t1 = await db.create_task(name="A", status="Done", assigned_agent="focus")
    t2 = await db.create_task(
        name="B", status="Waiting", assigned_agent="dispersion",
        depends_on=str(t1.id),
    )

    bus = EventBus()
    scheduler = Scheduler(agents={}, db=db, event_bus=bus, tick_interval=1)
    await scheduler._tick()

    refreshed = await db.get_task(t2.id)
    assert refreshed.status == "Todo"


async def test_event_bus():
    bus = EventBus()
    received = []

    async def listener(event, data):
        received.append(event)

    bus.on("task_done", listener)
    await bus.emit("task_done:42")
    assert len(received) == 1
    assert received[0] == "task_done:42"

    # Non-matching event
    await bus.emit("project_started:1")
    assert len(received) == 1
