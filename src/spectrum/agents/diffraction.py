"""🌊 衍射 — Curator / output agent.

Responsibilities:
- Read Wiki cards for a project
- Stage 1: Generate detailed outline from cards
- Stage 2: Expand outline section-by-section into full document
- Stage 3: Critical review and revision
- Create Output records with full content
- Mark as Review Needed for Kuro
"""

from __future__ import annotations

import json
import logging
import re

from spectrum.agents._parsing import extract_json_from_llm
from spectrum.agents.base import AgentBase
from spectrum.db.models import AgentTask
from spectrum.llm.prompts import (
    DIFFRACTION_OUTLINE_PROMPT,
    DIFFRACTION_REVIEW_PROMPT,
    DIFFRACTION_SYSTEM,
)

logger = logging.getLogger(__name__)


class DiffractionAgent(AgentBase):
    agent_name = "diffraction"
    agent_label = "🌊 衍射"

    async def process_task(self, task: AgentTask) -> list[str]:
        """Synthesize wiki cards into an output document via 3-stage pipeline."""
        # Route synthesis tasks to dedicated handler
        if "综合产出" in (task.name or ""):
            return await self._process_synthesis_task(task)

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

        # Build card context with Card IDs for fact anchoring
        card_text = self._build_card_text(cards)

        # Append source references for additional context
        sources = []
        if task.project_ref:
            sources = list(await self.db.list_sources(project_ref=task.project_ref))
        if sources:
            card_text += "---\n## 原始素材参考\n"
            for s in sources:
                card_text += f"- Source #{s.id}: {s.title} ({s.url})\n"

        output_type = project.output_type if project else "综述"
        project_name = project.name if project else task.name

        # ── Stage 1: Outline ──────────────────────────────────────────
        self.logger.info("Stage 1: Generating outline for %s", project_name)
        outline = await self._generate_outline(
            project_name, output_type, task.message, card_text
        )

        if outline:
            gap_report_from_outline = outline.get("gap_report", "")
            await self.db.update_task(
                task.id,
                ai_notes=f"提纲: {json.dumps(outline, ensure_ascii=False)[:1000]}",
            )
        else:
            gap_report_from_outline = ""

        # ── Stage 2: Section-by-section expansion ─────────────────────
        self.logger.info("Stage 2: Expanding sections for %s", project_name)
        draft_content = await self._expand_sections(
            project_name, output_type, task.message, card_text, outline, cards=cards
        )

        # ── Stage 3: Critical review ─────────────────────────────────
        self.logger.info("Stage 3: Reviewing draft for %s", project_name)
        title = outline.get("title", project_name) if outline else project_name
        review = await self._critical_review(title, output_type, draft_content)

        # Revise if needed
        final_content = draft_content
        if review and review.get("needs_revision") and review.get("revision_instructions"):
            self.logger.info("Revising draft based on review feedback")
            final_content = await self._revise_draft(
                project_name, output_type, draft_content, card_text,
                review["revision_instructions"],
            )

        # Build ai_notes from review
        ai_notes = ""
        if review:
            issues = review.get("issues", [])
            if issues:
                issue_lines = [
                    f"- [{i.get('type')}] {i.get('location')}: {i.get('description')}"
                    for i in issues[:5]
                ]
                ai_notes = "审查发现:\n" + "\n".join(issue_lines)
            score = review.get("overall_score", "?")
            ai_notes = f"审查评分: {score}/5\n{ai_notes}"

        # Combine gap reports
        gap_report = gap_report_from_outline

        # Parse final output
        output_data = self._build_output(
            title, output_type, final_content, ai_notes,
            gap_report, task.project_ref,
        )

        if output_data:
            gap_report_final = output_data.pop("_gap_report", "")
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

            # Quality feedback loop: create supplemental collection task if gaps found
            is_supplement = "补充采集" in (task.name or "")
            if gap_report_final and gap_report_final.strip() != "无" and not is_supplement:
                await self.db.create_task(
                    name=f"补充采集 · {project_name}",
                    type="采集",
                    assigned_agent="focus",
                    priority=task.priority,
                    message=f"根据文稿产出的缺口报告进行补充采集：\n{gap_report_final}",
                    project_ref=task.project_ref,
                    status="Todo",
                )
                await self.activity_logger.log(
                    actor=self.agent_name,
                    action_type="Create",
                    target_db="Tasks",
                    description=f"创建补充采集任务: {project_name}",
                )
                self.logger.info(
                    "Created supplemental collection task for project %s", project_name
                )
        else:
            await self.db.update_task(
                task.id,
                ai_notes=final_content[:500] if final_content else "",
            )
            raise RuntimeError(
                f"未能产出文稿 (内容长度: {len(final_content or '')})"
            )

        return events

    # ── Synthesis: merge multiple outputs into one ────────────────────────

    async def _process_synthesis_task(self, task: AgentTask) -> list[str]:
        """Merge multiple sub-topic outputs into a single consolidated document."""
        events: list[str] = []

        project = None
        if task.project_ref:
            project = await self.db.get_project(task.project_ref)
        project_name = project.name if project else task.name
        output_type = project.output_type if project else "综述"

        # Gather existing outputs
        outputs = []
        if task.project_ref:
            outputs = list(await self.db.list_outputs(project_ref=task.project_ref))
        if not outputs:
            await self.db.update_task(task.id, ai_notes="无可合并的产出")
            return events

        # Build combined content
        parts = []
        for o in outputs:
            parts.append(f"## 子课题产出: {o.name}\n\n{o.content or ''}")
        combined = "\n\n---\n\n".join(parts)

        response = await self.llm.complete(
            agent_name=self.agent_name,
            system=DIFFRACTION_SYSTEM,
            messages=[{"role": "user", "content": (
                f"课题: {project_name}\n"
                f"产出类型: {output_type}\n\n"
                f"以下是多个子课题的独立产出，请将它们合并为一篇完整的综合文稿。\n"
                f"要求: 统一叙事线，消除重复内容，补充过渡段落，保持引用标注。\n"
                f"使用 Markdown 格式，直接输出正文。\n\n"
                f"{combined[:30000]}"
            )}],
        )
        final_content = response.content or ""

        output_data = self._build_output(
            f"综合报告 · {project_name}", output_type, final_content,
            "", "", task.project_ref,
        )
        if output_data:
            output_data.pop("_gap_report", "")
            created = await self.db.create_output(**output_data)
            await self.activity_logger.log(
                actor=self.agent_name,
                action_type="Create",
                target_db="Outputs",
                description=f"综合产出: {output_data['name']}",
                target_record=str(created.id),
                needs_review=True,
            )
            events.append(f"output_created:{created.id}")
            await self.db.update_task(
                task.id, message=f"已产出综合文稿: {output_data['name']}",
            )
        else:
            await self.db.update_task(
                task.id, ai_notes=final_content[:500] if final_content else "",
            )
            raise RuntimeError(
                f"未能产出综合文稿 (内容长度: {len(final_content or '')})"
            )

        return events

    # ── Stage 1: Outline generation ──────────────────────────────────────

    async def _generate_outline(
        self, project_name: str, output_type: str, task_message: str, card_text: str,
    ) -> dict | None:
        """Generate a structured outline from wiki cards."""
        prompt = DIFFRACTION_OUTLINE_PROMPT.format(
            project_name=project_name,
            output_type=output_type,
            task_message=task_message,
            card_text=card_text,
        )
        try:
            response = await self.llm.complete(
                agent_name=self.agent_name,
                system="你是结构化写作专家。只输出 JSON，不要输出其他内容。",
                messages=[{"role": "user", "content": prompt}],
            )
            return extract_json_from_llm(response.content, expect_type=dict)
        except Exception:
            self.logger.warning("Failed to generate outline, falling back to single-pass")
            return None

    # ── Stage 2: Section expansion ───────────────────────────────────────

    async def _expand_sections(
        self,
        project_name: str,
        output_type: str,
        task_message: str,
        card_text: str,
        outline: dict | None,
        cards: list | None = None,
    ) -> str:
        """Expand outline into full document. Falls back to single-pass if no outline."""
        if outline and outline.get("sections"):
            return await self._expand_with_outline(
                project_name, output_type, task_message, card_text, outline, cards=cards
            )
        # Fallback: single-pass generation (original behavior)
        return await self._single_pass_generate(
            project_name, output_type, task_message, card_text
        )

    async def _expand_with_outline(
        self,
        project_name: str,
        output_type: str,
        task_message: str,
        card_text: str,
        outline: dict,
        cards: list | None = None,
    ) -> str:
        """Expand each section of the outline sequentially."""
        sections = outline.get("sections", [])
        thesis = outline.get("thesis", "")
        title = outline.get("title", project_name)

        all_sections: list[str] = []
        section_summaries: list[str] = []  # concise summaries for dedup context
        for i, section in enumerate(sections):
            heading = section.get("heading", f"第{i+1}节")
            purpose = section.get("purpose", "")
            card_ids = section.get("card_ids", [])
            logic_flow = section.get("logic_flow", "")
            depth = section.get("depth", "详述")
            dedup_note = section.get("dedup_note", "")

            # Filter cards relevant to this section — use full text for relevant subset
            if card_ids and cards:
                id_set = {str(cid) for cid in card_ids}
                relevant = [c for c in cards if str(c.id) in id_set]
                relevant_cards = self._build_card_text_full(relevant) if relevant else card_text
            elif card_ids:
                relevant_cards = self._filter_card_text(card_text, card_ids)
            else:
                relevant_cards = card_text

            section_prompt = (
                f"你正在撰写「{title}」（{output_type}）的第 {i+1}/{len(sections)} 节。\n\n"
                f"全文主线: {thesis}\n"
                f"本节标题: {heading}\n"
                f"本节目的: {purpose}\n"
                f"逻辑线索: {logic_flow}\n"
                f"展开深度: {depth}\n"
                f"使用的卡片 ID: {card_ids}\n\n"
            )

            # Dedup instructions
            if dedup_note:
                section_prompt += f"⚠️ 去重边界: {dedup_note}\n\n"

            # Pass summaries of completed sections for dedup awareness
            if section_summaries:
                section_prompt += "已完成章节摘要（避免重复这些内容）:\n"
                for j, summary in enumerate(section_summaries):
                    section_prompt += f"  第{j+1}节: {summary}\n"
                section_prompt += "\n"

            #衔接上下文
            if all_sections:
                prev_ending = all_sections[-1][-200:]
                section_prompt += f"上一节末尾内容（用于衔接）:\n{prev_ending}\n\n"

            section_prompt += (
                f"可用知识卡片:\n{relevant_cards}\n\n"
                "请撰写本节内容。使用 Markdown 格式。"
                "每个事实性陈述必须标注 [Card #ID] 来源。"
                "直接输出本节 Markdown 内容，不要包含 JSON 或其他格式。\n"
            )

            if depth == "概述":
                section_prompt += (
                    "⚠️ 本节为概述深度：只做简要提及和全景导览，"
                    "不要展开完整公式推导或详细技术分析。"
                    "详细内容留给后续章节。\n"
                )

            response = await self.llm.complete(
                agent_name=self.agent_name,
                system=DIFFRACTION_SYSTEM,
                messages=[{"role": "user", "content": section_prompt}],
            )
            section_content = response.content or ""
            all_sections.append(section_content)

            # Generate a concise summary for dedup context (first 120 chars + key topics)
            summary = section_content[:120].replace("\n", " ").strip()
            if len(section_content) > 120:
                summary += "..."
            section_summaries.append(f"[{heading}] {summary}")

        return f"# {title}\n\n" + "\n\n".join(all_sections)

    async def _single_pass_generate(
        self, project_name: str, output_type: str, task_message: str, card_text: str,
    ) -> str:
        """Fallback: single LLM call to generate entire document."""
        response = await self.llm.complete(
            agent_name=self.agent_name,
            system=DIFFRACTION_SYSTEM,
            messages=[{"role": "user", "content": (
                f"课题: {project_name}\n"
                f"产出类型: {output_type}\n"
                f"任务指令: {task_message}\n\n"
                f"以下是相关知识卡片：\n\n{card_text}\n"
                "请合成一篇结构化文稿。使用 Markdown 格式，直接输出正文。"
            )}],
        )
        return response.content or ""

    # ── Stage 3: Critical review ─────────────────────────────────────────

    async def _critical_review(
        self, title: str, output_type: str, content: str,
    ) -> dict | None:
        """Review the draft for quality issues."""
        if not content or len(content) < 100:
            return None

        prompt = DIFFRACTION_REVIEW_PROMPT.format(
            title=title,
            output_type=output_type,
            content=content[:15000],  # cap to avoid token overflow
        )
        try:
            response = await self.llm.complete(
                agent_name=self.agent_name,
                system="你是学术写作审稿专家。只输出 JSON，不要输出其他内容。",
                messages=[{"role": "user", "content": prompt}],
            )
            return extract_json_from_llm(response.content, expect_type=dict)
        except Exception:
            self.logger.warning("Failed to parse review result")
            return None

    async def _revise_draft(
        self,
        project_name: str,
        output_type: str,
        draft: str,
        card_text: str,
        revision_instructions: str,
    ) -> str:
        """Revise the draft based on review feedback."""
        response = await self.llm.complete(
            agent_name=self.agent_name,
            system=DIFFRACTION_SYSTEM,
            messages=[{"role": "user", "content": (
                f"课题: {project_name}\n"
                f"产出类型: {output_type}\n\n"
                f"以下是初稿：\n\n{draft[:15000]}\n\n"
                f"可用知识卡片:\n{card_text}\n\n"
                f"审稿意见：\n{revision_instructions}\n\n"
                "请根据审稿意见修订文稿。直接输出修订后的 Markdown 内容。"
                "每个事实性陈述必须标注 [Card #ID] 来源。"
            )}],
        )
        return response.content or draft

    # ── Card filtering ────────────────────────────────────────────────────

    @staticmethod
    def _filter_card_text(card_text: str, card_ids: list) -> str:
        """Extract only the cards matching the given IDs from the full card text.

        Card text is formatted as sections starting with ``### Card #<id>``.
        If no matching cards are found, returns the full text as fallback.
        """
        if not card_ids:
            return card_text

        id_set = {str(cid) for cid in card_ids}
        blocks = re.split(r"(?=### Card #)", card_text)
        matched = []
        for block in blocks:
            for cid in id_set:
                if f"### Card #{cid}" in block:
                    matched.append(block.strip())
                    break

        return "\n\n".join(matched) if matched else card_text

    # ── Output building ──────────────────────────────────────────────────

    def _build_output(
        self,
        title: str,
        output_type: str,
        content: str,
        ai_notes: str,
        gap_report: str,
        project_ref: int | None,
    ) -> dict | None:
        """Build output dict from the pipeline results."""
        if not content or len(content.strip()) < 50:
            return None

        # Safety net: unwrap JSON if LLM returned {"title":..,"content":..}
        stripped = content.strip()
        if stripped.startswith("{"):
            try:
                parsed = json.loads(stripped)
                if isinstance(parsed, dict) and "content" in parsed:
                    content = parsed["content"]
                    if parsed.get("title"):
                        title = parsed["title"]
            except (json.JSONDecodeError, TypeError):
                pass

        # Extract GAP_REPORT from HTML comment at end of content
        gap_match = re.search(
            r"<!--\s*GAP_REPORT\s*\n(.*?)-->", content, re.DOTALL
        )
        if gap_match:
            extracted_gap = gap_match.group(1).strip()
            if extracted_gap:
                gap_report = (
                    f"{gap_report}\n{extracted_gap}".strip() if gap_report else extracted_gap
                )
            content = content[: gap_match.start()].rstrip()

        word_count = len(content)
        if gap_report and gap_report.strip():
            ai_notes = f"{ai_notes}\n\n【缺口报告】\n{gap_report}".strip()

        return {
            "name": title,
            "type": output_type,
            "status": "进行中",
            "project_ref": project_ref,
            "assigned_agent": "diffraction",
            "word_count": word_count,
            "content": content,
            "ai_notes": ai_notes,
            "review_needed": True,
            "_gap_report": gap_report,
        }

    # ── Helpers ───────────────────────────────────────────────────────────

    @staticmethod
    def _build_card_text(cards) -> str:
        """Build card context string with Card IDs for fact anchoring."""
        card_text = ""
        for c in cards:
            card_text += (
                f"### Card #{c.id}: {c.concept} ({c.type})\n"
                f"定义: {c.definition}\n"
                f"要点: {c.key_points}\n\n"
            )
        return card_text

    @staticmethod
    def _build_card_text_full(cards) -> str:
        """Build full card context including explanation (for single-section use)."""
        card_text = ""
        for c in cards:
            card_text += (
                f"### Card #{c.id}: {c.concept} ({c.type})\n"
                f"定义: {c.definition}\n"
                f"解释: {c.explanation}\n"
                f"要点: {c.key_points}\n"
                f"示例: {c.example}\n\n"
            )
        return card_text
