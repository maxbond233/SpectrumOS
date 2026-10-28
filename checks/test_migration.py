import os
from pathlib import Path
from uuid import uuid4

import httpx
import psycopg
from alembic import command
from alembic.config import Config
from psycopg import sql
from sqlalchemy import MetaData, create_engine, select

from spectrum.db.migrate_legacy import TABLES, migrate_sqlite
from spectrum.db.models import Base
from spectrum.db.runtime import engine
from spectrum.runtime_config import runtime_settings


def test_migrate_actual_project_records():
    settings = runtime_settings()
    token = settings.api_token.get_secret_value()
    headers = {"Authorization": "Bearer " + token} if token else {}
    with httpx.Client(base_url=f"http://127.0.0.1:{settings.port}/api", timeout=30,
                      headers=headers, trust_env=False) as client:
        response = client.post("/projects", json={
            "name": "SpectrumOS v0.5.0 迁移核验",
            "domain": "软件架构核验",
            "research_questions": "当前业务记录经过 SQLite 导出和 PostgreSQL 导入后是否一致？",
            "scope": "本轮实际写入的课题和审计记录",
        })
        assert response.status_code == 201, response.text
    original_url = settings.database_url
    original_environment = os.environ.get("SPECTRUM_DATABASE_URL")
    database_name = "spectrum_migration_" + uuid4().hex[:12]
    target_url = original_url.rsplit("/", 1)[0] + "/" + database_name
    snapshot = Path(".work/migration-checks") / (database_name + ".db")
    snapshot.parent.mkdir(parents=True, exist_ok=True)
    sqlite = create_engine("sqlite:///" + str(snapshot))
    metadata = MetaData()
    for name in TABLES:
        Base.metadata.tables[name].to_metadata(metadata)
    metadata.create_all(sqlite)
    counts = {}
    with engine().connect() as source, sqlite.begin() as target:
        for name in TABLES:
            rows = source.execute(select(Base.metadata.tables[name])).mappings().all()
            counts[name] = len(rows)
            if rows:
                target.execute(metadata.tables[name].insert(), [dict(row) for row in rows])
    sqlite.dispose()
    assert counts["research_projects"] > 0
    with psycopg.connect(settings.postgres_dsn, autocommit=True) as connection:
        connection.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(database_name)))
    engine().dispose()
    engine.cache_clear()
    os.environ["SPECTRUM_DATABASE_URL"] = target_url
    runtime_settings.cache_clear()
    try:
        command.upgrade(Config("alembic.ini"), "head")
        assert migrate_sqlite(snapshot) == counts
        with engine().connect() as migrated, create_engine(original_url).connect() as source:
            for name in TABLES:
                if name == "activity_log":
                    continue
                table = Base.metadata.tables[name]
                assert migrated.execute(select(table).order_by(table.c.id)).all() == source.execute(
                    select(table).order_by(table.c.id),
                ).all()
    finally:
        engine().dispose()
        engine.cache_clear()
        if original_environment is None:
            del os.environ["SPECTRUM_DATABASE_URL"]
        else:
            os.environ["SPECTRUM_DATABASE_URL"] = original_environment
        runtime_settings.cache_clear()
