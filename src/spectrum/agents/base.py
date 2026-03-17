"""AgentBase — abstract lifecycle for all agents.

Each agent follows the tick/process_task pattern:
  tick() polls for assigned Todo tasks → process_task() handles each one.
"""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod

from spectrum.db.activity_log import ActivityLogger
from spectrum.db.models import AgentTask
from spectrum.db.operations import DatabaseOps
from spectrum.llm.client import LLMClient

logger = logging.getLogger(__name__)


class AgentBase(ABC):
    """Base class for all Spectrum OS agents."""

    # Subclasses set these
    agent_name: str = ""       # e.g. "prism", "focus"
    agent_label: str = ""      # e.g. "🔮 棱镜"

    def __init__(
        self,
        db: DatabaseOps,
        llm: LLMClient,
        activity_logger: ActivityLogger,
    ) -> None:
        self.db = db
        self.llm = llm
        self.activity_logger = activity_logger
        self.logger = logging.getLogger(f"spectrum.agents.{self.agent_name}")

    async def tick(self) -> list[str]:
        """Main loop entry — called by the scheduler every tick.

        1. Query Agent Board for tasks assigned to this agent with status=Todo
        2. Process each: Todo → Doing → process_task() → Done
        3. On error: set Waiting + Review Needed
        4. Return list of events produced
        """
        events: list[str] = []

        tasks = await self.db.list_tasks_for_agent(self.agent_name, "Todo")
        if not tasks:
            return events

        self.logger.info("%s found %d tasks", self.agent_label, len(tasks))

        for task in tasks:
            # Transition to Doing
            await self.db.update_task(task.id, status="Doing")
            await self.activity_logger.log(
                actor=self.agent_name,
                action_type="Update",
                target_db="Agent Board",
                description=f"开始处理: {task.name}",
                target_record=str(task.id),
                before="Todo",
                after="Doing",
            )

            try:
                task_events = await self.process_task(task)
                events.extend(task_events)

                # Transition to Done
                await self.db.update_task(task.id, status="Done")
                await self.activity_logger.log(
                    actor=self.agent_name,
                    action_type="Update",
                    target_db="Agent Board",
                    description=f"完成: {task.name}",
                    target_record=str(task.id),
                    before="Doing",
                    after="Done",
                )
                events.append(f"task_done:{task.id}")

            except Exception as e:
                self.logger.exception("Failed to process task %s: %s", task.name, e)
                await self.db.update_task(
                    task.id,
                    status="Waiting",
                    review_needed=True,
                    ai_notes=f"处理失败: {e}",
                )
                await self.activity_logger.log(
                    actor=self.agent_name,
                    action_type="Update",
                    target_db="Agent Board",
                    description=f"处理失败: {task.name}",
                    target_record=str(task.id),
                    before="Doing",
                    after="Waiting",
                    needs_review=True,
                    notes=str(e),
                )

        return events

    @abstractmethod
    async def process_task(self, task: AgentTask) -> list[str]:
        """Process a single task. Return list of events produced."""
        ...
