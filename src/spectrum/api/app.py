"""FastAPI application factory."""

from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse

from spectrum._version import __version__
from spectrum.api import routes
from spectrum.db.activity_log import ActivityLogger
from spectrum.db.operations import DatabaseOps
from spectrum.llm.client import LLMClient
from spectrum.orchestrator.scheduler import Scheduler

DASHBOARD_HTML = Path(__file__).resolve().parent.parent / "dashboard" / "dashboard.html"
EXPLORER_HTML = Path(__file__).resolve().parent.parent / "dashboard" / "explorer.html"


def create_app(
    scheduler: Scheduler,
    db: DatabaseOps,
    activity_logger: ActivityLogger,
    llm_client: LLMClient | None = None,
) -> FastAPI:
    app = FastAPI(
        title="光谱 OS Agent API",
        version=__version__,
        description="Multi-agent knowledge pipeline control plane",
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # Wire dependencies into routes
    routes.configure(scheduler, db, activity_logger, llm_client=llm_client)
    app.include_router(routes.router, prefix="/api")

    @app.get("/")
    async def serve_dashboard():
        return FileResponse(DASHBOARD_HTML, media_type="text/html")

    @app.get("/explorer")
    async def serve_explorer():
        return FileResponse(EXPLORER_HTML, media_type="text/html")

    return app
