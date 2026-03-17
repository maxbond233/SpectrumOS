# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Commands

```bash
pip install -e ".[dev]"          # Install with dev dependencies
spectrum run                      # Start scheduler + FastAPI (port 8078)
pytest -v                         # Run all tests
pytest tests/test_db/ -v          # Run DB tests only
pytest tests/test_db/test_operations.py::test_create_and_get_project -v  # Single test
ruff check src/ tests/            # Lint
ruff format src/ tests/           # Format
```

## Architecture

SQLite-backed multi-agent knowledge pipeline. 4 agents process research projects through a linear pipeline: 课题 → 采集 → 分析 → 产出.

**Data flow:** `main.py` initializes everything — DB engine, LLM client, agents, scheduler, FastAPI — then runs scheduler + API concurrently via `asyncio.gather`.

**Agent tick lifecycle** (`agents/base.py`): Scheduler calls `agent.tick()` every 30s. Base tick queries Agent Board for `status=Todo` tasks assigned to this agent, transitions each through `Todo → Doing → process_task() → Done`. Errors set `Waiting + review_needed=True`. Prism overrides `tick()` to also scan for new projects and check pipeline progress.

**Dependency chain:** Prism decomposes projects into chained tasks (采集→分析→产出). Downstream tasks start as `Waiting` with `depends_on` referencing upstream task IDs. Scheduler calls `db.resolve_dependencies()` each tick to unlock `Waiting → Todo` when all deps are `Done`.

**LLM dual protocol** (`llm/provider.py`): Abstract `LLMProvider` with `AnthropicProvider` (Claude) and `OpenAICompatProvider` (DeepSeek/Qwen). `LLMClient` routes to per-agent providers based on `config/settings.yaml`. Focus agent uses `complete_with_tool_loop()` for multi-round web search.

**Config** (`config.py`): `load_settings()` merges `config/settings.yaml` (structured config) with `.env` (secrets) via pydantic-settings.

## Key Conventions

- **No hard deletes** — `db/operations.py` intentionally has no delete methods. Archive via status fields instead.
- **All writes logged** — Every DB write should be recorded in `activity_log` table. Use `ActivityLogger.log()` or the `@logged` decorator. Title format: `"动作｜目标库｜说明"`.
- **Review needed** — Status/priority changes auto-set `review_needed=True` for human review.
- **Project-driven** — All sources, wiki cards, outputs, and tasks reference a `project_ref`.
- **Field write isolation** — AI writes `ai_notes`, `assigned_agent`; humans write `name`, `status`, `priority`.

## Database

6 SQLAlchemy ORM tables in `db/models.py`: `ResearchProject`, `Source`, `WikiCard`, `Output`, `AgentTask`, `ActivityLog`. Tests use in-memory SQLite (`conftest.py` provides a fresh `db` fixture per test).

## Adding a New Agent

1. Subclass `AgentBase` in `agents/`, set `agent_name` and `agent_label`
2. Implement `async process_task(self, task: AgentTask) -> list[str]`
3. Register in `main.py:build_agents()` factory dict
4. Add to `config/settings.yaml` under `agents.enabled` and optionally `llm.agents`
