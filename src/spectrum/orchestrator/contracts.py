from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Budget(StrictModel):
    max_calls: int = Field(default=20, ge=1, le=100)
    max_queries: int = Field(default=6, ge=1, le=30)
    max_sources: int = Field(default=12, ge=1, le=50)
    max_rounds: int = Field(default=2, ge=1, le=5)
    max_output_tokens: int = Field(default=4096, ge=512, le=16000)
    max_cost_usd: float = Field(default=5.0, gt=0, le=100)
    max_seconds: int = Field(default=1800, ge=60, le=7200)


class ProjectInput(StrictModel):
    name: str = Field(min_length=1, max_length=500)
    domain: str = Field(default="", max_length=200)
    research_questions: str = Field(min_length=1, max_length=20000)
    scope: str = Field(default="", max_length=10000)
    output_type: str = "综述"
    priority: Literal["P1", "P2", "P3"] = "P2"


class RunInput(StrictModel):
    budget: Budget = Field(default_factory=Budget)


class ReviewInput(StrictModel):
    revision: int = Field(ge=0)
    decision: Literal["approve", "reject"]
    content: str = Field(min_length=1, max_length=200000)
    feedback: str = Field(default="", max_length=20000)


class Brief(StrictModel):
    content: str = Field(min_length=20)
    queries: list[str] = Field(min_length=1, max_length=6)


class Coverage(StrictModel):
    sufficient: bool
    gaps: list[str]
    queries: list[str] = Field(max_length=6)


class Evidence(StrictModel):
    chunk_id: int
    quote: str = Field(min_length=5)
    relation: Literal["supports", "contradicts"] = "supports"


class KnowledgeClaim(StrictModel):
    statement: str = Field(min_length=5)
    evidence: list[Evidence] = Field(min_length=1)


class KnowledgeCard(StrictModel):
    concept: str
    definition: str
    explanation: str
    claims: list[KnowledgeClaim] = Field(min_length=1)
    tags: list[str] = Field(max_length=5)


class Knowledge(StrictModel):
    cards: list[KnowledgeCard] = Field(min_length=1, max_length=12)


class Outline(StrictModel):
    title: str
    sections: list[str] = Field(min_length=1, max_length=8)


class Paragraph(StrictModel):
    text: str = Field(min_length=1)
    claim_ids: list[int] = Field(min_length=1)


class Section(StrictModel):
    paragraphs: list[Paragraph] = Field(min_length=1)


class Critique(StrictModel):
    approved: bool
    issues: list[str]
