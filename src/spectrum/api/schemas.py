"""Request/response schemas for the API."""

from __future__ import annotations

from pydantic import BaseModel


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
    version: str = "0.1.0"
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
