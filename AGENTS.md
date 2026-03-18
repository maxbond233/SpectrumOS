# Repository Guidelines

## Project Structure & Module Organization
Core code lives in `src/spectrum/`. Use `agents/` for agent implementations, `orchestrator/` for scheduling and pipeline flow, `db/` for SQLAlchemy models and operations, `api/` for FastAPI routes and schemas, `llm/` for provider/client code, and `tools/` for search and content extraction. Static dashboard assets live in `src/spectrum/dashboard/`. Tests are under `tests/`, currently split by area such as `tests/test_db/` and `tests/test_orchestrator/`. Runtime configuration is stored in `config/settings.yaml`; keep secrets in `.env`, not in source control.

## Build, Test, and Development Commands
Install locally with `pip install -e ".[dev]"`. Start the full app with `spectrum run` or `python -m spectrum.main`; this launches the scheduler and FastAPI server on port `8078`. Use `pytest -v` for the full test suite, `pytest tests/test_db/ -v` for a focused run, and `pytest tests/test_db/test_operations.py::test_create_and_get_project -v` for a single test. Lint with `ruff check src/ tests/` and format with `ruff format src/ tests/`.

## Architecture

SQLite-backed multi-agent knowledge pipeline. 4 agents process research projects through a linear pipeline: 课题 → 采集 → 分析 → 产出.

**Data flow:** `main.py` initializes everything — DB engine, LLM client, agents, scheduler, FastAPI — then runs scheduler + API concurrently via `asyncio.gather`.

**Agent tick lifecycle** (`agents/base.py`): Scheduler calls `agent.tick()` every 30s. Base tick queries Agent Board for `status=Todo` tasks assigned to this agent, transitions each through `Todo → Doing → process_task() → Done`. Errors increment `retry_count`; after 3 failures task is marked `Failed` with `review_needed=True`. Prism overrides `tick()` to also scan for new projects and check pipeline progress.

**Dependency chain:** Prism decomposes projects into chained tasks (采集→分析→产出). Downstream tasks start as `Waiting` with `depends_on` referencing comma-separated upstream task IDs. Scheduler calls `db.resolve_dependencies()` each tick to unlock `Waiting → Todo` when all deps are `Done`.

**Project status flow:** 未开始 → 进行中 → 待审核 → 完成. Projects enter "待审核" when all tasks are done but outputs still have `review_needed=True`. Projects only transition to "完成" after all outputs are reviewed. If multiple outputs exist, Prism creates a synthesis task before marking complete.

**LLM protocol** (`llm/provider.py`): Abstract `LLMProvider` with `OpenAICompatProvider` implementation (handles Claude, DeepSeek, Qwen via OpenAI-compatible endpoints). `LLMClient` routes to per-agent providers based on `config/settings.yaml` — supports per-agent model/key/temperature overrides.

**Config** (`config.py`): `load_settings()` merges `config/settings.yaml` (structured config) with `.env` (secrets) via pydantic-settings. Includes backward-compat migration for old search config format.

**Multi-provider search** (`tools/`): `WebSearchTool` coordinates 4 search providers (Tavily, SerpAPI, Semantic Scholar, Perplexity) — concurrent execution, URL dedup with score boosting, domain blocklist/preferred-list filtering. Content extraction via Jina Reader API with regex fallback. Configured in `settings.yaml` under `search.providers`, `search.blocked_domains`, and `search.preferred_domains`.

**Focus agent 4-stage pipeline** (`agents/focus.py`): Code-driven, not LLM tool-loop. `_plan_search()` (LLM plans keywords) → `_execute_search()` (code runs multi-provider search + page extraction) → `_evaluate_results()` (LLM scores coverage, suggests supplements) → `_synthesize_sources()` (LLM produces structured records). Iterates up to `max_search_rounds` with a total query budget of `max_search_queries`.

**Shared parsing utilities** (`agents/_parsing.py`): `extract_json_from_llm()` handles markdown code fences, trailing commas, and type validation. `normalize_field()` converts list/dict values to readable text. Used by focus, dispersion, and diffraction agents.

## Database

6 SQLAlchemy ORM tables in `db/models.py`: `ResearchProject`, `Source`, `WikiCard`, `Output`, `AgentTask`, `ActivityLog`. Tests use in-memory SQLite (`conftest.py` provides a fresh `db` fixture per test).

## Key Conventions

- **No hard deletes** — `db/operations.py` intentionally has no delete methods. Archive via status fields instead.
- **All writes logged** — Every DB write should be recorded in `activity_log` table. Use `ActivityLogger.log()` or the `@logged` decorator. Title format: `"动作｜目标库｜说明"`.
- **Review needed** — Status/priority changes auto-set `review_needed=True` for human review.
- **Project-driven** — All sources, wiki cards, outputs, and tasks reference a `project_ref`. Domain is inferred by Prism and propagated to all downstream entities.
- **Field write isolation** — AI writes `ai_notes`, `assigned_agent`; humans write `name`, `status`, `priority`.

## Coding Style & Naming Conventions
Target Python 3.11+ and keep code compatible with the `src/` layout. Ruff enforces a `100`-character line length; use 4-space indentation and type hints for new or modified functions. Follow existing naming patterns: `snake_case` for modules/functions, `PascalCase` for classes, and clear agent names such as `prism`, `focus`, `dispersion`, and `diffraction`. Prefer small async functions in I/O-heavy paths. Do not add hard-delete database helpers; this repository archives via status fields instead.

## Testing Guidelines
Tests use `pytest` with `pytest-asyncio`; the shared fixture in `tests/conftest.py` provisions a fresh in-memory SQLite database per test. Name new tests `test_<behavior>.py` and keep them near the relevant subsystem. Add regression coverage for database writes, scheduler transitions, and API behavior when you change those areas.

## Commit & Pull Request Guidelines
Recent history uses Conventional Commit prefixes such as `feat:` and `docs:`. Keep commits scoped and descriptive, for example `feat: tighten scheduler retry handling`. Pull requests should explain the user-visible impact, call out config or schema changes, link related issues, and include screenshots when modifying `src/spectrum/dashboard/` pages or Explorer behavior.

## Adding a New Agent

1. Subclass `AgentBase` in `agents/`, set `agent_name` and `agent_label`
2. Implement `async process_task(self, task: AgentTask) -> list[str]`
3. Register in `main.py:build_agents()` factory dict
4. Add to `config/settings.yaml` under `agents.enabled` and optionally `llm.agents`

## Adding a New Search Provider

1. Subclass `SearchProvider` in `tools/search_providers.py`, set `name`
2. Implement `async search(self, query, max_results) -> list[SearchResult]`
3. Add to `_PROVIDER_MAP` in the same file
4. Add config entry in `settings.yaml` under `search.providers`
