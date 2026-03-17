"""SQLAlchemy ORM models for the 6 core tables.

Maps 1:1 to the original Notion databases:
  ResearchProject, Source, WikiCard, Output, AgentTask, ActivityLog
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import Boolean, DateTime, Float, Integer, String, Text, func
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class ResearchProject(Base):
    """🔬 Research Projects — 系统枢纽"""

    __tablename__ = "research_projects"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(500), nullable=False)
    status: Mapped[str] = mapped_column(String(50), default="未开始")  # 未开始/进行中/完成
    domain: Mapped[str] = mapped_column(String(200), default="")
    research_questions: Mapped[str] = mapped_column(Text, default="")
    scope: Mapped[str] = mapped_column(Text, default="")
    output_type: Mapped[str] = mapped_column(String(100), default="")  # 综述/教程/笔记/报告/论文草稿
    priority: Mapped[str] = mapped_column(String(10), default="P2")  # P1/P2/P3
    deadline: Mapped[str] = mapped_column(String(50), default="")
    assigned_agent: Mapped[str] = mapped_column(String(50), default="")
    ai_notes: Mapped[str] = mapped_column(Text, default="")
    review_needed: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now()
    )


class Source(Base):
    """📚 Sources — 素材库"""

    __tablename__ = "sources"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    title: Mapped[str] = mapped_column(String(500), nullable=False)
    source_type: Mapped[str] = mapped_column(String(100), default="")
    status: Mapped[str] = mapped_column(String(50), default="Collected")  # Collected/To Read/Reading/Processed/Archived
    priority: Mapped[str] = mapped_column(String(10), default="")
    domain: Mapped[str] = mapped_column(String(200), default="")
    url: Mapped[str] = mapped_column(String(2000), default="")
    authors: Mapped[str] = mapped_column(String(500), default="")
    year: Mapped[str] = mapped_column(String(10), default="")
    output_type: Mapped[str] = mapped_column(String(100), default="")
    extracted_summary: Mapped[str] = mapped_column(Text, default="")
    key_questions: Mapped[str] = mapped_column(Text, default="")
    why_it_matters: Mapped[str] = mapped_column(Text, default="")
    project_ref: Mapped[int | None] = mapped_column(Integer, nullable=True)  # FK to research_projects.id
    assigned_agent: Mapped[str] = mapped_column(String(50), default="")
    review_needed: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now()
    )


class WikiCard(Base):
    """🧠 Wiki — 知识卡"""

    __tablename__ = "wiki_cards"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    concept: Mapped[str] = mapped_column(String(500), nullable=False)
    type: Mapped[str] = mapped_column(String(50), default="")  # 概念/方法/工具/流程/术语/经验/人物
    domain: Mapped[str] = mapped_column(String(200), default="")
    definition: Mapped[str] = mapped_column(Text, default="")
    explanation: Mapped[str] = mapped_column(Text, default="")
    key_points: Mapped[str] = mapped_column(Text, default="")
    example: Mapped[str] = mapped_column(Text, default="")
    maturity: Mapped[str] = mapped_column(String(20), default="Seed")  # Seed/Growing/Stable
    project_ref: Mapped[int | None] = mapped_column(Integer, nullable=True)
    reading_ref: Mapped[int | None] = mapped_column(Integer, nullable=True)  # FK to sources.id
    assigned_agent: Mapped[str] = mapped_column(String(50), default="")
    needs_review: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now()
    )


class Output(Base):
    """📄 Outputs — 产出库"""

    __tablename__ = "outputs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(500), nullable=False)
    type: Mapped[str] = mapped_column(String(100), default="")  # 综述/教程/报告/笔记/论文草稿
    status: Mapped[str] = mapped_column(String(50), default="未开始")  # 未开始/进行中/完成
    project_ref: Mapped[int | None] = mapped_column(Integer, nullable=True)
    domain: Mapped[str] = mapped_column(String(200), default="")
    assigned_agent: Mapped[str] = mapped_column(String(50), default="")
    word_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    content: Mapped[str] = mapped_column(Text, default="")  # 正文内容（原 Notion 页面 body）
    ai_notes: Mapped[str] = mapped_column(Text, default="")
    review_needed: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now()
    )


class AgentTask(Base):
    """🎯 Agent Board — 代理工作台"""

    __tablename__ = "agent_tasks"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(500), nullable=False)
    status: Mapped[str] = mapped_column(String(50), default="Todo")  # Inbox/Todo/Doing/Waiting/Done/Archived
    priority: Mapped[str] = mapped_column(String(10), default="")
    type: Mapped[str] = mapped_column(String(50), default="")  # 采集/分析/沉淀/产出/协调
    assigned_agent: Mapped[str] = mapped_column(String(50), default="")
    depends_on: Mapped[str] = mapped_column(String(500), default="")  # comma-separated task IDs
    message: Mapped[str] = mapped_column(Text, default="")
    project_ref: Mapped[int | None] = mapped_column(Integer, nullable=True)
    source_ref: Mapped[int | None] = mapped_column(Integer, nullable=True)
    ai_notes: Mapped[str] = mapped_column(Text, default="")
    review_needed: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now()
    )


class ActivityLog(Base):
    """📋 Activity Log — 操作日志"""

    __tablename__ = "activity_log"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    title: Mapped[str] = mapped_column(String(500), nullable=False)  # 动作｜目标库｜说明
    actor: Mapped[str] = mapped_column(String(50), default="")
    action_type: Mapped[str] = mapped_column(String(50), default="")  # Create/Update/Summarize/...
    target_db: Mapped[str] = mapped_column(String(100), default="")
    target_record: Mapped[str] = mapped_column(String(200), default="")
    before: Mapped[str] = mapped_column(Text, default="")
    after: Mapped[str] = mapped_column(Text, default="")
    confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    needs_review: Mapped[bool] = mapped_column(Boolean, default=False)
    notes: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
