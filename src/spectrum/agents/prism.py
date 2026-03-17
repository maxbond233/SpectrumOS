"""🔮 棱镜 — Orchestrator agent.

Responsibilities:
- Scan for new research projects (status=未开始)
- Generate a Research Brief for each new project
- Decompose projects into task chains with brief context injected
- Monitor pipeline progress and perform completion review
- Create supplement task chains if coverage is insufficient (max 1 round)
"""

from __future__ import annotations

import json
import logging

from spectrum.agents.base import AgentBase
from spectrum.db.models import AgentTask
from spectrum.llm.prompts import PRISM_BRIEF_PROMPT, PRISM_REVIEW_PROMPT, PRISM_SYSTEM

logger = logging.getLogger(__name__)

TASK_TYPE_TO_AGENT = {
    "采集": "focus",
    "分析": "dispersion",
    "产出": "diffraction",
}


class PrismAgent(AgentBase):
    agent_name = "prism"
    agent_label = "🔮 棱镜"

    async def tick(self) -> list[str]:
        """Extended tick: also scan for new projects and check pipeline progress."""
        events: list[str] = []

        # 1. Check for new projects to decompose
        new_events = await self.check_for_new_projects()
        events.extend(new_events)

        # 2. Check pipeline progress
        progress_events = await self.check_pipeline_progress()
        events.extend(progress_events)

        # 3. Normal task processing
        base_events = await super().tick()
        events.extend(base_events)

        return events

    async def process_task(self, task: AgentTask) -> list[str]:
        """Process a coordination task (e.g., re-plan, adjust priorities)."""
        response = await self.llm.complete(
            agent_name=self.agent_name,
            system=PRISM_SYSTEM,
            messages=[{"role": "user", "content": (
                f"任务: {task.name}\n"
                f"类型: {task.type}\n"
                f"消息: {task.message}\n"
                f"课题ID: {task.project_ref}\n\n"
                "请分析并给出处理建议。"
            )}],
        )
        if response.content:
            await self.db.update_task(task.id, ai_notes=response.content)
        return []

    # ── New project handling ─────────────────────────────────────────────

    async def check_for_new_projects(self) -> list[str]:
        """Scan Research Projects with status=未开始, decompose into tasks."""
        events: list[str] = []
        projects = await self.db.list_projects(status="未开始")

        for project in projects:
            self.logger.info("Decomposing project: %s", project.name)

            # Step 1: Generate research brief
            brief_text = await self._generate_brief(project)
            if brief_text:
                await self.db.update_project(project.id, research_brief=brief_text)
                await self.activity_logger.log(
                    actor=self.agent_name,
                    action_type="Create",
                    target_db="Research Projects",
                    description=f"生成研究简报: {project.name}",
                    target_record=str(project.id),
                )

            # Step 2: Ask LLM to decompose (with brief context)
            decompose_msg = (
                f"课题名称: {project.name}\n"
                f"领域: {project.domain}\n"
                f"研究问题: {project.research_questions}\n"
                f"范围: {project.scope}\n"
                f"产出类型: {project.output_type}\n"
                f"优先级: {project.priority}\n"
            )
            if brief_text:
                decompose_msg += f"\n研究简报:\n{brief_text}\n"
            decompose_msg += "\n请将此课题拆解为具体任务链。返回 JSON 数组。"

            response = await self.llm.complete(
                agent_name=self.agent_name,
                system=PRISM_SYSTEM,
                messages=[{"role": "user", "content": decompose_msg}],
            )

            # Parse task chain from LLM response
            tasks = self._parse_task_chain(
                response.content, project.id, project.priority, brief_text
            )

            if tasks:
                # Create tasks with dependency chain
                created_ids: list[int] = []
                for task_data in tasks:
                    dep_indices = task_data.pop("_depends_on_indices", [])
                    if dep_indices:
                        resolved = [
                            str(created_ids[i])
                            for i in dep_indices
                            if 0 <= i < len(created_ids)
                        ]
                        if resolved:
                            task_data["depends_on"] = ",".join(resolved)
                            task_data["status"] = "Waiting"
                        else:
                            task_data["status"] = "Todo"
                    else:
                        task_data["status"] = "Todo"

                    created = await self.db.create_task(**task_data)
                    created_ids.append(created.id)

                    await self.activity_logger.log(
                        actor=self.agent_name,
                        action_type="Create",
                        target_db="Agent Board",
                        description=f"创建任务: {task_data['name']}",
                        target_record=str(created.id),
                    )

                # Update project status
                await self.db.update_project(
                    project.id, status="进行中", assigned_agent="prism"
                )
                await self.activity_logger.log(
                    actor=self.agent_name,
                    action_type="Update",
                    target_db="Research Projects",
                    description=f"课题启动: {project.name}",
                    target_record=str(project.id),
                    before="未开始",
                    after="进行中",
                )
                events.append(f"project_started:{project.id}")

        return events

    # ── Pipeline progress & completion review ────────────────────────────

    async def check_pipeline_progress(self) -> list[str]:
        """Check project pipeline status and perform completion review."""
        events: list[str] = []
        active_projects = await self.db.list_projects(status="进行中")

        for project in active_projects:
            tasks = await self.db.list_tasks(project_ref=project.id)
            if not tasks:
                continue

            # Skip if any tasks are still pending/doing/waiting
            has_active = any(
                t.status in ("Todo", "Doing", "Waiting", "Inbox") for t in tasks
            )
            if has_active:
                continue

            # Skip if any tasks failed
            has_failed = any(t.status == "Failed" for t in tasks)
            if has_failed:
                continue

            all_done = all(t.status == "Done" for t in tasks)
            if not all_done:
                continue

            # Determine review path
            review_round = getattr(project, "review_round", 0) or 0
            brief = getattr(project, "research_brief", "") or ""

            if brief and review_round < 1:
                # Perform completion review
                review_result = await self._completion_review(project, tasks)
                if review_result and review_result.get("needs_supplement"):
                    # Create supplement tasks
                    await self._create_supplement_tasks(project, review_result)
                    await self.db.update_project(
                        project.id,
                        review_round=1,
                        completion_review=json.dumps(
                            review_result, ensure_ascii=False
                        ),
                    )
                    await self.activity_logger.log(
                        actor=self.agent_name,
                        action_type="Update",
                        target_db="Research Projects",
                        description=f"审核发现缺口，创建补充任务: {project.name}",
                        target_record=str(project.id),
                    )
                    events.append(f"project_supplement:{project.id}")
                    continue
                else:
                    # Review passed or review failed to parse — mark complete
                    if review_result:
                        await self.db.update_project(
                            project.id,
                            review_round=1,
                            completion_review=json.dumps(
                                review_result, ensure_ascii=False
                            ),
                        )

            # Mark project complete
            await self.db.update_project(
                project.id, status="完成", review_needed=True
            )
            await self.activity_logger.log(
                actor=self.agent_name,
                action_type="Update",
                target_db="Research Projects",
                description=f"课题完成: {project.name}",
                target_record=str(project.id),
                before="进行中",
                after="完成",
                needs_review=True,
            )
            events.append(f"project_completed:{project.id}")

        return events

    # ── Brief generation ─────────────────────────────────────────────────

    async def _generate_brief(self, project) -> str:
        """Call LLM to generate a research brief. Returns JSON string or empty."""
        try:
            prompt = PRISM_BRIEF_PROMPT.format(
                name=project.name,
                domain=project.domain or "未指定",
                research_questions=project.research_questions or "未指定",
                scope=project.scope or "未指定",
                output_type=project.output_type or "综述",
                priority=project.priority or "P2",
            )
            response = await self.llm.complete(
                agent_name=self.agent_name,
                system="你是研究规划专家。请严格按要求输出 JSON。",
                messages=[{"role": "user", "content": prompt}],
            )
            # Validate it's parseable JSON
            parsed = self._parse_json(response.content)
            if parsed and "core_questions" in parsed:
                return json.dumps(parsed, ensure_ascii=False)
        except Exception:
            self.logger.warning("Failed to generate brief for project %s", project.id)
        return ""

    def _parse_brief(self, brief_str: str) -> dict | None:
        """Parse a brief JSON string into a dict."""
        if not brief_str:
            return None
        try:
            return json.loads(brief_str)
        except (json.JSONDecodeError, TypeError):
            return None

    # ── Completion review ────────────────────────────────────────────────

    async def _completion_review(self, project, tasks) -> dict | None:
        """Call LLM to review project completion against the brief."""
        brief = getattr(project, "research_brief", "") or ""
        if not brief:
            return None

        try:
            source_count = len(await self.db.list_sources(project_ref=project.id))
            wiki_count = len(await self.db.list_wiki_cards(project_ref=project.id))
            output_count = len(await self.db.list_outputs(project_ref=project.id))
        except Exception:
            source_count = wiki_count = output_count = 0

        task_summary = ", ".join(
            f"{t.name}({t.status})" for t in tasks
        )

        prompt = PRISM_REVIEW_PROMPT.format(
            brief=brief,
            source_count=source_count,
            wiki_count=wiki_count,
            output_count=output_count,
            task_summary=task_summary,
        )

        try:
            response = await self.llm.complete(
                agent_name=self.agent_name,
                system="你是研究质量审核专家。请严格按要求输出 JSON。",
                messages=[{"role": "user", "content": prompt}],
            )
            parsed = self._parse_json(response.content)
            if parsed and "coverage_score" in parsed:
                return parsed
        except Exception:
            self.logger.warning(
                "Failed completion review for project %s", project.id
            )
        return None

    # ── Supplement task creation ──────────────────────────────────────────

    async def _create_supplement_tasks(self, project, review_result: dict) -> None:
        """Create a supplement task chain based on review gaps."""
        gaps = review_result.get("gaps", [])
        plan = review_result.get("supplement_plan", "")
        brief = getattr(project, "research_brief", "") or ""

        gap_desc = "\n".join(f"- {g}" for g in gaps) if gaps else "覆盖度不足"
        context = (
            f"【补充任务】\n"
            f"审核发现以下缺口:\n{gap_desc}\n\n"
            f"补充方向: {plan}\n\n"
        )
        if brief:
            context += f"研究简报:\n{brief}\n"

        priority = project.priority or "P2"
        tasks_data = [
            {
                "name": f"补充采集 · {plan[:30]}" if plan else "补充采集",
                "type": "采集",
                "assigned_agent": "focus",
                "priority": priority,
                "message": f"{context}\n请针对上述缺口进行补充素材采集。",
                "project_ref": project.id,
                "status": "Todo",
            },
            {
                "name": "补充分析",
                "type": "分析",
                "assigned_agent": "dispersion",
                "priority": priority,
                "message": f"{context}\n请分析补充采集的素材，提炼核心概念。",
                "project_ref": project.id,
                "status": "Waiting",
            },
            {
                "name": "补充产出",
                "type": "产出",
                "assigned_agent": "diffraction",
                "priority": priority,
                "message": f"{context}\n请根据补充的知识卡片更新文稿。",
                "project_ref": project.id,
                "status": "Waiting",
            },
        ]

        created_ids: list[int] = []
        for td in tasks_data:
            if len(created_ids) == 1:
                td["depends_on"] = str(created_ids[0])
            elif len(created_ids) == 2:
                td["depends_on"] = str(created_ids[1])
            created = await self.db.create_task(**td)
            created_ids.append(created.id)

            await self.activity_logger.log(
                actor=self.agent_name,
                action_type="Create",
                target_db="Agent Board",
                description=f"创建补充任务: {td['name']}",
                target_record=str(created.id),
            )

    # ── Task chain parsing ───────────────────────────────────────────────

    def _parse_task_chain(
        self,
        content: str,
        project_id: int,
        priority: str,
        brief_text: str = "",
    ) -> list[dict]:
        """Parse LLM response into task dicts. Supports multi-dependency."""
        text = content.strip()
        if "```" in text:
            start = text.find("[")
            end = text.rfind("]") + 1
            if start >= 0 and end > start:
                text = text[start:end]

        try:
            raw_tasks = json.loads(text)
        except json.JSONDecodeError:
            self.logger.warning("Failed to parse LLM task chain response")
            return self._default_task_chain(project_id, priority, brief_text)

        tasks = []
        for i, rt in enumerate(raw_tasks):
            task_type = rt.get("type", "采集")
            dep_raw = rt.get("depends_on_index")

            # Normalize depends_on_index to a list of ints
            if dep_raw is None:
                dep_indices = []
            elif isinstance(dep_raw, list):
                dep_indices = [int(d) for d in dep_raw if isinstance(d, (int, float))]
            else:
                dep_indices = [int(dep_raw)]

            tasks.append({
                "name": rt.get("name", f"任务-{i+1}"),
                "type": task_type,
                "assigned_agent": rt.get(
                    "assigned_agent", TASK_TYPE_TO_AGENT.get(task_type, "focus")
                ),
                "priority": rt.get("priority", priority),
                "message": rt.get("message", ""),
                "project_ref": project_id,
                "_depends_on_indices": dep_indices,
            })
        return tasks

    def _default_task_chain(
        self, project_id: int, priority: str, brief_text: str = ""
    ) -> list[dict]:
        """Fallback: standard 3-task chain with brief context injected."""
        context = ""
        if brief_text:
            context = f"\n\n研究简报:\n{brief_text}"

        return [
            {
                "name": "素材采集",
                "type": "采集",
                "assigned_agent": "focus",
                "priority": priority,
                "message": f"请根据课题搜索并采集相关素材{context}",
                "project_ref": project_id,
                "_depends_on_indices": [],
            },
            {
                "name": "概念分析",
                "type": "分析",
                "assigned_agent": "dispersion",
                "priority": priority,
                "message": f"请分析采集的素材，提炼核心概念{context}",
                "project_ref": project_id,
                "_depends_on_indices": [0],
            },
            {
                "name": "文稿产出",
                "type": "产出",
                "assigned_agent": "diffraction",
                "priority": priority,
                "message": f"请根据知识卡片合成文稿{context}",
                "project_ref": project_id,
                "_depends_on_indices": [1],
            },
        ]

    # ── Helpers ───────────────────────────────────────────────────────────

    @staticmethod
    def _parse_json(content: str) -> dict | None:
        """Extract and parse JSON from LLM response (handles markdown fences)."""
        text = content.strip()
        if "```" in text:
            # Try to find JSON object or array
            for start_char, end_char in [("{", "}"), ("[", "]")]:
                start = text.find(start_char)
                end = text.rfind(end_char) + 1
                if start >= 0 and end > start:
                    text = text[start:end]
                    break
        try:
            return json.loads(text)
        except (json.JSONDecodeError, TypeError):
            return None
