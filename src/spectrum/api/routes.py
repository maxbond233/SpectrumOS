"""FastAPI routes — webhook, manual trigger, health check, status queries."""

from __future__ import annotations

from datetime import datetime, timezone, timedelta

from fastapi import APIRouter, HTTPException

from spectrum.api.schemas import (
    AgentInfo,
    CreateProjectRequest,
    CreateSourceRequest,
    DashboardStatsResponse,
    HealthResponse,
    LogResponse,
    OutputDetailResponse,
    OutputResponse,
    PaginatedResponse,
    ProjectDetailResponse,
    ProjectResponse,
    SourceDetailResponse,
    SourceResponse,
    StatsResponse,
    TableStats,
    TaskDetailResponse,
    TaskResponse,
    TriggerAgentRequest,
    TriggerResponse,
    UpdateTaskRequest,
    WikiCardDetailResponse,
    WikiCardResponse,
)
from spectrum.db.activity_log import ActivityLogger
from spectrum.db.models import ActivityLog, AgentTask, Output, Source, WikiCard
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


# ── Agent Definitions ───────────────────────────────────────────────────────

AGENT_DEFS = [
    {"name": "棱镜", "key": "prism",       "emoji": "🔮", "role": "总控", "role_en": "Orchestrator", "color": "#10b981"},
    {"name": "聚光", "key": "focus",        "emoji": "💠", "role": "采集", "role_en": "Collector",    "color": "#f59e0b"},
    {"name": "色散", "key": "dispersion",   "emoji": "🌈", "role": "分析", "role_en": "Analyst",      "color": "#8b5cf6"},
    {"name": "衍射", "key": "diffraction",  "emoji": "🌊", "role": "沉淀", "role_en": "Curator",      "color": "#06b6d4"},
]


# ── Dashboard Stats ─────────────────────────────────────────────────────────

def _group_by(items, attr: str) -> dict[str, int]:
    counts: dict[str, int] = {}
    for item in items:
        val = getattr(item, attr, "") or ""
        if val:
            counts[val] = counts.get(val, 0) + 1
    return counts


def _recent_items(items, fields: list[str], limit: int = 5) -> list[dict]:
    recent = []
    for item in items[:limit]:
        entry: dict = {"id": item.id}
        for f in fields:
            entry[f] = getattr(item, f, "")
        # Use 'title' key for display — pick the best name field
        if "title" not in entry:
            entry["title"] = getattr(item, "name", "") or getattr(item, "concept", "") or getattr(item, "title", "")
        recent.append(entry)
    return recent


