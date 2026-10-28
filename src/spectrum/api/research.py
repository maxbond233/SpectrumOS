import asyncio
import hmac
import json
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI, Header, HTTPException, Query, Request
from fastapi.encoders import jsonable_encoder
from fastapi.responses import JSONResponse, PlainTextResponse, StreamingResponse
from opentelemetry import trace
from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor
from pydantic import Field
from sqlalchemy import func, select, text
from starlette.concurrency import run_in_threadpool

from spectrum._version import __version__
from spectrum.db.models import (
    ActivityLog,
    AgentTask,
    CardLink,
    CardTag,
    Output,
    ResearchProject,
    Source,
    Tag,
    WikiCard,
)
from spectrum.db.research import (
    ArtifactVersion,
    Claim,
    EvidenceLink,
    ModelCall,
    NodeExecution,
    ResearchRun,
    ReviewDecision,
    SourceChunk,
    SourceVersion,
)
from spectrum.db.runtime import audit, engine, record, session
from spectrum.orchestrator.contracts import ProjectInput, ReviewInput, RunInput, StrictModel
from spectrum.orchestrator.service import cancel_run, retry_run, review_run, start_run
from spectrum.runtime_config import runtime_settings
from spectrum.tools.knowledge import extract, ingest, public_url, search_knowledge


class Intake(StrictModel):
    project_id: int
    title: str = Field(min_length=1, max_length=500)
    url: str


class ProjectPatch(StrictModel):
    name: str | None = Field(default=None, min_length=1, max_length=500)
    research_questions: str | None = None
    scope: str | None = None
    priority: str | None = None
    status: str | None = None


class RecordPatch(StrictModel):
    status: str | None = None
    priority: str | None = None
    maturity: str | None = None
    review_needed: bool | None = None
    needs_review: bool | None = None


class TagInput(StrictModel):
    name: str = Field(min_length=1, max_length=200)
    parent_id: int | None = None
    description: str = ""


class LinkInput(StrictModel):
    to_id: int
    relation: str = Field(min_length=1, max_length=50)
    note: str = ""


class TagAssignment(StrictModel):
    tag_ids: list[int] = Field(min_length=1, max_length=20)


def authorize(authorization: str | None = Header(default=None)) -> None:
    token = runtime_settings().api_token.get_secret_value()
    if token and not hmac.compare_digest(authorization or "", "Bearer " + token):
        raise HTTPException(401, "需要有效的访问凭据")


def get_run(identifier: str) -> dict:
    with session() as db:
        run = db.get(ResearchRun, identifier)
        if run is None:
            raise HTTPException(404, "研究运行不存在")
        result = record(run)
        result["calls"] = [record(call) for call in db.scalars(select(ModelCall).where(
            ModelCall.run_id == identifier,
        ).order_by(ModelCall.id))]
        result["nodes"] = [record(node) for node in db.scalars(select(NodeExecution).where(
            NodeExecution.run_id == identifier,
        ).order_by(NodeExecution.id))]
        for node in result["nodes"]:
            node.pop("result")
        result["artifacts"] = [record(item) for item in db.scalars(select(ArtifactVersion).where(
            ArtifactVersion.run_id == identifier,
        ).order_by(ArtifactVersion.id))]
        result["reviews"] = [record(item) for item in db.scalars(select(ReviewDecision).where(
            ReviewDecision.run_id == identifier,
        ).order_by(ReviewDecision.id))]
        result["cost_usd"] = sum(call["cost_usd"] for call in result["calls"])
        return result


