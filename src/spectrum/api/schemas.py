"""Request/response schemas for the API."""

from __future__ import annotations

from pydantic import BaseModel

from spectrum._version import __version__


# ── Requests ─────────────────────────────────────────────────────────────────

class TriggerAgentRequest(BaseModel):
    agent: str


class CreateProjectRequest(BaseModel):
    name: str
    domain: str = ""
    research_questions: str = ""
    scope: str = ""
    output_type: str = "综述"
    priority: str = "P2"


# ── Responses ────────────────────────────────────────────────────────────────

class HealthResponse(BaseModel):
    status: str = "ok"
    version: str = __version__
    agents: list[str] = []


class TriggerResponse(BaseModel):
    agent: str
    events: list[str]


class ProjectResponse(BaseModel):
    id: int
    name: str
    status: str
    domain: str
    priority: str
    output_type: str


class TaskResponse(BaseModel):
    id: int
    name: str
    status: str
    type: str
    assigned_agent: str
    project_ref: int | None


class StatsResponse(BaseModel):
    projects: dict[str, int]   # status → count
    tasks: dict[str, int]
    sources: int
    wiki_cards: int
    outputs: int
    logs: int


# ── Dashboard Schemas ───────────────────────────────────────────────────────

class CreateSourceRequest(BaseModel):
    title: str
    url: str = ""
    source_type: str = ""
    domain: str = ""
    project_ref: int | None = None


class UpdateTaskRequest(BaseModel):
    status: str | None = None
    review_needed: bool | None = None


class UpdateProjectRequest(BaseModel):
    status: str | None = None
    priority: str | None = None
    review_needed: bool | None = None


class UpdateSourceRequest(BaseModel):
    status: str | None = None
    priority: str | None = None
    review_needed: bool | None = None


class UpdateWikiCardRequest(BaseModel):
    maturity: str | None = None
    needs_review: bool | None = None


class UpdateOutputRequest(BaseModel):
    status: str | None = None
    review_needed: bool | None = None


class ReviewItemResponse(BaseModel):
    id: int
    table: str
    title: str
    status: str
    created_at: str
    updated_at: str


class TableStats(BaseModel):
    total: int = 0
    primary: dict[str, int] = {}    # main grouping (status/maturity/action)
    secondary: dict[str, dict[str, int]] = {}  # sub-groupings
    review_needed: int = 0
    recent: list[dict] = []


class AgentInfo(BaseModel):
    name: str
    key: str
    emoji: str
    role: str
    role_en: str
    color: str
    active: bool = False
    task_count: int = 0


class DashboardStatsResponse(BaseModel):
    timestamp: str
    agents: list[AgentInfo]
    databases: dict[str, TableStats]


# ── Pagination ────────────────────────────────────────────────────────────────

class PaginatedResponse(BaseModel):
    items: list[dict]
    total: int
    limit: int
    offset: int


# ── Source ────────────────────────────────────────────────────────────────────

class SourceResponse(BaseModel):
    id: int
    title: str
    source_type: str
    status: str
    priority: str
    domain: str
    url: str
    project_ref: int | None
    review_needed: bool
    created_at: str


class SourceDetailResponse(SourceResponse):
    authors: str
    year: str
    output_type: str
    extracted_summary: str
    key_questions: str
    why_it_matters: str
    assigned_agent: str
    updated_at: str


# ── WikiCard ──────────────────────────────────────────────────────────────────

class WikiCardResponse(BaseModel):
    id: int
    concept: str
    type: str
    domain: str
    maturity: str
    project_ref: int | None
    needs_review: bool
    created_at: str


class WikiCardDetailResponse(WikiCardResponse):
    definition: str
    explanation: str
    key_points: str
    example: str
    reading_ref: int | None
    assigned_agent: str
    updated_at: str


# ── Output ────────────────────────────────────────────────────────────────────

class OutputResponse(BaseModel):
    id: int
    name: str
    type: str
    status: str
    domain: str
    project_ref: int | None
    word_count: int | None
    review_needed: bool
    created_at: str


class OutputDetailResponse(OutputResponse):
    content: str
    ai_notes: str
    assigned_agent: str
    updated_at: str


# ── Project Detail ────────────────────────────────────────────────────────────

class ProjectDetailResponse(ProjectResponse):
    research_questions: str
    scope: str
    deadline: str
    assigned_agent: str
    ai_notes: str
    review_needed: bool
    created_at: str
    updated_at: str


# ── Task Detail ───────────────────────────────────────────────────────────────

class TaskDetailResponse(TaskResponse):
    priority: str
    depends_on: str
    message: str
    source_ref: int | None
    ai_notes: str
    retry_count: int
    review_needed: bool
    created_at: str
    updated_at: str


# ── Activity Log ──────────────────────────────────────────────────────────────

class LogResponse(BaseModel):
    id: int
    title: str
    actor: str
    action_type: str
    target_db: str
    target_record: str
    before: str
    after: str
    notes: str
    needs_review: bool
    created_at: str
