"""Scheduler — polling loop that drives the agent tick cycle."""

from __future__ import annotations

import asyncio
import logging

from spectrum.agents.base import AgentBase
from spectrum.db.operations import DatabaseOps
from spectrum.orchestrator.event_bus import EventBus

logger = logging.getLogger(__name__)

MAX_RETRIES = 3


class Scheduler:
    """Runs the main tick loop: resolve deps → run agents → emit events."""

    def __init__(
        self,
        agents: dict[str, AgentBase],
        db: DatabaseOps,
        event_bus: EventBus,
        tick_interval: int = 30,
        max_concurrent: int = 3,
    ) -> None:
        self._agents = agents
        self._db = db
        self._event_bus = event_bus
        self._tick_interval = tick_interval
        self._semaphore = asyncio.Semaphore(max_concurrent)
        self._running = False

    async def start(self) -> None:
        """Start the scheduler loop."""
        self._running = True
        logger.info(
            "Scheduler started — tick=%ds, agents=%s",
            self._tick_interval,
            list(self._agents.keys()),
        )

        while self._running:
            try:
                await self._tick()
            except Exception:
                logger.exception("Scheduler tick error")
            await asyncio.sleep(self._tick_interval)

    async def stop(self) -> None:
        self._running = False
        logger.info("Scheduler stopped")

    async def _tick(self) -> None:
        """Single tick cycle."""
        # 1. Resolve dependencies: Waiting → Todo
        unlocked = await self._db.resolve_dependencies()
        if unlocked:
            logger.info("Unlocked %d waiting tasks", unlocked)

        # 2. Retry failed tasks that haven't exceeded max retries
        retried = await self._retry_failed_tasks()
        if retried:
            logger.info("Retried %d failed tasks", retried)

        # 3. Run all enabled agents concurrently (bounded by semaphore)
        async def run_agent(name: str, agent: AgentBase) -> list[str]:
            async with self._semaphore:
                try:
                    return await agent.tick()
                except Exception:
                    logger.exception("Agent %s tick failed", name)
                    return []

        tasks = [
            asyncio.create_task(run_agent(name, agent))
            for name, agent in self._agents.items()
        ]
        results = await asyncio.gather(*tasks)

        # 3. Emit all events
        all_events = [e for events in results for e in events]
        if all_events:
            logger.info("Tick produced %d events: %s", len(all_events), all_events)
            await self._event_bus.emit_many(all_events)

    async def trigger_agent(self, agent_name: str) -> list[str]:
        """Manually trigger a single agent's tick (for API/CLI use)."""
        agent = self._agents.get(agent_name)
        if not agent:
            raise ValueError(f"Unknown agent: {agent_name}")
        events = await agent.tick()
        await self._event_bus.emit_many(events)
        return events

    async def _retry_failed_tasks(self) -> int:
        """Re-queue Waiting tasks that failed but haven't exceeded MAX_RETRIES.

        Tasks that have exhausted retries (review_needed=True) are marked Failed.
        Tasks waiting on dependencies are left alone.
        """
        waiting_tasks = await self._db.list_tasks(status="Waiting")
        retried = 0
        for task in waiting_tasks:
            # Skip tasks waiting on dependencies
            if task.depends_on:
                continue
            # Exhausted retries → mark as Failed
            if task.review_needed or (task.retry_count or 0) >= MAX_RETRIES:
                await self._db.update_task(task.id, status="Failed")
                logger.warning(
                    "Task %s (%s) marked Failed after %d retries",
                    task.id, task.name, task.retry_count or 0,
                )
                continue
            if (task.retry_count or 0) < MAX_RETRIES:
                await self._db.update_task(task.id, status="Todo")
                logger.info(
                    "Re-queued task %s (%s) for retry #%d",
                    task.id, task.name, (task.retry_count or 0) + 1,
                )
                retried += 1
        return retried
