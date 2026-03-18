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

        response = await self.llm.complete(
            agent_name=self.agent_name,
            system=DISPERSION_SYSTEM,
            messages=[{"role": "user", "content": (
                f"任务: {task.name}\n"
                f"指令: {task.message}\n\n"
                f"以下是已采集的素材：\n\n{source_text}\n"
                "请从这些素材中提炼核心概念，创建知识卡片。返回 JSON 数组。"
            )}],
        )

        # Parse wiki cards
        cards = self._parse_cards(response.content, task.project_ref, project_domain)

        if not cards:
            await self.db.update_task(
                task.id,
                ai_notes=response.content[:500] if response.content else "",
            )
            raise RuntimeError(
                f"未能从 LLM 响应中解析出任何知识卡片 (响应长度: {len(response.content or '')})"
            )

        for card_data in cards:
            created = await self.db.create_wiki_card(**card_data)
            await self.activity_logger.log(
                actor=self.agent_name,
                action_type="Create",
                target_db="Wiki",
                description=f"提炼概念: {card_data['concept']}",
                target_record=str(created.id),
            )
            events.append(f"wiki_created:{created.id}")

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
            })
        return cards
