"""🔮 棱镜 — Orchestrator agent.

Responsibilities:
- Scan for new research projects (status=未开始)
- Decompose projects into task chains on the Agent Board
- Monitor pipeline progress and update project status
"""

from __future__ import annotations

import json
import logging

from spectrum.agents.base import AgentBase
from spectrum.db.activity_log import ActivityLogger
from spectrum.db.models import AgentTask
from spectrum.db.operations import DatabaseOps
from spectrum.llm.client import LLMClient
from spectrum.llm.prompts import PRISM_SYSTEM

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

    async def check_for_new_projects(self) -> list[str]:
        """Scan Research Projects with status=未开始, decompose into tasks."""
        events: list[str] = []
        projects = await self.db.list_projects(status="未开始")

        for project in projects:
            self.logger.info("Decomposing project: %s", project.name)

            # Ask LLM to decompose
            response = await self.llm.complete(
                agent_name=self.agent_name,
                system=PRISM_SYSTEM,
                messages=[{"role": "user", "content": (
                    f"课题名称: {project.name}\n"
                    f"领域: {project.domain}\n"
                    f"研究问题: {project.research_questions}\n"
                    f"范围: {project.scope}\n"
                    f"产出类型: {project.output_type}\n"
                    f"优先级: {project.priority}\n\n"
                    "请将此课题拆解为具体任务链。返回 JSON 数组。"
                )}],
            )

            # Parse task chain from LLM response
            tasks = self._parse_task_chain(response.content, project.id, project.priority)

            if tasks:
                # Create tasks with dependency chain
                created_ids: list[int] = []
                for task_data in tasks:
                    dep_idx = task_data.pop("_depends_on_index", None)
                    if dep_idx is not None and 0 <= dep_idx < len(created_ids):
                        task_data["depends_on"] = str(created_ids[dep_idx])
                        task_data["status"] = "Waiting"
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
                await self.db.update_project(project.id, status="进行中", assigned_agent="prism")
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

    async def check_pipeline_progress(self) -> list[str]:
        """Check if all tasks for a project are Done → mark project 完成."""
        events: list[str] = []
        active_projects = await self.db.list_projects(status="进行中")

        for project in active_projects:
            tasks = await self.db.list_tasks(project_ref=project.id)
            if not tasks:
                continue

            all_done = all(t.status == "Done" for t in tasks)
            if all_done:
                await self.db.update_project(
                    project.id,
                    status="完成",
                    review_needed=True,
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

    def _parse_task_chain(
        self, content: str, project_id: int, priority: str
    ) -> list[dict]:
        """Parse LLM response into task dicts."""
        # Extract JSON from response (may be wrapped in markdown code block)
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
            # Fallback: create default 3-task chain
            return self._default_task_chain(project_id, priority)

        tasks = []
        for i, rt in enumerate(raw_tasks):
            task_type = rt.get("type", "采集")
            tasks.append({
                "name": rt.get("name", f"任务-{i+1}"),
                "type": task_type,
                "assigned_agent": rt.get("assigned_agent", TASK_TYPE_TO_AGENT.get(task_type, "focus")),
                "priority": rt.get("priority", priority),
                "message": rt.get("message", ""),
                "project_ref": project_id,
                "_depends_on_index": rt.get("depends_on_index"),
            })
        return tasks

    def _default_task_chain(self, project_id: int, priority: str) -> list[dict]:
        """Fallback: standard 3-task chain."""
        return [
            {
                "name": "素材采集",
                "type": "采集",
                "assigned_agent": "focus",
                "priority": priority,
                "message": "请根据课题搜索并采集相关素材",
                "project_ref": project_id,
                "_depends_on_index": None,
            },
            {
                "name": "概念分析",
                "type": "分析",
                "assigned_agent": "dispersion",
                "priority": priority,
                "message": "请分析采集的素材，提炼核心概念",
                "project_ref": project_id,
                "_depends_on_index": 0,
            },
            {
                "name": "文稿产出",
                "type": "产出",
                "assigned_agent": "diffraction",
                "priority": priority,
                "message": "请根据知识卡片合成文稿",
                "project_ref": project_id,
                "_depends_on_index": 1,
            },
        ]
