"""🌈 色散 — Analyst agent.

Responsibilities:
- Read Collected sources for a project
- Extract and distill concepts into Wiki cards
- Update source status to Processed
"""

from __future__ import annotations

import json
import logging
import re

from spectrum.agents._parsing import extract_json_from_llm, normalize_field
from spectrum.agents.base import AgentBase
from spectrum.db.fts import upsert_fts_entry
from spectrum.db.models import AgentTask
from spectrum.llm.prompts import DISPERSION_SYSTEM

logger = logging.getLogger(__name__)


class DispersionAgent(AgentBase):
    agent_name = "dispersion"
    agent_label = "🌈 色散"

    async def process_task(self, task: AgentTask) -> list[str]:
        """Analyze sources → create Wiki cards."""
        events: list[str] = []

        # Gather collected sources for this project
        sources = []
        project = None
        if task.project_ref:
            project = await self.db.get_project(task.project_ref)
            sources = list(await self.db.list_sources(
                project_ref=task.project_ref, status="Collected"
            ))
        project_domain = project.domain if project else ""

        if not sources:
            self.logger.info("No collected sources found for project %s", task.project_ref)
            await self.db.update_task(task.id, ai_notes="无可分析的素材")
            return events

        # Build source context for LLM
        source_text = ""
        for s in sources:
            source_text += (
                f"## {s.title} (ID: {s.id})\n"
                f"类型: {s.source_type}\n"
                f"URL: {s.url}\n"
                f"摘要: {s.extracted_summary}\n"
                f"关键问题: {s.key_questions}\n"
                f"重要性: {s.why_it_matters}\n\n"
            )

        task_context = f"任务: {task.name}\n指令: {task.message}\n"

        # Step 1: Ask LLM to list concepts to extract (lightweight call)
        plan_response = await self.llm.complete(
            agent_name=self.agent_name,
            system="你是知识提炼专家。只输出 JSON，不要输出其他内容。",
            messages=[{"role": "user", "content": (
                f"{task_context}\n"
                f"以下是已采集的素材：\n\n{source_text}\n"
                "请列出应该提炼的核心概念清单。返回 JSON 数组，每项包含：\n"
                '{"concept": "概念名称", "source_ids": [相关素材ID], "type": "概念/方法/工具/理论"}\n'
                "只列出概念清单，不要生成完整卡片。"
            )}],
        )

        try:
            concept_plan = extract_json_from_llm(plan_response.content, expect_type=list)
        except (json.JSONDecodeError, TypeError):
            self.logger.warning("Failed to parse concept plan, falling back to single-pass")
            concept_plan = None

        # Step 2: Generate cards — batch by concepts to avoid truncation
        if concept_plan and len(concept_plan) > 0:
            all_cards_content = await self._batch_generate_cards(
                task_context, source_text, concept_plan
            )
        else:
            # Fallback: single-pass (original behavior)
            response = await self.llm.complete(
                agent_name=self.agent_name,
                system=DISPERSION_SYSTEM,
                messages=[{"role": "user", "content": (
                    f"{task_context}\n"
                    f"以下是已采集的素材：\n\n{source_text}\n"
                    "请从这些素材中提炼核心概念，创建知识卡片。返回 JSON 数组。"
                )}],
            )
            all_cards_content = response.content or ""

        # Parse wiki cards
        cards = self._parse_cards(all_cards_content, task.project_ref, project_domain)

        if not cards:
            await self.db.update_task(
                task.id,
                ai_notes=all_cards_content[:500] if all_cards_content else "",
            )
            raise RuntimeError(
                f"未能从 LLM 响应中解析出任何知识卡片 (响应长度: {len(all_cards_content or '')})"
            )

        created_cards = []  # (card_obj, card_data) pairs
        for card_data in cards:
            # Extract and remove transient fields before DB insert
            tags_raw = card_data.pop("_tags", [])
            links_raw = card_data.pop("_links", [])
            created = await self.db.create_wiki_card(**card_data)
            await self.activity_logger.log(
                actor=self.agent_name,
                action_type="Create",
                target_db="Wiki",
                description=f"提炼概念: {card_data['concept']}",
                target_record=str(created.id),
            )
            events.append(f"wiki_created:{created.id}")
            created_cards.append((created, card_data, tags_raw, links_raw))

            # FTS index
            try:
                body = " ".join(filter(None, [
                    card_data.get("definition", ""),
                    card_data.get("explanation", ""),
                    card_data.get("key_points", ""),
                    card_data.get("example", ""),
                ]))
                await upsert_fts_entry(
                    "wiki_card", created.id, card_data["concept"],
                    body, card_data.get("domain", ""),
                )
            except Exception:
                logger.warning("FTS upsert failed for card %d", created.id)

        # Apply knowledge layer (tags + links)
        await self._apply_knowledge_layer(created_cards)

        # Mark sources as Processed
        for s in sources:
            await self.db.update_source(s.id, status="Processed")
            await self.activity_logger.log(
                actor=self.agent_name,
                action_type="Update",
                target_db="Sources",
                description=f"素材已分析: {s.title}",
                target_record=str(s.id),
                before="Collected",
                after="Processed",
            )

        await self.db.update_task(
            task.id,
            message=f"提炼 {len(cards)} 个概念，处理 {len(sources)} 个素材",
        )

        return events

    async def _apply_knowledge_layer(
        self, created_cards: list[tuple],
    ) -> None:
        """Apply tags and concept links to newly created cards."""
        if not created_cards:
            return

        # Build concept → card_id mapping for link resolution
        concept_to_id: dict[str, int] = {}
        for card, card_data, _, _ in created_cards:
            concept_to_id[card_data["concept"]] = card.id

        # Tag name → tag_id cache to avoid repeated DB lookups
        tag_cache: dict[str, int] = {}

        for card, card_data, tags_raw, links_raw in created_cards:
            # ── Tags ──
            for tag_path in tags_raw:
                try:
                    parts = [p.strip() for p in str(tag_path).split("/") if p.strip()]
                    parts = parts[:3]  # max 3 levels
                    parent_id = None
                    for part in parts:
                        cache_key = f"{parent_id}:{part}"
                        if cache_key in tag_cache:
                            parent_id = tag_cache[cache_key]
                            continue
                        existing = await self.db.find_tag_by_name(part)
                        if existing:
                            tag_cache[cache_key] = existing.id
                            parent_id = existing.id
                        else:
                            new_tag = await self.db.create_tag(
                                name=part, parent_id=parent_id,
                            )
                            tag_cache[cache_key] = new_tag.id
                            parent_id = new_tag.id
                    # Tag the card with the leaf tag
                    if parent_id is not None:
                        await self.db.tag_card(card.id, parent_id, source="ai")
                except Exception:
                    logger.warning("Failed to apply tag '%s' to card %d", tag_path, card.id)

            # ── Links ──
            for link in links_raw:
                try:
                    target = link.get("target", "")
                    relation = link.get("relation", "相关")
                    note = link.get("note", "")
                    target_id = concept_to_id.get(target)
                    if target_id and target_id != card.id:
                        await self.db.create_card_link(
                            from_id=card.id, to_id=target_id,
                            relation=relation, source="ai", note=note,
                        )
                except Exception:
                    logger.warning("Failed to create link from card %d to '%s'", card.id, link.get("target", "?"))

    async def _batch_generate_cards(
        self, task_context: str, source_text: str, concept_plan: list[dict],
    ) -> str:
        """Generate wiki cards one concept at a time to avoid output truncation."""
        merged: list = []

        for i, concept in enumerate(concept_plan):
            concept_name = concept.get("concept", "?")
            concept_type = concept.get("type", "概念")
            source_ids = concept.get("source_ids", [])

            response = await self.llm.complete(
                agent_name=self.agent_name,
                system=DISPERSION_SYSTEM,
                messages=[{"role": "user", "content": (
                    f"{task_context}\n"
                    f"以下是已采集的素材：\n\n{source_text}\n"
                    f"请为以下概念生成 1 张完整的知识卡片（JSON 数组，包含 1 个元素）：\n"
                    f"- {concept_name} (类型: {concept_type}, 相关素材: {source_ids})\n\n"
                    "只生成这一个概念的卡片，不要添加其他概念。"
                )}],
            )

            try:
                parsed = extract_json_from_llm(response.content or "", expect_type=list)
                merged.extend(parsed)
            except (json.JSONDecodeError, TypeError):
                if not merged:
                    return response.content or ""
                self.logger.warning("Failed to parse card for concept '%s', skipping", concept_name)

        if merged:
            return json.dumps(merged, ensure_ascii=False)
        return "[]"

    def _parse_cards(self, content: str, project_ref: int | None, domain: str = "") -> list[dict]:
        """Parse LLM response into wiki card dicts.

        Falls back to text-splitting, then a single card if JSON parsing fails.
        """
        try:
            raw = extract_json_from_llm(content, expect_type=list)
        except (json.JSONDecodeError, TypeError):
            self.logger.warning(
                "Failed to parse wiki cards from LLM response: %s", content[:200]
            )
            # Secondary fallback: split by numbered items or markdown headings
            chunks = re.split(r"\n(?=\d+[\.\)、]|\#{1,3}\s)", content.strip())
            cards: list[dict] = []
            for i, chunk in enumerate(chunks):
                chunk = chunk.strip()
                if len(chunk) < 30:
                    continue
                first_line = chunk.split("\n")[0][:60].strip("# ").strip("0123456789.、) ")
                concept = (
                    first_line
                    if len(first_line) > 5
                    else f"概念 {i + 1} · 课题{project_ref or '?'}"
                )
                cards.append({
                    "concept": concept,
                    "type": "概念",
                    "domain": domain,
                    "definition": chunk[:500],
                    "explanation": chunk[:5000],
                    "key_points": "",
                    "example": "",
                    "maturity": "Seed",
                    "project_ref": project_ref,
                    "assigned_agent": "dispersion",
                })
            if cards:
                return cards
            # Final fallback: single card with content-derived concept name
            if len(content.strip()) > 50:
                self.logger.info("Creating fallback wiki card from raw LLM response")
                return [{
                    "concept": content.strip().split("\n")[0][:60] or "未命名概念",
                    "type": "概念",
                    "domain": domain,
                    "definition": content[:500],
                    "explanation": content[:5000],
                    "key_points": "",
                    "example": "",
                    "maturity": "Seed",
                    "project_ref": project_ref,
                    "assigned_agent": "dispersion",
                }]
            return []

        cards = []
        for r in raw:
            cards.append({
                "concept": r.get("concept", "未命名概念"),
                "type": r.get("type", "概念"),
                "domain": r.get("domain", "") or domain,
                "definition": normalize_field(r.get("definition", "")),
                "explanation": normalize_field(r.get("explanation", "")),
                "key_points": normalize_field(r.get("key_points", "")),
                "example": normalize_field(r.get("example", "")),
                "maturity": "Seed",
                "project_ref": project_ref,
                "assigned_agent": "dispersion",
                "_tags": r.get("tags", []) or [],
                "_links": r.get("links", []) or [],
            })
        return cards
