"""Typer CLI — run, trigger, status, create-project, logs, reindex."""

from __future__ import annotations

import asyncio
import os
from typing import Optional

import typer

app = typer.Typer(name="spectrum", help="光谱 OS — Multi-agent knowledge pipeline")


@app.command()
def run():
    """Start the scheduler + API server."""
    from spectrum.main import main as run_main
    run_main()


@app.command()
def trigger(agent: str = typer.Argument(..., help="Agent name: prism/focus/dispersion/diffraction")):
    """Manually trigger a single agent tick."""
    async def _trigger():
        from spectrum.config import load_settings, setup_logging
        from spectrum.db.engine import init_engine, create_tables, close_engine
        from spectrum.db.operations import DatabaseOps
        from spectrum.db.activity_log import ActivityLogger
        from spectrum.llm.client import LLMClient
        from spectrum.tools.web_search import WebSearchTool
        from spectrum.orchestrator.event_bus import EventBus
        from spectrum.orchestrator.scheduler import Scheduler
        from spectrum.main import build_agents

        setup_logging()
        settings = load_settings()

        # Export .env vars to os.environ for provider initialization
        for key, val in {
            "CLAUDE_API_KEY": settings.claude_api_key,
            "CLAUDE_BASE_URL": settings.claude_base_url,
            "DEEPSEEK_API_KEY": settings.deepseek_api_key,
            "DEEPSEEK_BASE_URL": settings.deepseek_base_url,
            "TAVILY_API_KEY": settings.tavily_api_key,
            "SERPAPI_API_KEY": settings.serpapi_api_key,
        }.items():
            if val and not os.environ.get(key):
                os.environ[key] = val

        init_engine(settings.database)
        await create_tables()

        db = DatabaseOps()
        al = ActivityLogger(db)
        llm = LLMClient(settings.llm)
        search = WebSearchTool(settings.search)
        agents = build_agents(db, llm, al, search, settings.agents.enabled)
        bus = EventBus()
        scheduler = Scheduler(agents=agents, db=db, event_bus=bus)

        try:
            events = await scheduler.trigger_agent(agent)
            if events:
                typer.echo(f"Events: {events}")
            else:
                typer.echo("No events produced.")
        finally:
            await close_engine()

    asyncio.run(_trigger())


@app.command()
def status():
    """Show system status: projects, tasks, counts."""
    async def _status():
        from spectrum.config import load_settings
        from spectrum.db.engine import init_engine, create_tables, close_engine
        from spectrum.db.operations import DatabaseOps

        settings = load_settings()
        init_engine(settings.database)
        await create_tables()
        db = DatabaseOps()

        projects = await db.list_projects()
        tasks = await db.list_tasks()
        sources = await db.list_sources()
        wiki_cards = await db.list_wiki_cards()
        outputs = await db.list_outputs()

        typer.echo("=== 光谱 OS Status ===")
        typer.echo(f"Projects:   {len(projects)}")
        for p in projects:
            typer.echo(f"  [{p.status}] {p.name} ({p.priority})")

        typer.echo(f"\nTasks:      {len(tasks)}")
        status_counts: dict[str, int] = {}
        for t in tasks:
            status_counts[t.status] = status_counts.get(t.status, 0) + 1
        for s, c in sorted(status_counts.items()):
            typer.echo(f"  {s}: {c}")

        typer.echo(f"\nSources:    {len(sources)}")
        typer.echo(f"Wiki Cards: {len(wiki_cards)}")
        typer.echo(f"Outputs:    {len(outputs)}")

        await close_engine()

    asyncio.run(_status())


@app.command("create-project")
def create_project(
    name: str = typer.Argument(..., help="Project name"),
    domain: str = typer.Option("", help="Domain"),
    questions: str = typer.Option("", help="Research questions"),
    output_type: str = typer.Option("综述", help="Output type"),
    priority: str = typer.Option("P2", help="Priority: P1/P2/P3"),
):
    """Create a new research project."""
    async def _create():
        from spectrum.config import load_settings, setup_logging
        from spectrum.db.engine import init_engine, create_tables, close_engine
        from spectrum.db.operations import DatabaseOps
        from spectrum.db.activity_log import ActivityLogger

        setup_logging()
        settings = load_settings()
        init_engine(settings.database)
        await create_tables()
        db = DatabaseOps()
        al = ActivityLogger(db)

        project = await db.create_project(
            name=name,
            domain=domain,
            research_questions=questions,
            output_type=output_type,
            priority=priority,
        )
        await al.log(
            actor="cli",
            action_type="Create",
            target_db="Research Projects",
            description=f"CLI 创建课题: {name}",
            target_record=str(project.id),
        )
        typer.echo(f"Created project #{project.id}: {name}")
        await close_engine()

    asyncio.run(_create())


@app.command()
def logs(limit: int = typer.Option(20, help="Number of recent logs")):
    """Show recent activity logs."""
    async def _logs():
        from spectrum.config import load_settings
        from spectrum.db.engine import init_engine, create_tables, close_engine
        from spectrum.db.operations import DatabaseOps

        settings = load_settings()
        init_engine(settings.database)
        await create_tables()
        db = DatabaseOps()

        entries = await db.list_logs()
        for entry in entries[:limit]:
            ts = entry.created_at.strftime("%m-%d %H:%M") if entry.created_at else "?"
            review = " ⚠️" if entry.needs_review else ""
            typer.echo(f"[{ts}] {entry.title}{review}")

        await close_engine()

    asyncio.run(_logs())


@app.command()
def reindex():
    """Rebuild the FTS5 full-text search index."""
    async def _reindex():
        from spectrum.config import load_settings, setup_logging
        from spectrum.db.engine import init_engine, create_tables, close_engine
        from spectrum.db.fts import rebuild_fts_index

        setup_logging()
        settings = load_settings()
        init_engine(settings.database)
        await create_tables()

        count = await rebuild_fts_index()
        typer.echo(f"FTS index rebuilt: {count} entries indexed.")

        await close_engine()

    asyncio.run(_reindex())


if __name__ == "__main__":
    app()
