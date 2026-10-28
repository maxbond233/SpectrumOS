import time

import httpx
from langgraph.checkpoint.postgres import PostgresSaver
from sqlalchemy import select

from spectrum.db.research import ModelCall, Outbox, ResearchRun
from spectrum.db.runtime import session
from spectrum.orchestrator.worker import execute
from spectrum.runtime_config import runtime_settings


def test_real_worker_budget_checkpoint_and_redelivery():
    settings = runtime_settings()
    token = settings.api_token.get_secret_value()
    headers = {"Authorization": "Bearer " + token} if token else {}
    with httpx.Client(base_url=f"http://127.0.0.1:{settings.port}/api", timeout=30,
                      headers=headers, trust_env=False) as client:
        response = client.post("/projects", json={
            "name": "SpectrumOS v0.5.0 预算与恢复核验",
            "domain": "软件架构核验",
            "research_questions": "SpectrumOS 如何在模型请求前限制预算并保存执行状态？",
            "scope": "当前仓库中的实际运行机制",
        })
        assert response.status_code == 201, response.text
        project_id = response.json()["id"]
        response = client.post(f"/projects/{project_id}/runs", json={
            "budget": {"max_cost_usd": 0.00000001},
        })
        assert response.status_code == 202, response.text
        run_id = response.json()["id"]
        with session() as db:
            event_id = db.scalar(select(Outbox.id).where(Outbox.run_id == run_id))
        execute.apply_async(args=[event_id])
        deadline = time.monotonic() + 45
        while time.monotonic() < deadline:
            result = client.get(f"/runs/{run_id}").json()
            if result["status"] == "failed":
                break
            time.sleep(0.2)
        assert result["status"] == "failed", result
        assert "费用预算不足" in result["error"]
        assert result["calls"] == []
        with PostgresSaver.from_conn_string(settings.postgres_dsn) as saver:
            checkpoint = saver.get_tuple({"configurable": {"thread_id": run_id}})
            assert checkpoint is not None
            assert checkpoint.checkpoint["channel_values"]["run_id"] == run_id
        with session() as db:
            before = db.get(ResearchRun, run_id).updated_at
            assert db.get(Outbox, event_id).status == "failed"
        execute.run(event_id)
        with session() as db:
            assert db.get(ResearchRun, run_id).updated_at == before
            assert db.scalar(select(ModelCall.id).where(ModelCall.run_id == run_id)) is None
        response = client.post(f"/projects/{project_id}/runs", json={
            "budget": {"max_cost_usd": 0.00000001},
        })
        assert response.status_code == 202, response.text
        next_id = response.json()["id"]
        try:
            conflict = client.post(f"/runs/{run_id}/retry")
            assert conflict.status_code == 409, conflict.text
        finally:
            client.post(f"/runs/{next_id}/cancel")
