from uuid import uuid4

from sqlalchemy import select

from spectrum._version import __version__
from spectrum.db.models import ResearchProject
from spectrum.db.research import Outbox, ResearchRun, ReviewDecision, now
from spectrum.db.runtime import audit, session
from spectrum.orchestrator.contracts import Budget, ReviewInput
from spectrum.runtime_config import runtime_settings


def start_run(project_id: int, budget: Budget) -> str:
    settings = runtime_settings()
    with session() as db, db.begin():
        project = db.scalar(select(ResearchProject).where(
            ResearchProject.id == project_id,
        ).with_for_update())
        if project is None:
            raise ValueError("课题不存在")
        active = db.scalar(select(ResearchRun).where(
            ResearchRun.project_id == project_id,
            ResearchRun.status.in_(["queued", "running", "waiting_review"]),
        ))
        if active:
            raise ValueError("课题已有活动中的研究运行")
        identifier = str(uuid4())
        snapshot = {key: getattr(project, key) for key in (
            "name", "domain", "research_questions", "scope", "output_type",
        )}
        db.add(ResearchRun(
            id=identifier, project_id=project_id, input_snapshot=snapshot,
            config={"version": __version__, "budget": budget.model_dump(), "model": settings.model,
                    "input_price": settings.input_price_per_million,
                    "output_price": settings.output_price_per_million,
                    "embedding_model": settings.embedding_model},
        ))
        db.flush()
        db.add(Outbox(id=str(uuid4()), run_id=identifier))
        project.status, project.review_needed = "进行中", True
        audit(db, "启动研究", "research_runs", identifier, "human")
        return identifier


def review_run(run_id: str, decision: ReviewInput) -> None:
    with session() as db, db.begin():
        run = db.scalar(select(ResearchRun).where(ResearchRun.id == run_id).with_for_update())
        if run is None:
            raise ValueError("研究运行不存在")
        if run.status != "waiting_review" or run.revision != decision.revision:
            raise ValueError("审核版本已改变，请刷新页面")
        pending = run.pending_review
        db.add(ReviewDecision(
            run_id=run_id, revision=run.revision, stage=pending["stage"],
            decision=decision.decision, content=decision.content, feedback=decision.feedback,
        ))
        run.status, run.updated_at = "queued", now()
        run.pending_review = None
        db.add(Outbox(id=str(uuid4()), run_id=run_id, payload=decision.model_dump()))
        audit(db, "提交审核", "research_runs", run_id, "human")


def cancel_run(run_id: str) -> None:
    with session() as db, db.begin():
        run = db.scalar(select(ResearchRun).where(ResearchRun.id == run_id).with_for_update())
        if run is None or run.status not in ("queued", "running", "waiting_review"):
            raise ValueError("研究运行无法取消")
        run.status, run.updated_at = "cancelled", now()
        project = db.get(ResearchProject, run.project_id)
        project.status, project.review_needed = "待审核", True
        audit(db, "取消研究", "research_runs", run_id, "human")


def retry_run(run_id: str) -> None:
    with session() as db, db.begin():
        project_id = db.scalar(select(ResearchRun.project_id).where(ResearchRun.id == run_id))
        if project_id is None:
            raise ValueError("研究运行不存在")
        project = db.scalar(select(ResearchProject).where(
            ResearchProject.id == project_id,
        ).with_for_update())
        run = db.scalar(select(ResearchRun).where(ResearchRun.id == run_id).with_for_update())
        if run is None or run.status != "failed":
            raise ValueError("仅允许恢复已失败的研究运行")
        active = db.scalar(select(ResearchRun.id).where(
            ResearchRun.project_id == project_id,
            ResearchRun.status.in_(["queued", "running", "waiting_review"]),
        ))
        if active:
            raise ValueError("课题已有活动中的研究运行")
        run.status, run.error, run.updated_at = "queued", "", now()
        project.status, project.review_needed = "进行中", True
        db.add(Outbox(id=str(uuid4()), run_id=run_id))
        audit(db, "恢复研究", "research_runs", run_id, "human")
