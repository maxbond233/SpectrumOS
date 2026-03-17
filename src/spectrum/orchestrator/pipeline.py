"""Pipeline stage definitions and dependency resolution."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class Stage(str, Enum):
    COLLECT = "采集"
    ANALYZE = "分析"
    PRODUCE = "产出"
    COORDINATE = "协调"


STAGE_ORDER = [Stage.COLLECT, Stage.ANALYZE, Stage.PRODUCE]

STAGE_TO_AGENT = {
    Stage.COLLECT: "focus",
    Stage.ANALYZE: "dispersion",
    Stage.PRODUCE: "diffraction",
    Stage.COORDINATE: "prism",
}

AGENT_TO_STAGE = {v: k for k, v in STAGE_TO_AGENT.items()}


@dataclass
class PipelineStep:
    stage: Stage
    agent: str
    depends_on: Stage | None = None

    @property
    def next_stage(self) -> Stage | None:
        idx = STAGE_ORDER.index(self.stage) if self.stage in STAGE_ORDER else -1
        if 0 <= idx < len(STAGE_ORDER) - 1:
            return STAGE_ORDER[idx + 1]
        return None


# Standard pipeline: 采集 → 分析 → 产出
STANDARD_PIPELINE = [
    PipelineStep(Stage.COLLECT, "focus", depends_on=None),
    PipelineStep(Stage.ANALYZE, "dispersion", depends_on=Stage.COLLECT),
    PipelineStep(Stage.PRODUCE, "diffraction", depends_on=Stage.ANALYZE),
]
