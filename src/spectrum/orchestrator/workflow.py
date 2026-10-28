import hashlib
import json
import os
from functools import wraps
from typing import Any, TypedDict

import httpx
from langgraph.graph import END, START, StateGraph
from langgraph.types import interrupt
from sqlalchemy import select

from spectrum.db.models import CardLink, CardTag, Output, Tag, WikiCard
from spectrum.db.research import (
    ArtifactVersion,
    Claim,
    EvidenceLink,
    NodeExecution,
    ResearchRun,
    SearchCall,
    SourceChunk,
    now,
)
from spectrum.db.runtime import audit, session
from spectrum.llm.research import check_run, generate
from spectrum.orchestrator.contracts import Brief, Coverage, Critique, Knowledge, Outline, Section
from spectrum.tools.knowledge import extract, ingest, search_knowledge
from spectrum.tools.storage import put_text


class ResearchState(TypedDict, total=False):
    run_id: str
    project: dict[str, Any]
    brief: str
    queries: list[str]
    round: int
    chunks: list[int]
    source_urls: list[str]
    coverage: dict[str, Any]
    claims: list[int]
    outline: str
    draft: str
    critique: dict[str, Any]
    decision: str
    output_id: int


def durable(name: str):
    def decorate(function):
        @wraps(function)
        def execute(state: ResearchState) -> dict:
            key = hashlib.sha256(json.dumps(state, sort_keys=True).encode()).hexdigest()
            with session() as db, db.begin():
                run = db.get(ResearchRun, state["run_id"])
                check_run(run)
                run.node, run.heartbeat_at = name, now()
                cached = db.scalar(select(NodeExecution).where(
                    NodeExecution.run_id == run.id, NodeExecution.node == name,
                    NodeExecution.key == key,
                ))
                if cached:
                    return cached.result
            result = function(state)
            with session() as db, db.begin():
                check_run(db.get(ResearchRun, state["run_id"]))
                db.add(NodeExecution(run_id=state["run_id"], node=name, key=key, result=result))
                audit(db, "完成节点", "research_runs", state["run_id"] + ":" + name)
            return result
        return execute
    return decorate


def save_artifact(state: ResearchState, kind: str, content: str, author: str,
                  citations: list[int] | None = None, output_id: int | None = None) -> None:
    key, _ = put_text(content, "artifacts/" + state["run_id"])
    with session() as db, db.begin():
        run = db.get(ResearchRun, state["run_id"])
        revision = run.revision * 2 + (1 if author == "human" else 0)
        existing = db.scalar(select(ArtifactVersion).where(
            ArtifactVersion.run_id == run.id, ArtifactVersion.kind == kind,
            ArtifactVersion.revision == revision,
        ))
        if existing is None:
            db.add(ArtifactVersion(
                run_id=run.id, kind=kind, revision=revision, content=content,
                object_key=key, author=author, citations=citations or [], output_id=output_id,
            ))
            audit(db, "保存文稿版本", "artifact_versions", run.id + ":" + kind, author)


@durable("brief")
def brief(state: ResearchState) -> dict:
    result = generate(state["run_id"], "brief", json.dumps(state["project"], ensure_ascii=False)
                      + "\n生成研究范围、必须回答的问题、证据标准和搜索词。", Brief)
    save_artifact(state, "brief", result.content, "ai")
    return {"brief": result.content, "queries": result.queries, "round": 0, "chunks": []}


def gate(stage: str, field: str):
    def review(state: ResearchState) -> dict:
        decision = interrupt({"stage": stage, "content": state[field]})
        if decision["decision"] == "reject":
            return {"decision": "reject"}
        save_artifact(state, stage, decision["content"], "human", state.get("claims", []))
        return {field: decision["content"], "decision": "approve"}
    return review


def next_after_review(destination: str):
    return lambda state: destination if state["decision"] == "approve" else END


def search_web(run_id: str, query: str) -> dict:
    with session() as db, db.begin():
        run = db.scalar(select(ResearchRun).where(ResearchRun.id == run_id).with_for_update())
        budget = check_run(run)
        calls = db.scalars(select(SearchCall).where(SearchCall.run_id == run_id)).all()
        existing = next((call for call in calls if call.query == query), None)
        if existing:
            if existing.status != "complete":
                raise RuntimeError("此前搜索请求结果未知，请核对后重新开始研究")
            return existing.response
        if len(calls) >= budget.max_queries:
            raise RuntimeError("搜索次数预算已用尽")
        db.add(SearchCall(run_id=run_id, query=query))
        audit(db, "预留搜索预算", "search_calls", run_id)
    with httpx.Client(timeout=60) as client:
        response = client.post("https://api.tavily.com/search", json={
            "api_key": os.environ["TAVILY_API_KEY"], "query": query,
            "max_results": 3, "include_raw_content": "text", "search_depth": "advanced",
        })
        response.raise_for_status()
        result = response.json()
    with session() as db, db.begin():
        call = db.scalar(select(SearchCall).where(
            SearchCall.run_id == run_id, SearchCall.query == query,
        ))
        call.response, call.status = result, "complete"
        audit(db, "保存搜索结果", "search_calls", run_id)
    return result


