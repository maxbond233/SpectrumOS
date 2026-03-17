"""Configuration loader — merges settings.yaml + environment variables."""

from __future__ import annotations

import logging
import logging.config
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, Field
from pydantic_settings import BaseSettings

_ROOT = Path(__file__).resolve().parent.parent.parent  # project root
_CONFIG_DIR = _ROOT / "config"


# ── Database ─────────────────────────────────────────────────────────────────

class DatabaseConfig(BaseModel):
    url: str = "sqlite+aiosqlite:///data/spectrum.db"


# ── LLM ──────────────────────────────────────────────────────────────────────

class LLMProviderConfig(BaseModel):
    provider: str = "anthropic"
    model: str = "claude-sonnet-4-20250514"
    api_key_env: str = "ANTHROPIC_API_KEY"
    base_url: str | None = None
    base_url_env: str | None = None
    max_tokens: int = 4096
    temperature: float = 0.3


class LLMConfig(BaseModel):
    default: LLMProviderConfig = Field(default_factory=LLMProviderConfig)
    agents: dict[str, dict[str, Any]] = Field(default_factory=dict)

    def for_agent(self, agent_name: str) -> LLMProviderConfig:
        overrides = self.agents.get(agent_name, {})
        if not overrides:
            return self.default
        merged = self.default.model_dump()
        merged.update(overrides)
        return LLMProviderConfig(**merged)


# ── Search ───────────────────────────────────────────────────────────────────

class SearchConfig(BaseModel):
    provider: str = "tavily"
    api_key_env: str = "TAVILY_API_KEY"
    max_results: int = 10


# ── Scheduler ────────────────────────────────────────────────────────────────

class SchedulerConfig(BaseModel):
    tick_interval: int = 30
    max_concurrent_agents: int = 3


# ── API ──────────────────────────────────────────────────────────────────────

class APIConfig(BaseModel):
    host: str = "0.0.0.0"
    port: int = 8078


# ── Agents ───────────────────────────────────────────────────────────────────

class AgentsConfig(BaseModel):
    enabled: list[str] = Field(
        default_factory=lambda: ["prism", "focus", "dispersion", "diffraction"]
    )


# ── Root Settings ────────────────────────────────────────────────────────────

class Settings(BaseSettings):
    anthropic_api_key: str = ""
    openai_compat_api_key: str = ""
    openai_compat_base_url: str = ""
    tavily_api_key: str = ""

    database: DatabaseConfig = Field(default_factory=DatabaseConfig)
    llm: LLMConfig = Field(default_factory=LLMConfig)
    search: SearchConfig = Field(default_factory=SearchConfig)
    scheduler: SchedulerConfig = Field(default_factory=SchedulerConfig)
    api: APIConfig = Field(default_factory=APIConfig)
    agents: AgentsConfig = Field(default_factory=AgentsConfig)

    model_config = {"env_file": ".env", "env_file_encoding": "utf-8", "extra": "ignore"}


def _load_yaml(path: Path) -> dict[str, Any]:
    if path.exists():
        with open(path) as f:
            return yaml.safe_load(f) or {}
    return {}


def load_settings() -> Settings:
    """Load settings from YAML + env vars."""
    yaml_data = _load_yaml(_CONFIG_DIR / "settings.yaml")
    return Settings(**yaml_data)


def setup_logging() -> None:
    """Configure logging from config/logging.yaml."""
    log_cfg = _load_yaml(_CONFIG_DIR / "logging.yaml")
    if log_cfg:
        log_dir = _ROOT / "logs"
        log_dir.mkdir(exist_ok=True)
        for handler in log_cfg.get("handlers", {}).values():
            if "filename" in handler:
                handler["filename"] = str(_ROOT / handler["filename"])
        logging.config.dictConfig(log_cfg)
    else:
        logging.basicConfig(level=logging.INFO)
