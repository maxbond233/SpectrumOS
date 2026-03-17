"""Tests for database CRUD operations."""

from __future__ import annotations

import pytest
from spectrum.db.operations import DatabaseOps


async def test_create_and_get_project(db: DatabaseOps):
    project = await db.create_project(
        name="scVI 单细胞分析",
        domain="生物信息学",
        priority="P1",
        output_type="综述",
    )
    assert project.id is not None
    assert project.name == "scVI 单细胞分析"
    assert project.status == "未开始"

    fetched = await db.get_project(project.id)
    assert fetched is not None
    assert fetched.name == project.name


async def test_update_project(db: DatabaseOps):
    project = await db.create_project(name="Test Project")
    updated = await db.update_project(project.id, status="进行中", priority="P1")
    assert updated.status == "进行中"
    assert updated.priority == "P1"


async def test_list_projects_with_filter(db: DatabaseOps):
    await db.create_project(name="A", status="未开始")
    await db.create_project(name="B", status="进行中")
    await db.create_project(name="C", status="未开始")

    pending = await db.list_projects(status="未开始")
    assert len(pending) == 2


async def test_create_source(db: DatabaseOps):
    source = await db.create_source(
        title="scVI Paper",
        source_type="论文",
        url="https://example.com/scvi",
        project_ref=1,
    )
    assert source.id is not None
    assert source.status == "Collected"


async def test_create_wiki_card(db: DatabaseOps):
    card = await db.create_wiki_card(
        concept="Variational Autoencoder",
        type="方法",
        domain="机器学习",
        definition="一种生成模型",
        maturity="Seed",
    )
    assert card.id is not None
    assert card.maturity == "Seed"


async def test_create_output(db: DatabaseOps):
    output = await db.create_output(
        name="scVI 综述",
        type="综述",
        content="# scVI\n\n这是一篇综述...",
        word_count=100,
    )
    assert output.id is not None
    assert output.content.startswith("# scVI")


async def test_task_lifecycle(db: DatabaseOps):
    task = await db.create_task(
        name="采集 · scVI 相关论文",
        type="采集",
        assigned_agent="focus",
        status="Todo",
        project_ref=1,
    )
    assert task.status == "Todo"

    updated = await db.update_task(task.id, status="Doing")
    assert updated.status == "Doing"

    done = await db.update_task(task.id, status="Done")
    assert done.status == "Done"


async def test_resolve_dependencies(db: DatabaseOps):
    t1 = await db.create_task(name="Task A", status="Done", assigned_agent="focus")
    t2 = await db.create_task(
        name="Task B",
        status="Waiting",
        assigned_agent="dispersion",
        depends_on=str(t1.id),
    )

    unlocked = await db.resolve_dependencies()
    assert unlocked == 1

    refreshed = await db.get_task(t2.id)
    assert refreshed.status == "Todo"


async def test_resolve_dependencies_not_ready(db: DatabaseOps):
    t1 = await db.create_task(name="Task A", status="Doing", assigned_agent="focus")
    t2 = await db.create_task(
        name="Task B",
        status="Waiting",
        assigned_agent="dispersion",
        depends_on=str(t1.id),
    )

    unlocked = await db.resolve_dependencies()
    assert unlocked == 0

    refreshed = await db.get_task(t2.id)
    assert refreshed.status == "Waiting"


async def test_activity_log(db: DatabaseOps):
    await db.create_log(
        title="Create｜Research Projects｜测试课题",
        actor="prism",
        action_type="Create",
        target_db="Research Projects",
    )
    logs = await db.list_logs()
    assert len(logs) == 1
    assert logs[0].actor == "prism"