@router.get("/dashboard/stats", response_model=DashboardStatsResponse)
async def dashboard_stats():
    projects = await _db.list_projects()
    sources = await _db.list_sources()
    wiki_cards = await _db.list_wiki_cards()
    outputs = await _db.list_outputs()
    tasks = await _db.list_tasks()
    logs = await _db.list_logs()

    # Agent task counts
    agent_task_counts: dict[str, int] = {}
    for t in tasks:
        if t.assigned_agent:
            agent_task_counts[t.assigned_agent] = agent_task_counts.get(t.assigned_agent, 0) + 1

    active_agents = set()
    for t in tasks:
        if t.status == "Doing" and t.assigned_agent:
            active_agents.add(t.assigned_agent)

    agent_infos = []
    for a in AGENT_DEFS:
        agent_infos.append(AgentInfo(
            **a,
            active=a["name"] in active_agents,
            task_count=agent_task_counts.get(a["name"], 0),
        ))

    databases: dict[str, TableStats] = {}

    # Research Projects
    databases["projects"] = TableStats(
        total=len(projects),
        primary=_group_by(projects, "status"),
        secondary={"domain": _group_by(projects, "domain"), "priority": _group_by(projects, "priority")},
        review_needed=sum(1 for p in projects if p.review_needed),
        recent=_recent_items(projects, ["name", "status", "domain", "priority"]),
    )

    # Sources
    databases["sources"] = TableStats(
        total=len(sources),
        primary=_group_by(sources, "status"),
        secondary={"domain": _group_by(sources, "domain"), "source_type": _group_by(sources, "source_type")},
        review_needed=sum(1 for s in sources if s.review_needed),
        recent=_recent_items(sources, ["title", "status", "domain", "source_type"]),
    )

    # Wiki Cards
    databases["wiki"] = TableStats(
        total=len(wiki_cards),
        primary=_group_by(wiki_cards, "maturity"),
        secondary={"domain": _group_by(wiki_cards, "domain"), "type": _group_by(wiki_cards, "type")},
        review_needed=sum(1 for w in wiki_cards if w.needs_review),
        recent=_recent_items(wiki_cards, ["concept", "maturity", "domain", "type"]),
    )

    # Outputs
    databases["outputs"] = TableStats(
        total=len(outputs),
        primary=_group_by(outputs, "status"),
        secondary={"type": _group_by(outputs, "type")},
        review_needed=sum(1 for o in outputs if o.review_needed),
        recent=_recent_items(outputs, ["name", "status", "type"]),
    )

    # Tasks
    databases["tasks"] = TableStats(
        total=len(tasks),
        primary=_group_by(tasks, "status"),
        secondary={"type": _group_by(tasks, "type"), "agent": _group_by(tasks, "assigned_agent")},
        review_needed=sum(1 for t in tasks if t.review_needed),
        recent=_recent_items(tasks, ["name", "status", "type", "assigned_agent"]),
    )

    # Activity Log
    databases["activity_log"] = TableStats(
        total=len(logs),
        primary=_group_by(logs, "action_type"),
        secondary={"actor": _group_by(logs, "actor"), "target_db": _group_by(logs, "target_db")},
        review_needed=sum(1 for lg in logs if lg.needs_review),
        recent=_recent_items(logs, ["title", "action_type", "actor", "target_db"]),
    )

    now = datetime.now(timezone(timedelta(hours=8)))
    return DashboardStatsResponse(
        timestamp=now.isoformat(),
        agents=agent_infos,
        databases=databases,
    )


# ── Create Source (intervention) ────────────────────────────────────────────

@router.post("/sources", status_code=201)
async def create_source(req: CreateSourceRequest):
    source = await _db.create_source(
        title=req.title,
        url=req.url,
        source_type=req.source_type,
        domain=req.domain,
        project_ref=req.project_ref,
        status="Collected",
    )
    await _activity_logger.log(
        actor="human",
        action_type="Create",
        target_db="Sources",
        description=f"手动添加素材: {req.title}",
        target_record=str(source.id),
    )
    return {"id": source.id, "title": source.title, "status": source.status}


# ── Update Task (intervention) ──────────────────────────────────────────────

@router.patch("/tasks/{task_id}")
async def update_task(task_id: int, req: UpdateTaskRequest):
    task = await _db.get_task(task_id)
    if not task:
        raise HTTPException(404, f"Task {task_id} not found")

    fields: dict = {}
    if req.status is not None:
        fields["status"] = req.status
    if req.review_needed is not None:
        fields["review_needed"] = req.review_needed

    if not fields:
        raise HTTPException(400, "No fields to update")

    updated = await _db.update_task(task_id, **fields)
    await _activity_logger.log(
        actor="human",
        action_type="Update",
        target_db="Agent Tasks",
        description=f"手动更新任务 #{task_id}",
        target_record=str(task_id),
        before=task.status,
        after=fields.get("status", task.status),
        needs_review=True,
    )
    return {"id": updated.id, "name": updated.name, "status": updated.status, "review_needed": updated.review_needed}


# ── Explorer: helpers ────────────────────────────────────────────────────────

def _dt(val) -> str:
    """Convert datetime to ISO string, or empty string if None."""
    return val.isoformat() if val else ""


# ── Explorer: Sources ────────────────────────────────────────────────────────