@durable("collect")
def collect(state: ResearchState) -> dict:
    with session() as db:
        run = db.get(ResearchRun, state["run_id"])
        budget = check_run(run)
        project_id = run.project_id
    domain = state["project"]["domain"]
    chunks = set(state.get("chunks", []))
    reused = search_knowledge(state["brief"], domain, limit=8)
    chunks.update(item["id"] for item in reused)
    queries = state["queries"]
    if state.get("round", 0) == 0:
        plan = generate(state["run_id"], "search_plan", state["brief"]
                        + "\n以已确认的简报为准，制定搜索词。", Brief)
        queries = plan.queries
    source_urls = set(state.get("source_urls", []))
    for query in queries[:max(1, budget.max_queries // budget.max_rounds)]:
        result = search_web(state["run_id"], query)
        for item in result["results"]:
            if len(source_urls) >= budget.max_sources:
                break
            url, title = item["url"], item["title"]
            if url in source_urls:
                continue
            body = item.get("raw_content")
            if not body:
                body = extract(url)
            chunks.update(ingest(title, url, body[:100000], project_id, domain))
            source_urls.add(url)
    if not chunks:
        raise RuntimeError("没有可用原文证据，研究已终止")
    return {"chunks": sorted(chunks), "round": state.get("round", 0) + 1,
            "source_urls": sorted(source_urls)}


def evidence_context(state: ResearchState) -> str:
    with session() as db:
        chunks = db.scalars(select(SourceChunk).where(SourceChunk.id.in_(state["chunks"]))).all()
        # 依据研究问题检索当前材料，限制上下文大小并保留原文定位。
        ranked = search_knowledge(state["brief"], state["project"]["domain"], limit=24)
        ranks = {item["id"]: index for index, item in enumerate(ranked)}
        chunks = sorted(chunks, key=lambda chunk: ranks.get(chunk.id, 1000))[:24]
        return json.dumps([{"chunk_id": chunk.id, "content": chunk.content} for chunk in chunks],
                          ensure_ascii=False)


@durable("coverage")
def coverage(state: ResearchState) -> dict:
    result = generate(state["run_id"], "coverage", state["brief"] + "\n"
                      + evidence_context(state) + "\n核对研究问题的覆盖度，列出证据缺口。", Coverage)
    return {"coverage": result.model_dump(), "queries": result.queries}


def coverage_route(state: ResearchState) -> str:
    with session() as db:
        budget = check_run(db.get(ResearchRun, state["run_id"]))
    if not state["coverage"]["sufficient"] and state["queries"] and state["round"] < budget.max_rounds:
        return "collect"
    return "analyze"


@durable("analyze")
def analyze(state: ResearchState) -> dict:
    result = generate(state["run_id"], "analyze", state["brief"] + "\n"
                      + evidence_context(state)
                      + "\n提炼知识卡。每条主张必须附原文片段编号和完全匹配原文的引句。", Knowledge)
    with session() as db, db.begin():
        run = db.get(ResearchRun, state["run_id"])
        existing = list(db.scalars(select(Claim.id).where(Claim.run_id == run.id)))
        if existing:
            return {"claims": existing}
        chunks = {chunk.id: chunk for chunk in db.scalars(select(SourceChunk).where(
            SourceChunk.id.in_(state["chunks"]),
        ))}
        claim_ids, cards_by_chunk = [], {}
        for item in result.cards:
            card = WikiCard(
                concept=item.concept, definition=item.definition, explanation=item.explanation,
                domain=state["project"]["domain"], project_ref=run.project_id,
                assigned_agent="dispersion", needs_review=True, maturity="Seed",
            )
            db.add(card)
            db.flush()
            for item_claim in item.claims:
                claim = Claim(run_id=run.id, card_id=card.id, statement=item_claim.statement)
                db.add(claim)
                db.flush()
                claim_ids.append(claim.id)
                for evidence in item_claim.evidence:
                    chunk = chunks.get(evidence.chunk_id)
                    if chunk is None or evidence.quote not in chunk.content:
                        raise ValueError("引用必须完全匹配本次研究使用的原文片段")
                    db.add(EvidenceLink(claim_id=claim.id, **evidence.model_dump()))
                    cards_by_chunk.setdefault(chunk.id, set()).add(card.id)
            for tag_name in sorted(set(item.tags)):
                tag = db.scalar(select(Tag).where(Tag.name == tag_name, Tag.parent_id.is_(None)))
                if tag is None:
                    tag = Tag(name=tag_name)
                    db.add(tag)
                    db.flush()
                db.add(CardTag(card_id=card.id, tag_id=tag.id, source="ai"))
            audit(db, "提炼知识卡", "wiki_cards", str(card.id), "dispersion")
        linked = set()
        for card_ids in cards_by_chunk.values():
            for left in sorted(card_ids):
                for right in sorted(card_ids):
                    if left < right and (left, right) not in linked:
                        db.add(CardLink(from_id=left, to_id=right, relation="相关",
                                        note="共享原文证据", source="ai"))
                        linked.add((left, right))
        return {"claims": claim_ids}


def claims_context(state: ResearchState) -> str:
    with session() as db:
        claims = db.scalars(select(Claim).where(Claim.id.in_(state["claims"]))).all()
        return json.dumps([{"claim_id": claim.id, "statement": claim.statement}
                           for claim in claims], ensure_ascii=False)


@durable("outline")
def outline(state: ResearchState) -> dict:
    result = generate(state["run_id"], "outline", state["brief"] + "\n" + claims_context(state)
                      + "\n根据证据生成文稿标题及章节清单。", Outline)
    content = "# " + result.title + "\n\n" + "\n".join("## " + title for title in result.sections)
    save_artifact(state, "outline", content, "ai")
    return {"outline": content}


@durable("draft")
def draft(state: ResearchState) -> dict:
    structure = generate(state["run_id"], "outline_structure", state["outline"]
                         + "\n保留已确认大纲的所有标题，提取章节结构。", Outline)
    content = ["# " + structure.title]
    valid = set(state["claims"])
    for index, title in enumerate(structure.sections):
        section = generate(state["run_id"], f"section_{index}", state["brief"] + "\n"
                           + state["outline"] + "\n" + claims_context(state)
                           + f"\n仅撰写章节：{title}。每段标注支持其内容的 claim_ids。", Section)
        content.append("## " + title)
        for paragraph in section.paragraphs:
            if not set(paragraph.claim_ids).issubset(valid):
                raise ValueError("章节引用了本次研究范围外的知识主张")
            citations = " ".join(f"[证据 {identifier}](/evidence/{identifier})"
                                 for identifier in paragraph.claim_ids)
            content.append(paragraph.text + " " + citations)
    if state["coverage"]["gaps"]:
        content.append("## 证据限制\n\n" + "\n".join(
            "- " + gap for gap in state["coverage"]["gaps"]
        ))
    text = "\n\n".join(content)
    save_artifact(state, "draft", text, "ai", state["claims"])
    return {"draft": text}


@durable("critique")
def critique(state: ResearchState) -> dict:
    result = generate(state["run_id"], "critique", state["brief"] + "\n"
                      + claims_context(state) + "\n" + state["draft"]
                      + "\n逐项检查陈述与证据是否一致，指出无证据或夸大的表述。", Critique)
    content = state["draft"]
    if result.issues:
        content += "\n\n## 审阅待确认\n\n" + "\n".join("- " + issue for issue in result.issues)
    return {"draft": content, "critique": result.model_dump()}


@durable("publish")
def publish(state: ResearchState) -> dict:
    with session() as db, db.begin():
        run = db.get(ResearchRun, state["run_id"])
        existing = db.scalar(select(ArtifactVersion).where(
            ArtifactVersion.run_id == run.id, ArtifactVersion.kind == "published",
        ))
        if existing:
            return {"output_id": existing.output_id}
        key, _ = put_text(state["draft"], "outputs/" + run.id)
        output = Output(
            name=state["project"]["name"], type=state["project"]["output_type"],
            content=state["draft"], project_ref=run.project_id, domain=state["project"]["domain"],
            status="完成", review_needed=False, assigned_agent="diffraction",
            word_count=len(state["draft"]),
        )
        db.add(output)
        db.flush()
        db.add(ArtifactVersion(
            run_id=run.id, output_id=output.id, kind="published", revision=run.revision,
            content=state["draft"], object_key=key, author="human", citations=state["claims"],
        ))
        audit(db, "确认产出", "outputs", str(output.id), "human")
        return {"output_id": output.id}


def build_graph(checkpointer):
    graph = StateGraph(ResearchState)
    nodes = {"brief": brief, "brief_review": gate("brief", "brief"), "collect": collect,
             "coverage": coverage, "analyze": analyze, "outline": outline,
             "outline_review": gate("outline", "outline"), "draft": draft,
             "critique": critique, "final_review": gate("draft", "draft"), "publish": publish}
    for name, function in nodes.items():
        graph.add_node(name, function)
    for source, target in [(START, "brief"), ("brief", "brief_review"), ("collect", "coverage"),
                           ("analyze", "outline"), ("outline", "outline_review"),
                           ("draft", "critique"), ("critique", "final_review"), ("publish", END)]:
        graph.add_edge(source, target)
    for source, target in [("brief_review", "collect"), ("outline_review", "draft"),
                           ("final_review", "publish")]:
        graph.add_conditional_edges(source, next_after_review(target), [target, END])
    graph.add_conditional_edges("coverage", coverage_route, ["collect", "analyze"])
    return graph.compile(checkpointer=checkpointer)
