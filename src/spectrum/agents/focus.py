"""💠 聚光 — Collector agent.

Responsibilities:
- Search the web for materials related to a research project
- Fetch and extract content from URLs
- Create Source records with summaries
"""

from __future__ import annotations

import json
import logging

from spectrum.agents.base import AgentBase
from spectrum.db.models import AgentTask
from spectrum.llm.prompts import FOCUS_SYSTEM
from spectrum.tools.web_search import WebSearchTool

logger = logging.getLogger(__name__)


class FocusAgent(AgentBase):
    agent_name = "focus"
    agent_label = "💠 聚光"

    def __init__(self, *args, search_tool: WebSearchTool, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self.search_tool = search_tool

    async def process_task(self, task: AgentTask) -> list[str]:
        """Collect materials: search web → extract → create Sources."""
        events: list[str] = []

        # Build context from task
        project = None
        if task.project_ref:
            project = await self.db.get_project(task.project_ref)

        context = f"任务: {task.name}\n指令: {task.message}\n"
        if project:
            context += (
                f"课题: {project.name}\n"
                f"领域: {project.domain}\n"
                f"研究问题: {project.research_questions}\n"
            )

        # Use LLM with search tools to find and analyze materials
        async def tool_executor(name: str, args: dict) -> str:
            return await self.search_tool.execute_tool(name, args)

        response = await self.llm.complete_with_tools(
            agent_name=self.agent_name,
            system=FOCUS_SYSTEM,
            messages=[{"role": "user", "content": (
                f"{context}\n"
                "请搜索相关资料，采集 3-8 个高质量素材。\n"
                "使用 web_search 工具搜索，使用 fetch_page 工具获取页面内容。\n"
                "最后返回 JSON 数组格式的素材列表。"
            )}],
            tools=self.search_tool.as_llm_tools(),
            tool_executor=tool_executor,
        )

        # Parse sources from LLM response
        sources = self._parse_sources(response.content, task.project_ref)

        for source_data in sources:
            created = await self.db.create_source(**source_data)
            await self.activity_logger.log(
                actor=self.agent_name,
                action_type="Create",
                target_db="Sources",
                description=f"采集素材: {source_data['title']}",
                target_record=str(created.id),
            )
            events.append(f"source_created:{created.id}")

        # Update task with collection summary
        await self.db.update_task(
            task.id,
            message=f"已采集 {len(sources)} 个素材",
            ai_notes=response.content[:500] if response.content else "",
        )

        return events

    def _parse_sources(self, content: str, project_ref: int | None) -> list[dict]:
        """Parse LLM response into source dicts."""
        text = content.strip()
        if "```" in text:
            start = text.find("[")
            end = text.rfind("]") + 1
            if start >= 0 and end > start:
                text = text[start:end]

        try:
            raw = json.loads(text)
        except json.JSONDecodeError:
            self.logger.warning("Failed to parse source list from LLM response")
            return []

        sources = []
        for r in raw:
            sources.append({
                "title": r.get("title", "未命名素材"),
                "source_type": r.get("source_type", ""),
                "status": "Collected",
                "url": r.get("url", ""),
                "authors": r.get("authors", ""),
                "extracted_summary": r.get("extracted_summary", ""),
                "key_questions": r.get("key_questions", ""),
                "why_it_matters": r.get("why_it_matters", ""),
                "project_ref": project_ref,
                "assigned_agent": "focus",
            })
        return sources
