from pathlib import Path

import httpx
import typer
from alembic import command
from alembic.config import Config
from langgraph.checkpoint.postgres import PostgresSaver

from spectrum.runtime_config import runtime_settings

app = typer.Typer(help="光谱 OS 研究工作台")


@app.command()
def run() -> None:
    from spectrum.main import main
    main()


@app.command()
def migrate() -> None:
    command.upgrade(Config("alembic.ini"), "head")
    with PostgresSaver.from_conn_string(runtime_settings().postgres_dsn) as saver:
        saver.setup()
    from spectrum.tools.storage import initialize_storage
    initialize_storage()
    typer.echo("数据库、检查点和对象存储初始化完成")


@app.command("import-sqlite")
def import_sqlite(path: Path) -> None:
    from spectrum.db.migrate_legacy import migrate_sqlite
    typer.echo(migrate_sqlite(path))


@app.command()
def worker() -> None:
    from spectrum.orchestrator.worker import celery_app
    celery_app.worker_main(["worker", "--loglevel=INFO", "--pool=solo"])


@app.command()
def beat() -> None:
    from spectrum.orchestrator.worker import celery_app
    Path(".work").mkdir(exist_ok=True)
    celery_app.Beat(loglevel="INFO", schedule=".work/celerybeat-schedule").run()


def request(method: str, path: str, **kwargs):
    settings = runtime_settings()
    token = settings.api_token.get_secret_value()
    headers = {"Authorization": "Bearer " + token} if token else {}
    response = httpx.request(method, f"http://127.0.0.1:{settings.port}/api/{path}",
                             headers=headers, timeout=30, trust_env=False, **kwargs)
    response.raise_for_status()
    return response.json()


@app.command()
def status() -> None:
    typer.echo(request("GET", "runs"))


@app.command("create-project")
def create_project(name: str, questions: str, domain: str = "", priority: str = "P2") -> None:
    typer.echo(request("POST", "projects", json={"name": name, "research_questions": questions,
                                                "domain": domain, "priority": priority}))


@app.command()
def trigger(project_id: int) -> None:
    typer.echo(request("POST", f"projects/{project_id}/runs", json={}))


@app.command()
def logs() -> None:
    typer.echo(request("GET", "logs"))


if __name__ == "__main__":
    app()
