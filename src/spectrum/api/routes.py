"""FastAPI routes — webhook, manual trigger, health check, status queries."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException

from spectrum.api.schemas import (
    CreateProjectRequest,
    HealthResponse,
    ProjectResponse,
    StatsResponse,
    TaskResponse,
    TriggerAgentRequest,
    TriggerResponse,
)
from spectrum.db.activity_log import ActivityLogger
from spectrum.db.operations import DatabaseOps
from spectrum.orchestrator.scheduler import Scheduler

router = APIRouter()

# These get set by create_app
_scheduler: Scheduler | None = None
_db: DatabaseOps | None = None
_activity_logger: ActivityLogger | None = None


def configure(
    scheduler: Scheduler, db: DatabaseOps, activity_logger: ActivityLogger
) -> None:
    global _scheduler, _db, _activity_logger
    _scheduler = scheduler
    _db = db
    _activity_logger = activity_logger


# ── Health ───────────────────────────────────────────────────────────────────

@router.get("/health", response_model=HealthResponse)
async def health():
    agents = list(_scheduler._agents.keys()) if _scheduler else []
    return HealthResponse(agents=agents)


# ── Trigger ──────────────────────────────────────────────────────────────────

@router.post("/trigger", response_model=TriggerResponse)
async def trigger_agent(req: TriggerAgentRequest):
    if not _scheduler:
        raise HTTPException(503, "Scheduler not ready")
    try:
        events = await _scheduler.trigger_agent(req.agent)
    except ValueError as e:
        raise HTTPException(400, str(e))
    return TriggerResponse(agent=req.agent, events=events)


# ── Projects ─────────────────────────────────────────────────────────────────

@router.get("/projects", response_model=list[ProjectResponse])
async def list_projects():
    projects = await _db.list_projects()
    return [
        ProjectResponse(
            id=p.id, name=p.name, status=p.status,
            domain=p.domain, priority=p.priority, output_type=p.output_type,
        )
        for p in projects
    ]


@router.post("/projects", response_model=ProjectResponse, status_code=201)
async def create_project(req: CreateProjectRequest):
    project = await _db.create_project(
        name=req.name,
        domain=req.domain,
        research_questions=req.research_questions,
        scope=req.scope,
        output_type=req.output_type,
        priority=req.priority,
    )
    await _activity_logger.log(
        actor="api",
        action_type="Create",
        target_db="Research Projects",
        description=f"API 创建课题: {req.name}",
        target_record=str(project.id),
    )
    return ProjectResponse(
        id=project.id, name=project.name, status=project.status,
        domain=project.domain, priority=project.priority, output_type=project.output_type,
    )


# ── Tasks ────────────────────────────────────────────────────────────────────

@router.get("/tasks", response_model=list[TaskResponse])
async def list_tasks(status: str | None = None, agent: str | None = None):
    filters = {}
    if status:
        filters["status"] = status
    if agent:
        filters["assigned_agent"] = agent
    tasks = await _db.list_tasks(**filters)
    return [
        TaskResponse(
            id=t.id, name=t.name, status=t.status,
            type=t.type, assigned_agent=t.assigned_agent,
            project_ref=t.project_ref,
        )
        for t in tasks
    ]


# ── Stats ────────────────────────────────────────────────────────────────────

@router.get("/stats", response_model=StatsResponse)
async def stats():
    projects = await _db.list_projects()
    tasks = await _db.list_tasks()
    sources = await _db.list_sources()
    wiki_cards = await _db.list_wiki_cards()
    outputs = await _db.list_outputs()
    logs = await _db.list_logs()

    project_stats: dict[str, int] = {}
    for p in projects:
        project_stats[p.status] = project_stats.get(p.status, 0) + 1

    task_stats: dict[str, int] = {}
    for t in tasks:
        task_stats[t.status] = task_stats.get(t.status, 0) + 1

    return StatsResponse(
        projects=project_stats,
        tasks=task_stats,
        sources=len(sources),
        wiki_cards=len(wiki_cards),
        outputs=len(outputs),
        logs=len(logs),
    )