def create_research_app() -> FastAPI:
    settings = runtime_settings()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        if settings.host not in ("127.0.0.1", "localhost", "::1") and not settings.api_token.get_secret_value():
            raise RuntimeError("非本机监听必须配置 SPECTRUM_API_TOKEN")
        with engine().connect() as connection:
            if connection.execute(text("SELECT version_num FROM alembic_version")).scalar_one() != "0005":
                raise RuntimeError("请先执行 spectrum migrate")
        yield
        engine().dispose()

    app = FastAPI(title="光谱 OS", version=__version__, lifespan=lifespan,
                  dependencies=[Depends(authorize)])

    @app.exception_handler(ValueError)
    async def invalid_state(request: Request, exc: ValueError):
        return JSONResponse(status_code=409, content={"detail": str(exc)})

    @app.get("/api/health")
    def health():
        with session() as db:
            db.execute(text("SELECT 1"))
        return {"status": "ok", "version": __version__}

    @app.get("/api/projects")
    def projects():
        with session() as db:
            return [record(item) for item in db.scalars(select(ResearchProject).order_by(
                ResearchProject.created_at.desc(),
            ))]

    @app.post("/api/projects", status_code=201)
    def create_project(body: ProjectInput):
        with session() as db, db.begin():
            project = ResearchProject(**body.model_dump())
            db.add(project)
            db.flush()
            audit(db, "创建课题", "research_projects", str(project.id), "human")
            return record(project)

    @app.get("/api/projects/{identifier}")
    def project(identifier: int):
        with session() as db:
            item = db.get(ResearchProject, identifier)
            if item is None:
                raise HTTPException(404, "课题不存在")
            return record(item)

    @app.patch("/api/projects/{identifier}")
    def update_project(identifier: int, body: ProjectPatch):
        with session() as db, db.begin():
            item = db.get(ResearchProject, identifier)
            if item is None:
                raise HTTPException(404, "课题不存在")
            for key, value in body.model_dump(exclude_none=True).items():
                setattr(item, key, value)
            item.review_needed = True
            audit(db, "修改课题", "research_projects", str(identifier), "human")
            db.flush()
            return record(item)

    @app.post("/api/projects/{identifier}/runs", status_code=202)
    def run_project(identifier: int, body: RunInput):
        return {"id": start_run(identifier, body.budget)}

    @app.get("/api/runs")
    def runs(project_id: int | None = None):
        with session() as db:
            query = select(ResearchRun).order_by(ResearchRun.created_at.desc()).limit(100)
            if project_id is not None:
                query = query.where(ResearchRun.project_id == project_id)
            return [record(item) for item in db.scalars(query)]

    @app.get("/api/runs/{identifier}")
    def run_detail(identifier: str):
        return get_run(identifier)

    @app.post("/api/runs/{identifier}/review", status_code=202)
    def review(identifier: str, body: ReviewInput):
        review_run(identifier, body)
        return {"status": "queued"}

    @app.post("/api/runs/{identifier}/cancel")
    def cancel(identifier: str):
        cancel_run(identifier)
        return {"status": "cancelled"}

    @app.post("/api/runs/{identifier}/retry", status_code=202)
    def retry(identifier: str):
        retry_run(identifier)
        return {"status": "queued"}

    @app.get("/api/runs/{identifier}/events")
    async def events(identifier: str, request: Request):
        await run_in_threadpool(get_run, identifier)

        async def stream():
            previous = None
            while not await request.is_disconnected():
                value = await run_in_threadpool(get_run, identifier)
                content = json.dumps(jsonable_encoder(value), ensure_ascii=False)
                if content != previous:
                    yield "data: " + content + "\n\n"
                    previous = content
                else:
                    yield ": heartbeat\n\n"
                if value["status"] in ("completed", "cancelled", "failed"):
                    break
                await asyncio.sleep(2)
        return StreamingResponse(stream(), media_type="text/event-stream",
                                 headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})

    @app.get("/api/reviews")
    def reviews():
        with session() as db:
            return [record(item) for item in db.scalars(select(ResearchRun).where(
                ResearchRun.status == "waiting_review",
            ))]

    @app.post("/api/intake", status_code=201)
    def intake(body: Intake):
        public_url(body.url)
        with session() as db:
            project = db.get(ResearchProject, body.project_id)
            if project is None:
                raise HTTPException(404, "课题不存在")
            domain = project.domain
        chunks = ingest(body.title, body.url, extract(body.url), body.project_id, domain)
        return {"chunk_ids": chunks}

    @app.get("/api/search")
    def search(q: str = Query(min_length=1, max_length=2000), domain: str = ""):
        return {"results": search_knowledge(q, domain)}

    @app.get("/api/evidence/{identifier}")
    def evidence(identifier: int):
        with session() as db:
            claim = db.get(Claim, identifier)
            if claim is None:
                raise HTTPException(404, "知识主张不存在")
            links = db.execute(select(EvidenceLink, SourceChunk, SourceVersion, Source).join(
                SourceChunk, EvidenceLink.chunk_id == SourceChunk.id,
            ).join(SourceVersion, SourceChunk.version_id == SourceVersion.id).join(
                Source, SourceVersion.source_id == Source.id,
            ).where(EvidenceLink.claim_id == identifier)).all()
            return {"claim": record(claim), "evidence": [
                {"quote": link.quote, "relation": link.relation, "chunk_id": chunk.id,
                 "content": chunk.content, "version": version.digest,
                 "source": record(source)} for link, chunk, version, source in links
            ]}

    tables = {"sources": Source, "wiki-cards": WikiCard, "outputs": Output,
              "tasks": AgentTask, "logs": ActivityLog, "tags": Tag}

    def browse_table(table: str, project_ref: int | None, limit: int, offset: int) -> dict:
        model = tables[table]
        with session() as db:
            query = select(model)
            if project_ref is not None and hasattr(model, "project_ref"):
                query = query.where(model.project_ref == project_ref)
            total = db.scalar(select(func.count()).select_from(query.subquery()))
            items = db.scalars(query.order_by(model.id.desc()).limit(limit).offset(offset))
            return {"items": [record(item) for item in items], "total": total,
                    "limit": limit, "offset": offset}

    @app.get("/api/sources/list")
    def sources(project_ref: int | None = None, limit: int = Query(20, ge=1, le=100),
                offset: int = Query(0, ge=0)):
        return browse_table("sources", project_ref, limit, offset)

    @app.get("/api/outputs/{identifier}/markdown")
    def download(identifier: int):
        with session() as db:
            output = db.get(Output, identifier)
            if output is None:
                raise HTTPException(404, "产出不存在")
            return PlainTextResponse(output.content, media_type="text/markdown", headers={
                "Content-Disposition": f'attachment; filename="output-{identifier}.md"',
            })

    @app.get("/api/tags/tree")
    def tag_tree():
        with session() as db:
            tags = {tag.id: {**record(tag), "children": []} for tag in db.scalars(select(Tag))}
            roots = []
            for tag in tags.values():
                if tag["parent_id"] is None:
                    roots.append(tag)
                else:
                    tags[tag["parent_id"]]["children"].append(tag)
            return roots

    @app.post("/api/tags", status_code=201)
    def create_tag(body: TagInput):
        with session() as db, db.begin():
            level = 1
            if body.parent_id is not None:
                parent = db.get(Tag, body.parent_id)
                if parent is None or parent.level >= 3:
                    raise HTTPException(422, "父标签不存在或已经达到三层限制")
                level = parent.level + 1
            tag = Tag(**body.model_dump(), level=level)
            db.add(tag)
            db.flush()
            audit(db, "创建标签", "tags", str(tag.id), "human")
            return record(tag)

    @app.get("/api/wiki-cards/{identifier}/tags")
    def card_tags(identifier: int):
        with session() as db:
            return [record(tag) for tag in db.scalars(select(Tag).join(
                CardTag, CardTag.tag_id == Tag.id,
            ).where(CardTag.card_id == identifier))]

    @app.post("/api/wiki-cards/{identifier}/tags", status_code=201)
    def assign_tags(identifier: int, body: TagAssignment):
        with session() as db, db.begin():
            if db.get(WikiCard, identifier) is None:
                raise HTTPException(404, "知识卡不存在")
            for tag_id in set(body.tag_ids):
                if db.get(Tag, tag_id) is None:
                    raise HTTPException(422, "标签不存在")
                existing = db.scalar(select(CardTag).where(
                    CardTag.card_id == identifier, CardTag.tag_id == tag_id,
                ))
                if existing is None:
                    db.add(CardTag(card_id=identifier, tag_id=tag_id, source="human"))
            audit(db, "修改知识卡标签", "wiki_cards", str(identifier), "human")
            return {"status": "saved"}

    @app.get("/api/wiki-cards/{identifier}/links")
    def links(identifier: int):
        with session() as db:
            outgoing = db.scalars(select(CardLink).where(CardLink.from_id == identifier))
            incoming = db.scalars(select(CardLink).where(CardLink.to_id == identifier))
            return {"outgoing": [record(link) for link in outgoing],
                    "incoming": [record(link) for link in incoming]}

    @app.post("/api/wiki-cards/{identifier}/links", status_code=201)
    def add_link(identifier: int, body: LinkInput):
        with session() as db, db.begin():
            if identifier == body.to_id or any(db.get(WikiCard, key) is None for key in (identifier, body.to_id)):
                raise HTTPException(422, "关联知识卡必须存在，且不能指向自身")
            existing = db.scalar(select(CardLink).where(
                CardLink.from_id == identifier, CardLink.to_id == body.to_id,
                CardLink.relation == body.relation,
            ))
            if existing:
                return record(existing)
            link = CardLink(from_id=identifier, **body.model_dump(), source="human")
            db.add(link)
            db.flush()
            audit(db, "关联知识卡", "card_links", str(link.id), "human")
            return record(link)

    @app.patch("/api/{table}/{identifier}")
    def patch_record(table: str, identifier: int, body: RecordPatch):
        allowed = {
            "sources": {"status", "priority", "review_needed"},
            "wiki-cards": {"maturity", "needs_review"},
            "outputs": {"status", "review_needed"},
        }
        fields = body.model_dump(exclude_none=True)
        if table not in allowed or not fields.keys() <= allowed[table]:
            raise HTTPException(422, "该数据类型不支持这些修改字段")
        with session() as db, db.begin():
            item = db.get(tables[table], identifier)
            if item is None:
                raise HTTPException(404, "记录不存在")
            for key, value in fields.items():
                setattr(item, key, value)
            if "status" in fields or "priority" in fields:
                item.review_needed = True
            audit(db, "修改记录", table, str(identifier), "human")
            db.flush()
            return record(item)

    @app.get("/api/{table}")
    def browse(table: str, project_ref: int | None = None,
               limit: int = Query(20, ge=1, le=100), offset: int = Query(0, ge=0)):
        if table not in tables:
            raise HTTPException(404, "数据类型不存在")
        return browse_table(table, project_ref, limit, offset)

    @app.get("/api/{table}/{identifier}")
    def detail(table: str, identifier: int):
        if table not in tables:
            raise HTTPException(404, "数据类型不存在")
        with session() as db:
            item = db.get(tables[table], identifier)
            if item is None:
                raise HTTPException(404, "记录不存在")
            return record(item)

    if settings.otlp_endpoint:
        provider = TracerProvider(resource=Resource.create({"service.name": "spectrum-api"}))
        provider.add_span_processor(BatchSpanProcessor(OTLPSpanExporter(endpoint=settings.otlp_endpoint)))
        trace.set_tracer_provider(provider)
    FastAPIInstrumentor.instrument_app(app)
    return app
