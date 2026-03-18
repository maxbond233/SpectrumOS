"""Entry point — starts the scheduler + FastAPI server concurrently."""

from __future__ import annotations

import asyncio
import logging
import os

import uvicorn

from spectrum.config import load_settings, setup_logging
from spectrum.db.activity_log import ActivityLogger
from spectrum.db.engine import close_engine, create_tables, init_engine
from spectrum.db.operations import DatabaseOps
from spectrum.llm.client import LLMClient
from spectrum.orchestrator.event_bus import EventBus
from spectrum.orchestrator.scheduler import Scheduler
from spectrum.tools.web_search import WebSearchTool

# Agent imports
from spectrum.agents.prism import PrismAgent
from spectrum.agents.focus import FocusAgent
from spectrum.agents.dispersion import DispersionAgent
from spectrum.agents.diffraction import DiffractionAgent

logger = logging.getLogger(__name__)


def build_agents(
    db: DatabaseOps,
    llm: LLMClient,
    activity_logger: ActivityLogger,
    search_tool: WebSearchTool,
    enabled: list[str],
) -> dict:
    """Instantiate enabled agents."""
    registry = {}
    factories = {
        "prism": lambda: PrismAgent(db=db, llm=llm, activity_logger=activity_logger),
        "focus": lambda: FocusAgent(
            db=db, llm=llm, activity_logger=activity_logger, search_tool=search_tool
        ),
        "dispersion": lambda: DispersionAgent(db=db, llm=llm, activity_logger=activity_logger),
        "diffraction": lambda: DiffractionAgent(db=db, llm=llm, activity_logger=activity_logger),
    }
    for name in enabled:
        if name in factories:
            registry[name] = factories[name]()
            logger.info("Agent enabled: %s", name)
    return registry


async def run() -> None:
    """Main async entry: init DB, build agents, start scheduler + API."""
    setup_logging()
    settings = load_settings()

    # Ensure LLM env vars are available to os.environ for provider initialization
    # pydantic-settings reads .env into Settings fields but doesn't export to os.environ
    _env_exports = {
        "CLAUDE_API_KEY": settings.claude_api_key,
        "CLAUDE_BASE_URL": settings.claude_base_url,
        "DEEPSEEK_API_KEY": settings.deepseek_api_key,
        "DEEPSEEK_BASE_URL": settings.deepseek_base_url,
        "TAVILY_API_KEY": settings.tavily_api_key,
    }
    for key, val in _env_exports.items():
        if val and not os.environ.get(key):
            os.environ[key] = val

    # Database
    init_engine(settings.database)
    await create_tables()
    logger.info("Database initialized")

    # Auto-rebuild FTS index if empty
    if settings.knowledge.fts_rebuild_on_startup:
        from spectrum.db.fts import fts_is_empty, rebuild_fts_index
        if await fts_is_empty():
            count = await rebuild_fts_index()
            logger.info("FTS index auto-rebuilt: %d entries", count)

    db = DatabaseOps()
    activity_logger = ActivityLogger(db)

    # LLM
    llm = LLMClient(settings.llm)

    # Search tool
    search_tool = WebSearchTool(settings.search)

    # Agents
    agents = build_agents(db, llm, activity_logger, search_tool, settings.agents.enabled)

    # Event bus
    event_bus = EventBus()

    # Scheduler
    scheduler = Scheduler(
        agents=agents,
        db=db,
        event_bus=event_bus,
        tick_interval=settings.scheduler.tick_interval,
        max_concurrent=settings.scheduler.max_concurrent_agents,
    )

    # FastAPI — import here to avoid circular deps
    from spectrum.api.app import create_app

    app = create_app(scheduler=scheduler, db=db, activity_logger=activity_logger, llm_client=llm)

    # Run scheduler + API concurrently
    api_config = uvicorn.Config(
        app,
        host=settings.api.host,
        port=settings.api.port,
        log_level="info",
    )
    api_server = uvicorn.Server(api_config)

    logger.info("Starting Spectrum OS on port %d", settings.api.port)

    try:
        await asyncio.gather(
            scheduler.start(),
            api_server.serve(),
        )
    finally:
        await scheduler.stop()
        await close_engine()


def main() -> None:
    """Sync entry point."""
    asyncio.run(run())


if __name__ == "__main__":
    main()