@router.get("/sources/list", response_model=PaginatedResponse)
async def browse_sources(
    status: str | None = None,
    domain: str | None = None,
    project_ref: int | None = None,
    limit: int = 20,
    offset: int = 0,
):
    filters: dict = {}
    if status:
        filters["status"] = status
    if domain:
        filters["domain"] = domain
    if project_ref is not None:
        filters["project_ref"] = project_ref

    total = await _db._count(Source, filters)
    items = await _db.list_sources(**filters, _limit=limit, _offset=offset)
    return PaginatedResponse(
        items=[
            SourceResponse(
                id=s.id, title=s.title, source_type=s.source_type, status=s.status,
                priority=s.priority, domain=s.domain, url=s.url,
                project_ref=s.project_ref, review_needed=s.review_needed,
                created_at=_dt(s.created_at),
            ).model_dump()
            for s in items
        ],
        total=total, limit=limit, offset=offset,
    )


@router.get("/sources/{source_id}", response_model=SourceDetailResponse)
async def get_source(source_id: int):
    s = await _db.get_source(source_id)
    if not s:
        raise HTTPException(404, f"Source {source_id} not found")
    return SourceDetailResponse(
        id=s.id, title=s.title, source_type=s.source_type, status=s.status,
        priority=s.priority, domain=s.domain, url=s.url,
        project_ref=s.project_ref, review_needed=s.review_needed,
        created_at=_dt(s.created_at), authors=s.authors, year=s.year,
        output_type=s.output_type, extracted_summary=s.extracted_summary,
        key_questions=s.key_questions, why_it_matters=s.why_it_matters,
        assigned_agent=s.assigned_agent, updated_at=_dt(s.updated_at),
    )


# ── Explorer: Wiki Cards ─────────────────────────────────────────────────────

@router.get("/wiki-cards", response_model=PaginatedResponse)
async def browse_wiki_cards(
    type: str | None = None,
    domain: str | None = None,
    maturity: str | None = None,
    project_ref: int | None = None,
    limit: int = 20,
    offset: int = 0,
):
    filters: dict = {}
    if type:
        filters["type"] = type
    if domain:
        filters["domain"] = domain
    if maturity:
        filters["maturity"] = maturity
    if project_ref is not None:
        filters["project_ref"] = project_ref

    total = await _db._count(WikiCard, filters)
    items = await _db.list_wiki_cards(**filters, _limit=limit, _offset=offset)
    return PaginatedResponse(
        items=[
            WikiCardResponse(
                id=w.id, concept=w.concept, type=w.type, domain=w.domain,
                maturity=w.maturity, project_ref=w.project_ref,
                needs_review=w.needs_review, created_at=_dt(w.created_at),
            ).model_dump()
            for w in items
        ],
        total=total, limit=limit, offset=offset,
    )


@router.get("/wiki-cards/{card_id}", response_model=WikiCardDetailResponse)
async def get_wiki_card(card_id: int):
    w = await _db.get_wiki_card(card_id)
    if not w:
        raise HTTPException(404, f"WikiCard {card_id} not found")
    return WikiCardDetailResponse(
        id=w.id, concept=w.concept, type=w.type, domain=w.domain,
        maturity=w.maturity, project_ref=w.project_ref,
        needs_review=w.needs_review, created_at=_dt(w.created_at),
        definition=w.definition, explanation=w.explanation,
        key_points=w.key_points, example=w.example,
        reading_ref=w.reading_ref, assigned_agent=w.assigned_agent,
        updated_at=_dt(w.updated_at),
    )


# ── Explorer: Outputs ────────────────────────────────────────────────────────

@router.get("/outputs", response_model=PaginatedResponse)
async def browse_outputs(
    status: str | None = None,
    type: str | None = None,
    project_ref: int | None = None,
    limit: int = 20,
    offset: int = 0,
):
    filters: dict = {}
    if status:
        filters["status"] = status
    if type:
        filters["type"] = type
    if project_ref is not None:
        filters["project_ref"] = project_ref

    total = await _db._count(Output, filters)
    items = await _db.list_outputs(**filters, _limit=limit, _offset=offset)
    return PaginatedResponse(
        items=[
            OutputResponse(
                id=o.id, name=o.name, type=o.type, status=o.status,
                domain=o.domain, project_ref=o.project_ref,
                word_count=o.word_count, review_needed=o.review_needed,
                created_at=_dt(o.created_at),
            ).model_dump()
            for o in items
        ],
        total=total, limit=limit, offset=offset,
    )


