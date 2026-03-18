"""Web search tool — multi-provider coordinator for the Focus agent."""

from __future__ import annotations

import asyncio
import logging
from urllib.parse import urlparse

from spectrum.config import SearchConfig
from spectrum.tools.content_extractor import ContentExtractor, PageContent, create_extractor
from spectrum.tools.search_providers import (
    SearchProvider,
    SearchResult,
    SemanticScholarProvider,
    create_search_provider,
)

logger = logging.getLogger(__name__)


def _normalize_url(url: str) -> str:
    """Normalize URL for dedup: strip scheme, trailing slash, www prefix."""
    parsed = urlparse(url)
    host = parsed.netloc.lower().removeprefix("www.")
    path = parsed.path.rstrip("/")
    return f"{host}{path}"


def _dedup_results(results: list[SearchResult]) -> list[SearchResult]:
    """Deduplicate by normalized URL. Boost score when multiple providers return same URL."""
    seen: dict[str, SearchResult] = {}
    for r in results:
        if not r.url:
            continue
        key = _normalize_url(r.url)
        if key in seen:
            # Boost score for results found by multiple providers
            seen[key].score = max(seen[key].score, r.score) + 0.1
            # Keep richer snippet
            if len(r.snippet) > len(seen[key].snippet):
                seen[key].snippet = r.snippet
        else:
            seen[key] = r
    return sorted(seen.values(), key=lambda r: r.score, reverse=True)


class WebSearchTool:
    """Multi-provider search coordinator with content extraction."""

    def __init__(self, config: SearchConfig) -> None:
        self._config = config
        self._providers: list[SearchProvider] = []
        self._academic_provider: SemanticScholarProvider | None = None
        self._extractor: ContentExtractor = create_extractor(config.extractor)
        self._blocked_domains: set[str] = set(config.blocked_domains)
        self._preferred_domains: set[str] = set(config.preferred_domains)

        for pc in config.providers:
            if not pc.enabled:
                continue
            provider = create_search_provider(pc)
            if provider is None:
                continue
            if isinstance(provider, SemanticScholarProvider):
                self._academic_provider = provider
            else:
                self._providers.append(provider)

        # If semantic_scholar wasn't in config but we need it, create a default
        if self._academic_provider is None:
            self._academic_provider = SemanticScholarProvider()

    async def search(self, query: str, max_results: int | None = None) -> list[SearchResult]:
        """Search across all enabled non-academic providers concurrently, merge and dedup."""
        if not self._providers:
            logger.warning("No search providers configured")
            return []

        tasks = []
        for provider in self._providers:
            limit = max_results or self._config.providers[0].max_results
            tasks.append(self._safe_search(provider, query, limit))

        all_results: list[SearchResult] = []
        for batch in await asyncio.gather(*tasks):
            all_results.extend(batch)

        deduped = _dedup_results(all_results)
        deduped = self._filter_and_boost(deduped)
        if max_results:
            deduped = deduped[:max_results]
        return deduped

    async def search_academic(self, query: str, max_results: int = 5) -> list[SearchResult]:
        """Search academic sources only (Semantic Scholar)."""
        if self._academic_provider is None:
            return []
        return await self._safe_search(self._academic_provider, query, max_results)

    async def fetch_page(self, url: str) -> PageContent:
        """Fetch and extract page content via configured extractor (Jina → regex fallback)."""
        return await self._extractor.extract(url, self._config.extractor.max_content_length)

    async def _safe_search(
        self, provider: SearchProvider, query: str, max_results: int
    ) -> list[SearchResult]:
        """Run a single provider search, catching errors."""
        try:
            results = await provider.search(query, max_results)
            logger.info(
                "Provider %s returned %d results for '%s'",
                provider.name, len(results), query[:50],
            )
            return results
        except Exception as e:
            status_code = getattr(getattr(e, "response", None), "status_code", None)
            if status_code == 429:
                logger.warning(
                    "Provider %s rate limited for '%s', skipping",
                    provider.name, query[:50],
                )
            else:
                logger.warning("Provider %s failed for '%s': %s", provider.name, query[:50], e)
            return []

    def _filter_and_boost(self, results: list[SearchResult]) -> list[SearchResult]:
        """Filter blocked domains and boost preferred domains."""
        filtered: list[SearchResult] = []
        for r in results:
            if not r.url:
                continue
            host = urlparse(r.url).netloc.lower().removeprefix("www.")
            # Check against blocked domains
            if any(host == d or host.endswith(f".{d}") for d in self._blocked_domains):
                logger.debug("Filtered blocked domain: %s", host)
                continue
            # Boost preferred domains
            if any(host == d or host.endswith(f".{d}") for d in self._preferred_domains):
                r.score += 0.3
            filtered.append(r)
        filtered.sort(key=lambda r: r.score, reverse=True)
        return filtered

    def as_llm_tools(self) -> list[dict]:
        """Return tool definitions in Anthropic tool format for LLM function calling."""
        return [
            {
                "name": "web_search",
                "description": "搜索互联网获取相关资料。返回标题、URL和摘要。",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "query": {
                            "type": "string",
                            "description": "搜索关键词",
                        },
                        "max_results": {
                            "type": "integer",
                            "description": "最大结果数量",
                            "default": 5,
                        },
                    },
                    "required": ["query"],
                },
            },
            {
                "name": "search_academic",
                "description": "搜索学术论文（Semantic Scholar）。返回论文标题、作者、摘要、引用数。",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "query": {
                            "type": "string",
                            "description": "学术搜索关键词",
                        },
                        "max_results": {
                            "type": "integer",
                            "description": "最大结果数量",
                            "default": 5,
                        },
                    },
                    "required": ["query"],
                },
            },
            {
                "name": "fetch_page",
                "description": "抓取指定 URL 的页面内容，提取正文文本（Markdown 格式）。",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "url": {
                            "type": "string",
                            "description": "要抓取的页面 URL",
                        },
                    },
                    "required": ["url"],
                },
            },
        ]

    async def execute_tool(self, tool_name: str, arguments: dict) -> str:
        """Execute a tool call from the LLM."""
        try:
            if tool_name == "web_search":
                results = await self.search(
                    arguments["query"],
                    arguments.get("max_results", 5),
                )
                if not results:
                    return "搜索无结果，请尝试其他关键词。"
                return "\n\n".join(
                    f"[{r.title}]({r.url})\n{r.snippet}" for r in results
                )
            elif tool_name == "search_academic":
                results = await self.search_academic(
                    arguments["query"],
                    arguments.get("max_results", 5),
                )
                if not results:
                    return "学术搜索无结果，请尝试其他关键词。"
                lines = []
                for r in results:
                    meta = []
                    if r.authors:
                        meta.append(f"Authors: {r.authors}")
                    if r.year:
                        meta.append(f"Year: {r.year}")
                    if r.citation_count is not None:
                        meta.append(f"Citations: {r.citation_count}")
                    lines.append(
                        f"[{r.title}]({r.url})\n{' | '.join(meta)}\n{r.snippet}"
                    )
                return "\n\n".join(lines)
            elif tool_name == "fetch_page":
                page = await self.fetch_page(arguments["url"])
                return f"# {page.title}\n\n{page.text}"
            return f"Unknown tool: {tool_name}"
        except Exception as e:
            logger.warning("Tool %s execution failed: %s", tool_name, e)
            return f"工具调用失败: {e}"
