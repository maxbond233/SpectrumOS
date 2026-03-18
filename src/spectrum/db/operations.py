"""Database CRUD operations.

Intentionally omits hard-delete (铁律: AI 不直接删除).
Archive operations set status fields instead.
Junction table deletes (card_tags) are allowed — they remove associations, not data.
"""

from __future__ import annotations

import hashlib
import logging
from typing import Any, Sequence, TypeVar

from sqlalchemy import delete, func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from spectrum.db.engine import get_session_factory
from spectrum.db.models import (
    AgentTask,
    ActivityLog,
    Base,
    CardLink,
    CardTag,
    Output,
    ResearchProject,
    Source,
    Tag,
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
            _filters = dict(filters) if filters else {}
            limit = _filters.pop("_limit", None)
            offset = _filters.pop("_offset", None)

            stmt = select(model)
            for key, value in _filters.items():
                stmt = stmt.where(getattr(model, key) == value)
            if order_by:
                col = getattr(model, order_by.lstrip("-"))
                stmt = stmt.order_by(col.desc() if order_by.startswith("-") else col)
            if offset:
                stmt = stmt.offset(offset)
            if limit:
                stmt = stmt.limit(limit)
            result = await session.execute(stmt)
            return result.scalars().all()

    async def _count(self, model: type[T], filters: dict[str, Any] | None = None) -> int:
        async with self._session() as session:
            stmt = select(func.count(model.id))
            if filters:
                for key, value in filters.items():
                    stmt = stmt.where(getattr(model, key) == value)
            result = await session.execute(stmt)
            return result.scalar_one()

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
        # Auto-compute url_hash for dedup
        url = fields.get("url", "")
        if url and "url_hash" not in fields:
            fields["url_hash"] = hashlib.sha256(url.strip().lower().encode()).hexdigest()[:16]
        source = Source(**fields)
        return await self._create(source)

    async def find_source_by_url(self, url: str) -> Source | None:
        """Find existing source by URL hash."""
        url_hash = hashlib.sha256(url.strip().lower().encode()).hexdigest()[:16]
        async with self._session() as session:
            stmt = select(Source).where(Source.url_hash == url_hash).limit(1)
            result = await session.execute(stmt)
            return result.scalars().first()

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
        """List tasks assigned to a specific agent with given status, ordered by project priority."""
        async with self._session() as session:
            stmt = (
                select(AgentTask)
                .outerjoin(ResearchProject, AgentTask.project_ref == ResearchProject.id)
                .where(AgentTask.assigned_agent == agent)
                .where(AgentTask.status == status)
                .order_by(
                    # P1 > P2 > P3, NULLs last
                    text("""CASE
                        WHEN research_projects.priority = 'P1' THEN 1
                        WHEN research_projects.priority = 'P2' THEN 2
                        WHEN research_projects.priority = 'P3' THEN 3
                        ELSE 4
                    END"""),
                    AgentTask.created_at.asc(),
                )
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

    # ── Tags ──────────────────────────────────────────────────────────────

    async def create_tag(
        self, name: str, parent_id: int | None = None, description: str | None = None,
    ) -> Tag:
        """Create a tag. Auto-computes level from parent."""
        level = 1
        if parent_id is not None:
            parent = await self._get_by_id(Tag, parent_id)
            if parent:
                level = parent.level + 1
        tag = Tag(name=name, parent_id=parent_id, level=level, description=description)
        return await self._create(tag)

    async def get_tag(self, id: int) -> Tag | None:
        return await self._get_by_id(Tag, id)

    async def update_tag(self, id: int, **fields: Any) -> Tag | None:
        return await self._update(Tag, id, **fields)

    async def list_tags(self, parent_id: int | None = None) -> Sequence[Tag]:
        """List tags. If parent_id is None, returns root tags only."""
        async with self._session() as session:
            if parent_id is None:
                stmt = select(Tag).where(Tag.parent_id.is_(None)).order_by(Tag.name)
            else:
                stmt = select(Tag).where(Tag.parent_id == parent_id).order_by(Tag.name)
            result = await session.execute(stmt)
            return result.scalars().all()

    async def list_all_tags(self) -> Sequence[Tag]:
        """List all tags regardless of parent."""
        return await self._list(Tag, order_by="name")

    async def get_tag_tree(self, root_id: int | None = None) -> list[dict]:
        """Build nested tag tree via recursive CTE."""
        async with self._session() as session:
            if root_id is None:
                roots = (await session.execute(
                    select(Tag).where(Tag.parent_id.is_(None)).order_by(Tag.name)
                )).scalars().all()
            else:
                root = await session.get(Tag, root_id)
                roots = [root] if root else []

            all_tags = (await session.execute(select(Tag).order_by(Tag.name))).scalars().all()
            children_map: dict[int, list[Tag]] = {}
            for t in all_tags:
                if t.parent_id is not None:
                    children_map.setdefault(t.parent_id, []).append(t)

            def _build(tag: Tag) -> dict:
                node = {"id": tag.id, "name": tag.name, "level": tag.level}
                kids = children_map.get(tag.id, [])
                if kids:
                    node["children"] = [_build(c) for c in kids]
                return node

            return [_build(r) for r in roots]

    async def get_tag_descendants(self, tag_id: int) -> list[int]:
        """Recursive CTE returning all descendant tag IDs (inclusive)."""
        async with self._session() as session:
            cte_sql = text("""
                WITH RECURSIVE subtree AS (
                    SELECT id FROM tags WHERE id = :tag_id
                    UNION ALL
                    SELECT t.id FROM tags t JOIN subtree s ON t.parent_id = s.id
                )
                SELECT id FROM subtree
            """)
            result = await session.execute(cte_sql, {"tag_id": tag_id})
            return [row[0] for row in result.fetchall()]

    # ── Card Tags ─────────────────────────────────────────────────────────

    async def tag_card(self, card_id: int, tag_id: int, source: str = "ai") -> CardTag | None:
        """Add tag to card. Returns None if already exists."""
        async with self._session() as session:
            # Check for existing
            stmt = select(CardTag).where(CardTag.card_id == card_id, CardTag.tag_id == tag_id)
            existing = (await session.execute(stmt)).scalars().first()
            if existing:
                return existing
            ct = CardTag(card_id=card_id, tag_id=tag_id, source=source)
            session.add(ct)
            await session.commit()
            await session.refresh(ct)
            return ct

    async def untag_card(self, card_id: int, tag_id: int) -> bool:
        """Remove tag from card. Junction delete, not data delete."""
        async with self._session() as session:
            stmt = delete(CardTag).where(CardTag.card_id == card_id, CardTag.tag_id == tag_id)
            result = await session.execute(stmt)
            await session.commit()
            return result.rowcount > 0

    async def get_card_tags(self, card_id: int) -> Sequence[Tag]:
        """Get all tags for a card."""
        async with self._session() as session:
            stmt = (
                select(Tag)
                .join(CardTag, CardTag.tag_id == Tag.id)
                .where(CardTag.card_id == card_id)
                .order_by(Tag.name)
            )
            result = await session.execute(stmt)
            return result.scalars().all()

    async def get_cards_by_tag(
        self, tag_id: int, include_descendants: bool = True, limit: int = 20, offset: int = 0,
    ) -> tuple[Sequence[WikiCard], int]:
        """Get cards with a given tag. If include_descendants, includes subtag cards."""
        if include_descendants:
            tag_ids = await self.get_tag_descendants(tag_id)
        else:
            tag_ids = [tag_id]

        async with self._session() as session:
            base = (
                select(WikiCard)
                .join(CardTag, CardTag.card_id == WikiCard.id)
                .where(CardTag.tag_id.in_(tag_ids))
                .distinct()
            )
            count_stmt = select(func.count()).select_from(base.subquery())
            total = (await session.execute(count_stmt)).scalar_one()

            stmt = base.order_by(WikiCard.created_at.desc()).offset(offset).limit(limit)
            result = await session.execute(stmt)
            return result.scalars().all(), total

    # ── Card Links ────────────────────────────────────────────────────────

    async def create_card_link(
        self,
        from_id: int,
        to_id: int,
        relation: str = "相关",
        source: str = "ai",
        note: str | None = None,
    ) -> CardLink | None:
        """Create a concept link. If relation is '相关', auto-create reverse link."""
        async with self._session() as session:
            # Check for existing
            stmt = select(CardLink).where(
                CardLink.from_id == from_id, CardLink.to_id == to_id, CardLink.relation == relation,
            )
            existing = (await session.execute(stmt)).scalars().first()
            if existing:
                return existing

            link = CardLink(from_id=from_id, to_id=to_id, relation=relation, source=source, note=note)
            session.add(link)

            # Auto-create reverse for symmetric relations
            if relation == "相关":
                rev_stmt = select(CardLink).where(
                    CardLink.from_id == to_id, CardLink.to_id == from_id, CardLink.relation == relation,
                )
                rev_existing = (await session.execute(rev_stmt)).scalars().first()
                if not rev_existing:
                    reverse = CardLink(from_id=to_id, to_id=from_id, relation=relation, source=source, note=note)
                    session.add(reverse)

            await session.commit()
            await session.refresh(link)
            return link

    async def get_card_links(self, card_id: int) -> dict:
        """Get all links for a card. Returns {'outgoing': [...], 'incoming': [...]}."""
        async with self._session() as session:
            # Outgoing
            out_stmt = (
                select(CardLink, WikiCard.concept)
                .join(WikiCard, WikiCard.id == CardLink.to_id)
                .where(CardLink.from_id == card_id)
            )
            out_result = await session.execute(out_stmt)
            outgoing = [
                {"to_id": link.to_id, "concept": concept, "relation": link.relation, "note": link.note}
                for link, concept in out_result.all()
            ]

            # Incoming
            in_stmt = (
                select(CardLink, WikiCard.concept)
                .join(WikiCard, WikiCard.id == CardLink.from_id)
                .where(CardLink.to_id == card_id)
            )
            in_result = await session.execute(in_stmt)
            incoming = [
                {"from_id": link.from_id, "concept": concept, "relation": link.relation, "note": link.note}
                for link, concept in in_result.all()
            ]

            return {"outgoing": outgoing, "incoming": incoming}

    async def get_link_graph(self, card_id: int, depth: int = 1) -> dict:
        """BFS from card_id up to `depth` hops. Returns {nodes, edges}."""
        visited: set[int] = set()
        edges: list[dict] = []
        queue = [card_id]

        async with self._session() as session:
            for _ in range(depth):
                next_queue: list[int] = []
                for cid in queue:
                    if cid in visited:
                        continue
                    visited.add(cid)
                    stmt = select(CardLink).where(
                        (CardLink.from_id == cid) | (CardLink.to_id == cid)
                    )
                    result = await session.execute(stmt)
                    for link in result.scalars().all():
                        edges.append({
                            "from": link.from_id, "to": link.to_id, "relation": link.relation,
                        })
                        neighbor = link.to_id if link.from_id == cid else link.from_id
                        if neighbor not in visited:
                            next_queue.append(neighbor)
                queue = next_queue

            # Collect all node IDs
            all_ids = visited | {e["from"] for e in edges} | {e["to"] for e in edges}
            nodes = []
            for nid in all_ids:
                card = await session.get(WikiCard, nid)
                if card:
                    nodes.append({"id": card.id, "concept": card.concept})

            # Deduplicate edges
            seen_edges: set[tuple] = set()
            unique_edges = []
            for e in edges:
                key = (e["from"], e["to"], e["relation"])
                if key not in seen_edges:
                    seen_edges.add(key)
                    unique_edges.append(e)

            return {"nodes": nodes, "edges": unique_edges}
