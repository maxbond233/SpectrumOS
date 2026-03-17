"""🌊 衍射 — Curator / output agent.

Responsibilities:
- Read Wiki cards for a project
- Synthesize structured documents (综述/教程/报告/etc.)
- Create Output records with full content
- Mark as Review Needed for Kuro
"""

from __future__ import annotations

import json
import logging

from spectrum.agents.base import AgentBase
from spectrum.db.models import AgentTask
from spectrum.llm.prompts import DIFFRACTION_SYSTEM

logger = logging.getLogger(__name__)


class DiffractionAgent(AgentBase):
    agent_name = "diffraction"
    agent_label = "🌊 衍射"

    async def process_task(self, task: AgentTask) -> list[str]:
        """Synthesize wiki cards into an output document."""
        events: list[str] = []

        # Get project info
        project = None
        if task.project_ref:
            project = await self.db.get_project(task.project_ref)

        # Gather wiki cards for this project
        cards = []
        if task.project_ref:
            cards = list(await self.db.list_wiki_cards(project_ref=task.project_ref))

        if not cards:
            self.logger.info("No wiki cards found for project %s", task.project_ref)
            await self.db.update_task(task.id, ai_notes="无可用的知识卡片")
            return events

        # Build card context
        card_text = ""
        for c in cards:
            card_text += (
                f"## {c.concept} ({c.type})\n"
                f"定义: {c.definition}\n"
                f"解释: {c.explanation}\n"
                f"要点: {c.key_points}\n"
                f"示例: {c.example}\n\n"
            )

        output_type = project.output_type if project else "综述"
        project_name = project.name if project else task.name

        response = await self.llm.complete(
            agent_name=self.agent_name,
            system=DIFFRACTION_SYSTEM,
            messages=[{"role": "user", "content": (
                f"课题: {project_name}\n"
                f"产出类型: {output_type}\n"
                f"任务指令: {task.message}\n\n"
                f"以下是相关知识卡片：\n\n{card_text}\n"
                "请合成一篇结构化文稿。返回 JSON 对象。"
            )}],
        )

        # Parse output
        output_data = self._parse_output(response.content, task.project_ref, output_type)

        if output_data:
            created = await self.db.create_output(**output_data)
            await self.activity_logger.log(
                actor=self.agent_name,
                action_type="Create",
                target_db="Outputs",
                description=f"产出文稿: {output_data['name']}",
                target_record=str(created.id),
                needs_review=True,
            )
            events.append(f"output_created:{created.id}")

            await self.db.update_task(
                task.id,
                message=f"已产出文稿: {output_data['name']}",
            )

        return events

    def _parse_output(
        self, content: str, project_ref: int | None, output_type: str
    ) -> dict | None:
        """Parse LLM response into an output dict."""
        text = content.strip()
        if "```" in text:
            start = text.find("{")
            end = text.rfind("}") + 1
            if start >= 0 and end > start:
                text = text[start:end]

        try:
            raw = json.loads(text)
        except json.JSONDecodeError:
            self.logger.warning("Failed to parse output from LLM response")
            return None

        word_count = raw.get("word_count", 0)
        body = raw.get("content", "")
        if not word_count and body:
            word_count = len(body)

        return {
            "name": raw.get("title", "未命名文稿"),
            "type": output_type,
            "status": "进行中",
            "project_ref": project_ref,
            "assigned_agent": "diffraction",
            "word_count": word_count,
            "content": body,
            "ai_notes": raw.get("ai_notes", ""),
            "review_needed": True,
        }
