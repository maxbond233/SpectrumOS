from pathlib import Path

import httpx
import pytest
from sqlalchemy import inspect

from spectrum.db.research import SourceChunk, SourceVersion
from spectrum.db.runtime import engine, session
from spectrum.runtime_config import runtime_settings
from spectrum.tools.knowledge import ingest, search_knowledge
from spectrum.tools.storage import storage


@pytest.fixture(scope="module")
def client():
    settings = runtime_settings()
    token = settings.api_token.get_secret_value()
    headers = {"Authorization": "Bearer " + token} if token else {}
    with httpx.Client(base_url=f"http://127.0.0.1:{settings.port}/api", timeout=180,
                      headers=headers, trust_env=False) as connection:
        yield connection


@pytest.fixture(scope="module")
def project(client):
    response = client.post("/projects", json={
        "name": "SpectrumOS v0.5.0 项目文档核验",
        "domain": "软件架构核验",
        "research_questions": "项目如何保存研究运行、原文证据和人工审核记录？",
        "scope": "当前仓库中已经编写的文档与代码",
    })
    assert response.status_code == 201, response.text
    return response.json()


def test_service_and_schema(client):
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json()["version"] == "0.5.0"
    schema = inspect(engine())
    assert {"research_runs", "checkpoints", "source_versions", "evidence_links"} <= set(schema.get_table_names())
    assert schema.get_foreign_keys("evidence_links")
    assert schema.get_foreign_keys("wiki_cards")


def test_real_document_storage_and_hybrid_search(client, project):
    path = Path("docs/rfcs/001-durable-research-workflow.md").resolve()
    content = path.read_text()
    chunks = ingest(path.name, path.as_uri(), content, project["id"], project["domain"])
    assert chunks
    assert ingest(path.name, path.as_uri(), content, project["id"], project["domain"]) == chunks
    results = search_knowledge("PostgreSQL 保存研究运行和人工审核", project["domain"])
    assert set(chunks) & {result["id"] for result in results}
    with session() as db:
        chunk = db.get(SourceChunk, chunks[0])
        version = db.get(SourceVersion, chunk.version_id)
        response = storage().get_object(Bucket=runtime_settings().s3_bucket, Key=version.object_key)
        assert response["Body"].read().decode() == content
    assert not search_knowledge("PostgreSQL", "没有登记材料的领域")


def test_project_write_is_audited(client, project):
    response = client.patch(f"/projects/{project['id']}", json={"priority": "P1"})
    assert response.status_code == 200
    assert response.json()["review_needed"] is True
    entries = client.get("/logs?limit=100").json()["items"]
    assert any(entry["target_record"] == str(project["id"]) and entry["actor"] == "human" for entry in entries)


def test_foreign_key_and_input_validation(client):
    response = client.post("/projects", json={"name": ""})
    assert response.status_code == 422
    response = client.post("/tags", json={"name": "无有效父节点的标签", "parent_id": -1})
    assert response.status_code == 422


def test_run_cancellation_and_stale_review(client, project):
    response = client.post(f"/projects/{project['id']}/runs", json={"budget": {"max_cost_usd": 0.00000001}})
    assert response.status_code == 202, response.text
    identifier = response.json()["id"]
    duplicate = client.post(f"/projects/{project['id']}/runs", json={})
    assert duplicate.status_code == 409
    stale = client.post(f"/runs/{identifier}/review", json={
        "revision": 0, "decision": "approve", "content": "尚未生成研究简报，不能提前通过审核。",
    })
    assert stale.status_code == 409
    assert client.post(f"/runs/{identifier}/cancel").status_code == 200
    assert client.get(f"/runs/{identifier}").json()["status"] == "cancelled"
