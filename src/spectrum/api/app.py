"""FastAPI application factory."""

from __future__ import annotations

from fastapi import FastAPI

from spectrum.api import routes
from spectrum.db.activity_log import ActivityLogger
from spectrum.db.operations import DatabaseOps
from spectrum.orchestrator.scheduler import Scheduler


def create_app(
    scheduler: Scheduler,
    db: DatabaseOps,
    activity_logger: ActivityLogger,
) -> FastAPI:
    app = FastAPI(
        title="光谱 OS Agent API",
        version="0.1.0",
        description="Multi-agent knowledge pipeline control plane",
    )

    # Wire dependencies into routes
    routes.configure(scheduler, db, activity_logger)
    app.include_router(routes.router, prefix="/api")

    return app
