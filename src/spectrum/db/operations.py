"""Database CRUD operations.

Intentionally omits hard-delete (铁律: AI 不直接删除).
Archive operations set status fields instead.
"""

from __future__ import annotations

import logging
from typing import Any, Sequence, TypeVar

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from spectrum.db.engine import get_session_factory
from spectrum.db.models import (
    AgentTask,
    ActivityLog,
    Base,
    Output,
    ResearchProject,
    Source,
    WikiCard,
)

logger = logging.getLogger(__name__)

T = TypeVar("T", bound=Base)


class DatabaseOps:
    """High-level async CRUD for all 6 tables."""

    def _session(self) -> AsyncSession:
        return get_session_factory()()

    # ── Generic helpers ──────────────────────────────────────────────────

    async def _get_by_id(self, model: type[T], id: int) -> T | None:
        async with self._session() as session:
            return await session.get(model, id)

    async def _list(
        self,
        model: type[T],
        filters: dict[str, Any] | None = None,
        order_by: str | None = None,
    ) -> Sequence[T]:
        async with self._session() as session:
            stmt = select(model)
            if filters:
                for key, value in filters.items():
                    stmt = stmt.where(getattr(model, key) == value)
            if order_by:
                col = getattr(model, order_by.lstrip("-"))
                stmt = stmt.order_by(col.desc() if order_by.startswith("-") else col)
            result = await session.execute(stmt)
            return result.scalars().all()

    async def _create(self, instance: T) -> T:
        async with self._session() as session:
            session.add(instance)
            await session.commit()
            await session.refresh(instance)
            return instance

    async def _update(self, model: type[T], id: int, **fields: Any) -> T | None:
        async with self._session() as session:
            obj = await session.get(model, id)
            if obj is None:
                return None
            for key, value in fields.items():
                setattr(obj, key, value)
            await session.commit()
            await session.refresh(obj)
            return obj

    # ── Research Projects ────────────────────────────────────────────────

    async def get_project(self, id: int) -> ResearchProject | None:
        return await self._get_by_id(ResearchProject, id)

    async def list_projects(self, **filters: Any) -> Sequence[ResearchProject]:
        return await self._list(ResearchProject, filters, order_by="-created_at")

    async def create_project(self, **fields: Any) -> ResearchProject:
        project = ResearchProject(**fields)
        return await self._create(project)

    async def update_project(self, id: int, **fields: Any) -> ResearchProject | None:
        return await self._update(ResearchProject, id, **fields)

    # ── Sources ──────────────────────────────────────────────────────────

    async def get_source(self, id: int) -> Source | None:
        return await self._get_by_id(Source, id)

    async def list_sources(self, **filters: Any) -> Sequence[Source]:
        return await self._list(Source, filters, order_by="-created_at")

    async def create_source(self, **fields: Any) -> Source:
        source = Source(**fields)
        return await self._create(source)

    async def update_source(self, id: int, **fields: Any) -> Source | None:
        return await self._update(Source, id, **fields)

    # ── Wiki Cards ───────────────────────────────────────────────────────

    async def get_wiki_card(self, id: int) -> WikiCard | None:
        return await self._get_by_id(WikiCard, id)

    async def list_wiki_cards(self, **filters: Any) -> Sequence[WikiCard]:
        return await self._list(WikiCard, filters, order_by="-created_at")

    async def create_wiki_card(self, **fields: Any) -> WikiCard:
        card = WikiCard(**fields)
        return await self._create(card)

    async def update_wiki_card(self, id: int, **fields: Any) -> WikiCard | None:
        return await self._update(WikiCard, id, **fields)

    # ── Outputs ──────────────────────────────────────────────────────────

    async def get_output(self, id: int) -> Output | None:
        return await self._get_by_id(Output, id)

    async def list_outputs(self, **filters: Any) -> Sequence[Output]:
        return await self._list(Output, filters, order_by="-created_at")

    async def create_output(self, **fields: Any) -> Output:
        output = Output(**fields)
        return await self._create(output)

    async def update_output(self, id: int, **fields: Any) -> Output | None:
        return await self._update(Output, id, **fields)

    # ── Agent Tasks ──────────────────────────────────────────────────────

    async def get_task(self, id: int) -> AgentTask | None:
        return await self._get_by_id(AgentTask, id)

    async def list_tasks(self, **filters: Any) -> Sequence[AgentTask]:
        return await self._list(AgentTask, filters, order_by="-created_at")

    async def create_task(self, **fields: Any) -> AgentTask:
        task = AgentTask(**fields)
        return await self._create(task)

    async def update_task(self, id: int, **fields: Any) -> AgentTask | None:
        return await self._update(AgentTask, id, **fields)

    async def list_tasks_for_agent(self, agent: str, status: str) -> Sequence[AgentTask]:
        """List tasks assigned to a specific agent with given status."""
        async with self._session() as session:
            stmt = (
                select(AgentTask)
                .where(AgentTask.assigned_agent == agent)
                .where(AgentTask.status == status)
                .order_by(AgentTask.created_at)
            )
            result = await session.execute(stmt)
            return result.scalars().all()

    async def resolve_dependencies(self) -> int:
        """Unlock Waiting tasks whose dependencies are all Done. Returns count unlocked."""
        async with self._session() as session:
            # Get all Waiting tasks
            stmt = select(AgentTask).where(AgentTask.status == "Waiting")
            result = await session.execute(stmt)
            waiting = result.scalars().all()

            unlocked = 0
            for task in waiting:
                if not task.depends_on:
                    continue
                dep_ids = [int(d.strip()) for d in task.depends_on.split(",") if d.strip()]
                if not dep_ids:
                    continue

                # Check if all dependencies are Done
                dep_stmt = select(AgentTask).where(AgentTask.id.in_(dep_ids))
                dep_result = await session.execute(dep_stmt)
                deps = dep_result.scalars().all()

                if all(d.status == "Done" for d in deps):
                    task.status = "Todo"
                    unlocked += 1

            if unlocked:
                await session.commit()
            return unlocked

    # ── Activity Log ─────────────────────────────────────────────────────

    async def list_logs(self, **filters: Any) -> Sequence[ActivityLog]:
        return await self._list(ActivityLog, filters, order_by="-created_at")

    async def create_log(self, **fields: Any) -> ActivityLog:
        entry = ActivityLog(**fields)
        return await self._create(entry)
