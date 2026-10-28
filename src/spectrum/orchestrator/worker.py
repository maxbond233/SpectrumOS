from contextlib import contextmanager
from datetime import timedelta
from threading import Event, Thread

import psycopg
from celery import Celery, Task
from langgraph.checkpoint.postgres import PostgresSaver
from langgraph.types import Command
from sqlalchemy import or_, select

from spectrum._version import __version__
from spectrum.db.models import ResearchProject
from spectrum.db.research import Outbox, ResearchRun, ReviewDecision, now
from spectrum.db.runtime import audit, session
from spectrum.orchestrator.workflow import build_graph
from spectrum.runtime_config import runtime_settings

settings = runtime_settings()
celery_app = Celery("spectrum", broker=settings.redis_url)
celery_app.conf.update(
    task_serializer="json", accept_content=["json"], task_acks_late=True,
    task_reject_on_worker_lost=True, worker_prefetch_multiplier=1,
    broker_connection_retry_on_startup=False,
    task_time_limit=settings.execution_timeout,
    beat_schedule={"dispatch-outbox": {"task": "spectrum.dispatch", "schedule": 5.0}},
    timezone="UTC", enable_utc=True,
)


class ResearchTask(Task):
    def on_failure(self, exc, task_id, args, kwargs, einfo) -> None:
        event_id = args[0]
        with session() as db, db.begin():
            event = db.get(Outbox, event_id)
            run = db.scalar(select(ResearchRun).where(
                ResearchRun.id == event.run_id,
            ).with_for_update())
            if run.status != "cancelled":
                run.status = "failed"
                run.error = f"{type(exc).__name__}: 执行失败，请查看调用记录与工作进程日志"
                if isinstance(exc, (ValueError, RuntimeError)):
                    run.error = f"{type(exc).__name__}: {str(exc)[:500]}"
            if run.started_at:
                run.elapsed_seconds += (now() - run.started_at).total_seconds()
                run.started_at = None
            run.updated_at, event.status = now(), "failed"
            project = db.get(ResearchProject, run.project_id)
            project.status, project.review_needed = "待审核", True
            audit(db, "研究执行失败", "research_runs", run.id)


@contextmanager
def heartbeat(run_id: str):
    stopped = Event()

    def update() -> None:
        while not stopped.wait(10):
            with session() as db, db.begin():
                run = db.get(ResearchRun, run_id)
                run.heartbeat_at = now()

    thread = Thread(target=update, daemon=True)
    thread.start()
    try:
        yield
    finally:
        stopped.set()
        thread.join(timeout=15)


@celery_app.task(name="spectrum.dispatch")
def dispatch() -> int:
    with session() as db, db.begin():
        events = db.scalars(select(Outbox).where(or_(
            Outbox.status == "pending",
            (Outbox.status == "sent") & (Outbox.delivered_at < now() - timedelta(seconds=60)),
        )).order_by(Outbox.created_at).limit(20).with_for_update(skip_locked=True)).all()
        for event in events:
            execute.apply_async(args=[event.id], task_id=event.id)
            event.status, event.delivered_at = "sent", now()
        return len(events)


@celery_app.task(name="spectrum.execute", base=ResearchTask)
def execute(event_id: str) -> None:
    with session() as db:
        event = db.get(Outbox, event_id)
        if event is None or event.status in ("done", "failed"):
            return
        run_id = event.run_id
    # 会话级锁覆盖一次完整执行；连接释放后失效，工作进程终止不会留下永久锁。
    with psycopg.connect(settings.postgres_dsn, autocommit=True) as connection:
        locked = connection.execute("SELECT pg_try_advisory_lock(hashtext(%s))", (run_id,)).fetchone()[0]
        if not locked:
            return
        with session() as db, db.begin():
            run = db.scalar(select(ResearchRun).where(ResearchRun.id == run_id).with_for_update())
            event = db.get(Outbox, event_id)
            if event.status in ("done", "failed"):
                return
            if run.status in ("cancelled", "completed", "waiting_review", "failed"):
                event.status = "done"
                return
            if run.config["version"] != __version__:
                raise RuntimeError("工作流版本不匹配，禁止跨版本恢复")
            if run.started_at:
                run.elapsed_seconds += ((run.heartbeat_at or now()) - run.started_at).total_seconds()
            run.status, run.started_at, run.heartbeat_at = "running", now(), now()
            initial = {"run_id": run.id, "project": run.input_snapshot}
        with PostgresSaver.from_conn_string(settings.postgres_dsn) as saver, heartbeat(run_id):
            graph = build_graph(saver)
            config = {"configurable": {"thread_id": run_id}, "recursion_limit": 80}
            snapshot = graph.get_state(config)
            should_invoke = True
            if snapshot.interrupts:
                stage = snapshot.interrupts[0].value["stage"]
                with session() as db:
                    decision = db.scalar(select(ReviewDecision).where(
                        ReviewDecision.run_id == run_id, ReviewDecision.stage == stage,
                    ).order_by(ReviewDecision.revision.desc()))
                    should_invoke = decision is not None
                    invocation = Command(resume={
                        "decision": decision.decision, "content": decision.content,
                        "feedback": decision.feedback,
                    }) if decision else None
            elif snapshot.values:
                invocation = None
            else:
                invocation = initial
            if should_invoke:
                graph.invoke(invocation, config)
            snapshot = graph.get_state(config)
        with session() as db, db.begin():
            run = db.scalar(select(ResearchRun).where(ResearchRun.id == run_id).with_for_update())
            event = db.get(Outbox, event_id)
            if run.status == "cancelled":
                event.status = "done"
                return
            if snapshot.interrupts:
                run.status, run.pending_review = "waiting_review", snapshot.interrupts[0].value
                run.revision += 1
            else:
                run.status = "completed" if snapshot.values.get("output_id") else "cancelled"
                run.pending_review = None
            run.updated_at, run.heartbeat_at = now(), now()
            run.elapsed_seconds += (now() - run.started_at).total_seconds()
            run.started_at = None
            event.status = "done"
            project = db.get(ResearchProject, run.project_id)
            project.status = "完成" if run.status == "completed" else "待审核"
            project.review_needed = run.status != "completed"
            audit(db, "更新研究状态", "research_runs", run_id)
