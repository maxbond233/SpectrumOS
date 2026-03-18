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
    provider: str = "openai_compat"
    model: str = "claude-sonnet-4-20250514"
    api_key_env: str = "CLAUDE_API_KEY"
    base_url: str | None = None
    base_url_env: str | None = "CLAUDE_BASE_URL"
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

class SearchProviderConfig(BaseModel):
    name: str = "tavily"
    api_key_env: str = ""
    max_results: int = 5
    enabled: bool = True


class ContentExtractorConfig(BaseModel):
    provider: str = "jina"       # jina / regex
    max_content_length: int = 20000


class SearchConfig(BaseModel):
    providers: list[SearchProviderConfig] = Field(default_factory=lambda: [
        SearchProviderConfig(name="tavily", api_key_env="TAVILY_API_KEY", max_results=8),
    ])
    extractor: ContentExtractorConfig = Field(default_factory=ContentExtractorConfig)
    max_search_rounds: int = 3
    max_search_queries: int = 10
    blocked_domains: list[str] = Field(default_factory=list)
    preferred_domains: list[str] = Field(default_factory=list)


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


class KnowledgeConfig(BaseModel):
    max_tag_depth: int = 3
    fts_rebuild_on_startup: bool = True


# ── Root Settings ────────────────────────────────────────────────────────────

class Settings(BaseSettings):
    claude_api_key: str = ""
    claude_base_url: str = ""
    deepseek_api_key: str = ""
    deepseek_base_url: str = ""
    tavily_api_key: str = ""
    serpapi_api_key: str = ""

    database: DatabaseConfig = Field(default_factory=DatabaseConfig)
    llm: LLMConfig = Field(default_factory=LLMConfig)
    search: SearchConfig = Field(default_factory=SearchConfig)
    scheduler: SchedulerConfig = Field(default_factory=SchedulerConfig)
    api: APIConfig = Field(default_factory=APIConfig)
    agents: AgentsConfig = Field(default_factory=AgentsConfig)
    knowledge: KnowledgeConfig = Field(default_factory=KnowledgeConfig)

    model_config = {"env_file": ".env", "env_file_encoding": "utf-8", "extra": "ignore"}


def _load_yaml(path: Path) -> dict[str, Any]:
    if path.exists():
        with open(path) as f:
            return yaml.safe_load(f) or {}
    return {}


def _migrate_search_config(data: dict[str, Any]) -> dict[str, Any]:
    """Backward compat: convert old flat search config to new providers list."""
    search = data.get("search", {})
    if not isinstance(search, dict):
        return data
    # Old format has "provider" key instead of "providers"
    if "provider" in search and "providers" not in search:
        old = search.copy()
        provider_name = old.pop("provider", "tavily")
        api_key_env = old.pop("api_key_env", "TAVILY_API_KEY")
        max_results = old.pop("max_results", 10)
        data["search"] = {
            "providers": [
                {"name": provider_name, "api_key_env": api_key_env, "max_results": max_results}
            ],
            **{k: v for k, v in old.items() if k not in ("provider", "api_key_env", "max_results")},
        }
    return data


def load_settings() -> Settings:
    """Load settings from YAML + env vars.

    Also exports .env values to os.environ so that downstream code
    (e.g. OpenAI SDK) can read them via os.environ.get().
    """
    _load_dotenv()
    yaml_data = _load_yaml(_CONFIG_DIR / "settings.yaml")
    yaml_data = _migrate_search_config(yaml_data)
    return Settings(**yaml_data)


def _load_dotenv() -> None:
    """Read .env file and inject into os.environ (skip existing keys)."""
    import os
    env_path = _ROOT / ".env"
    if not env_path.exists():
        return
    with open(env_path) as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, value = line.partition("=")
            key = key.strip()
            value = value.strip().strip('"').strip("'")
            if key and not os.environ.get(key):
                os.environ[key] = value


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
