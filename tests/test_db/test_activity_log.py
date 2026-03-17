"""Tests for the activity logger."""

from __future__ import annotations

import pytest
from spectrum.db.activity_log import ActivityLogger
from spectrum.db.operations import DatabaseOps


async def test_activity_logger(db: DatabaseOps):
    al = ActivityLogger(db)
    await al.log(
        actor="prism",
        action_type="Create",
        target_db="Agent Board",
        description="创建采集任务",
        target_record="42",
    )
    logs = await db.list_logs()
    assert len(logs) == 1
    assert "Create｜Agent Board｜创建采集任务" in logs[0].title
    assert logs[0].actor == "prism"


async def test_activity_logger_with_review(db: DatabaseOps):
    al = ActivityLogger(db)
    await al.log(
        actor="dispersion",
        action_type="Update",
        target_db="Sources",
        description="状态变更",
        needs_review=True,
    )
    logs = await db.list_logs()
    assert logs[0].needs_review is True
