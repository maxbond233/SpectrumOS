"""💠 聚光 — Collector agent (4-stage search pipeline).

Stages:
  1. plan_search   — LLM plans keywords and strategy
  2. execute_search — code drives multi-provider search + content extraction
  3. evaluate       — LLM scores coverage, may trigger another round
  4. synthesize     — LLM produces structured source records from collected content
"""

from __future__ import annotations

import json
import logging
from datetime import date

from spectrum.agents.base import AgentBase
from spectrum.db.models import AgentTask
from spectrum.llm.prompts import (
    FOCUS_EVALUATION_PROMPT,
    FOCUS_PLANNING_PROMPT,
    FOCUS_SYSTEM,
)
from spectrum.tools.search_providers import SearchResult
from spectrum.tools.web_search import WebSearchTool

logger = logging.getLogger(__name__)


class FocusAgent(AgentBase):
    agent_name = "focus"
    agent_label = "💠 聚光"

    def __init__(self, *args, search_tool: WebSearchTool, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self.search_tool = search_tool

    # ── Main entry ───────────────────────────────────────────────────────────

    async def process_task(self, task: AgentTask) -> list[str]:
        """Collect materials via 4-stage pipeline: plan → search → evaluate → synthesize."""
        events: list[str] = []

        # Build context
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

        # Stage 1 — Plan
        plan = await self._plan_search(context)
        self.logger.info("Search plan: %d keywords, %d academic keywords",
                         len(plan.get("keywords", [])),
                         len(plan.get("academic_keywords", [])))

        # Stage 2+3 — Execute + Evaluate loop
        all_results: list[SearchResult] = []
        all_pages: dict[str, str] = {}  # url → extracted text
        max_rounds = self.search_tool._config.max_search_rounds

        keywords = plan.get("keywords", [])
        academic_keywords = plan.get("academic_keywords", [])

        # Freshness: append current year to keywords for time-sensitive topics
        if plan.get("freshness") == "recent":
            year = str(date.today().year)
            keywords = [f"{kw} {year}" for kw in keywords]

        for round_num in range(max_rounds):
            self.logger.info("Search round %d/%d", round_num + 1, max_rounds)

            # Execute search
            new_results, new_pages = await self._execute_search(
                keywords, academic_keywords, all_pages
            )
            all_results.extend(new_results)
            all_pages.update(new_pages)

            # Evaluate (skip on last round)
            if round_num < max_rounds - 1:
                evaluation = await self._evaluate_results(context, all_results, all_pages)
                if evaluation.get("sufficient", False):
                    self.logger.info("Coverage sufficient (score=%s), stopping search",
                                     evaluation.get("coverage_score"))
                    break
                # Use supplemental keywords for next round
                keywords = evaluation.get("additional_keywords", [])
                academic_keywords = []  # only supplement with general keywords
                if not keywords:
                    break
                self.logger.info("Coverage insufficient, supplementing with: %s", keywords)
            # Clear for next round — only search new keywords
            academic_keywords = []

        self.logger.info("Search complete: %d results, %d pages extracted",
                         len(all_results), len(all_pages))

        # Stage 4 — Synthesize
        response_content = await self._synthesize_sources(context, all_results, all_pages)

        # Parse and persist sources
        sources = self._parse_sources(response_content, task.project_ref)

        if not sources:
            await self.db.update_task(
                task.id,
                ai_notes=response_content[:500] if response_content else "",
            )
            raise RuntimeError(
                f"未能从 LLM 响应中解析出任何素材 (响应长度: {len(response_content or '')})"
            )

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

        await self.db.update_task(
            task.id,
            message=f"已采集 {len(sources)} 个素材 ({len(all_results)} 搜索结果, {len(all_pages)} 页面提取)",
            ai_notes=response_content[:500] if response_content else "",
        )

        return events

    # ── Stage 1: Plan ────────────────────────────────────────────────────────

    async def _plan_search(self, context: str) -> dict:
        """LLM generates search keywords and strategy."""
        prompt = FOCUS_PLANNING_PROMPT.format(
            context=context,
            current_date=date.today().isoformat(),
        )
        response = await self.llm.complete(
            agent_name=self.agent_name,
            system="你是搜索规划专家。只输出 JSON，不要输出其他内容。",
            messages=[{"role": "user", "content": prompt}],
        )
        try:
            return self._extract_json(response.content, expect_type=dict)
        except Exception:
            self.logger.warning("Failed to parse search plan, using defaults")
            return {"keywords": [context[:100]], "academic_keywords": []}

    # ── Stage 2: Execute ─────────────────────────────────────────────────────

    async def _execute_search(
        self,
        keywords: list[str],
        academic_keywords: list[str],
        existing_pages: dict[str, str],
    ) -> tuple[list[SearchResult], dict[str, str]]:
        """Code-driven search: run keywords through providers, fetch top pages."""
        all_results: list[SearchResult] = []

        # General search for each keyword
        for kw in keywords:
            results = await self.search_tool.search(kw)
            all_results.extend(results)

        # Academic search
        for kw in academic_keywords:
            results = await self.search_tool.search_academic(kw)
            all_results.extend(results)

        # Fetch top pages (skip already-fetched URLs)
        new_pages: dict[str, str] = {}
        urls_to_fetch = []
        for r in all_results:
            if r.url and r.url not in existing_pages and r.url not in new_pages:
                urls_to_fetch.append(r.url)

        # Fetch top 8 new URLs
        for url in urls_to_fetch[:8]:
            try:
                page = await self.search_tool.fetch_page(url)
                new_pages[url] = page.text[:30000]
            except Exception as e:
                self.logger.debug("Failed to fetch %s: %s", url, e)

        return all_results, new_pages

    # ── Stage 3: Evaluate ────────────────────────────────────────────────────

    async def _evaluate_results(
        self,
        context: str,
        results: list[SearchResult],
        pages: dict[str, str],
    ) -> dict:
        """LLM evaluates coverage and suggests supplemental keywords."""
        # Build summary of what we have
        sources_summary = []
        for r in results[:20]:  # cap to avoid token overflow
            entry = f"- {r.title} ({r.source_provider})"
            if r.url:
                entry += f"\n  URL: {r.url}"
            if r.snippet:
                entry += f"\n  摘要: {r.snippet[:200]}"
            sources_summary.append(entry)

        summary_text = "\n".join(sources_summary)
        summary_text += f"\n\n已提取全文页面数: {len(pages)}"

        prompt = FOCUS_EVALUATION_PROMPT.format(
            context=context,
            sources_summary=summary_text,
        )
        response = await self.llm.complete(
            agent_name=self.agent_name,
            system="你是搜索质量评估专家。只输出 JSON，不要输出其他内容。",
            messages=[{"role": "user", "content": prompt}],
        )
        try:
            return self._extract_json(response.content, expect_type=dict)
        except Exception:
            self.logger.warning("Failed to parse evaluation, assuming sufficient")
            return {"sufficient": True, "coverage_score": 3}

    # ── Stage 4: Synthesize ──────────────────────────────────────────────────

    async def _synthesize_sources(
        self,
        context: str,
        results: list[SearchResult],
        pages: dict[str, str],
    ) -> str:
        """LLM synthesizes collected content into structured source records."""
        # Build input: search results + extracted page content
        materials = []
        seen_urls: set[str] = set()
        for r in results:
            if r.url in seen_urls:
                continue
            seen_urls.add(r.url)
            entry = f"## {r.title}\nURL: {r.url}\nProvider: {r.source_provider}\n"
            if r.authors:
                entry += f"Authors: {r.authors}\n"
            if r.year:
                entry += f"Year: {r.year}\n"
            entry += f"Snippet: {r.snippet}\n"
            # Attach full page content if available
            if r.url in pages:
                entry += f"\n### 全文内容（截取）\n{pages[r.url][:10000]}\n"
            materials.append(entry)

        materials_text = "\n---\n".join(materials[:20])  # cap to avoid token overflow

        response = await self.llm.complete(
            agent_name=self.agent_name,
            system=FOCUS_SYSTEM,
            messages=[{"role": "user", "content": (
                f"{context}\n\n"
                f"以下是已采集的 {len(materials)} 个素材的详细内容：\n\n"
                f"{materials_text}\n\n"
                "请为每个有价值的素材生成结构化记录（JSON 数组）。"
            )}],
        )
        return response.content or ""

    # ── Helpers ───────────────────────────────────────────────────────────────

    def _extract_json(self, content: str, expect_type: type = list):
        """Extract JSON from LLM response, handling markdown code blocks."""
        text = content.strip()
        # Strip markdown code fences
        if "```" in text:
            lines = text.split("\n")
            inside = False
            json_lines = []
            for line in lines:
                if line.strip().startswith("```"):
                    inside = not inside
                    continue
                if inside:
                    json_lines.append(line)
            if json_lines:
                text = "\n".join(json_lines)

        # Find the JSON structure
        if expect_type is dict:
            start = text.find("{")
            end = text.rfind("}") + 1
        else:
            start = text.find("[")
            end = text.rfind("]") + 1

        if start >= 0 and end > start:
            text = text[start:end]

        result = json.loads(text)
        if not isinstance(result, expect_type):
            raise TypeError(f"Expected {expect_type}, got {type(result)}")
        return result

    def _parse_sources(self, content: str, project_ref: int | None) -> list[dict]:
        """Parse LLM response into source dicts."""
        try:
            raw = self._extract_json(content, expect_type=list)
        except (json.JSONDecodeError, TypeError):
            self.logger.warning(
                "Failed to parse source list from LLM response: %s", content[:200]
            )
            if len(content.strip()) > 50:
                self.logger.info("Creating fallback source from raw LLM response")
                return [{
                    "title": f"采集素材 — {project_ref or '未知课题'}",
                    "source_type": "web",
                    "status": "Collected",
                    "url": "",
                    "authors": "",
                    "extracted_summary": content[:5000],
                    "key_questions": "",
                    "why_it_matters": "",
                    "project_ref": project_ref,
                    "assigned_agent": "focus",
                }]
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