@router.get("/outputs/{output_id}", response_model=OutputDetailResponse)
async def get_output(output_id: int):
    o = await _db.get_output(output_id)
    if not o:
        raise HTTPException(404, f"Output {output_id} not found")
    return OutputDetailResponse(
        id=o.id, name=o.name, type=o.type, status=o.status,
        domain=o.domain, project_ref=o.project_ref,
        word_count=o.word_count, review_needed=o.review_needed,
        created_at=_dt(o.created_at), content=o.content,
        ai_notes=o.ai_notes, assigned_agent=o.assigned_agent,
        updated_at=_dt(o.updated_at),
    )


# ── Explorer: Projects detail ────────────────────────────────────────────────

@router.get("/projects/{project_id}", response_model=ProjectDetailResponse)
async def get_project(project_id: int):
    p = await _db.get_project(project_id)
    if not p:
        raise HTTPException(404, f"Project {project_id} not found")
    return ProjectDetailResponse(
        id=p.id, name=p.name, status=p.status, domain=p.domain,
        priority=p.priority, output_type=p.output_type,
        research_questions=p.research_questions, scope=p.scope,
        deadline=p.deadline, assigned_agent=p.assigned_agent,
        ai_notes=p.ai_notes, review_needed=p.review_needed,
        created_at=_dt(p.created_at), updated_at=_dt(p.updated_at),
    )


# ── Explorer: Tasks browse ───────────────────────────────────────────────────

@router.get("/tasks/browse", response_model=PaginatedResponse)
async def browse_tasks(
    status: str | None = None,
    agent: str | None = None,
    type: str | None = None,
    project_ref: int | None = None,
    limit: int = 20,
    offset: int = 0,
):
    filters: dict = {}
    if status:
        filters["status"] = status
    if agent:
        filters["assigned_agent"] = agent
    if type:
        filters["type"] = type
    if project_ref is not None:
        filters["project_ref"] = project_ref

    total = await _db._count(AgentTask, filters)
    items = await _db.list_tasks(**filters, _limit=limit, _offset=offset)
    return PaginatedResponse(
        items=[
            TaskDetailResponse(
                id=t.id, name=t.name, status=t.status, type=t.type,
                assigned_agent=t.assigned_agent, project_ref=t.project_ref,
                priority=t.priority, depends_on=t.depends_on, message=t.message,
                source_ref=t.source_ref, ai_notes=t.ai_notes,
                retry_count=t.retry_count, review_needed=t.review_needed,
                created_at=_dt(t.created_at), updated_at=_dt(t.updated_at),
            ).model_dump()
            for t in items
        ],
        total=total, limit=limit, offset=offset,
    )


# ── Explorer: Logs ────────────────────────────────────────────────────────────

@router.get("/logs", response_model=PaginatedResponse)
async def browse_logs(
    actor: str | None = None,
    action_type: str | None = None,
    target_db: str | None = None,
    limit: int = 50,
    offset: int = 0,
):
    filters: dict = {}
    if actor:
        filters["actor"] = actor
    if action_type:
        filters["action_type"] = action_type
    if target_db:
        filters["target_db"] = target_db

    total = await _db._count(ActivityLog, filters)
    items = await _db.list_logs(**filters, _limit=limit, _offset=offset)
    return PaginatedResponse(
        items=[
            LogResponse(
                id=entry.id, title=entry.title, actor=entry.actor,
                action_type=entry.action_type, target_db=entry.target_db,
                target_record=entry.target_record, before=entry.before,
                after=entry.after, notes=entry.notes, needs_review=entry.needs_review,
                created_at=_dt(entry.created_at),
            ).model_dump()
            for entry in items
        ],
        total=total, limit=limit, offset=offset,
    )
