"""Search provider implementations — Tavily, SerpAPI, Semantic Scholar, Perplexity."""

from __future__ import annotations

import logging
import os
from abc import ABC, abstractmethod
from dataclasses import dataclass

import httpx

from spectrum.config import SearchProviderConfig

logger = logging.getLogger(__name__)


@dataclass
class SearchResult:
    title: str
    url: str
    snippet: str
    score: float = 0.0
    source_provider: str = ""
    authors: str = ""
    year: int | None = None
    citation_count: int | None = None


class SearchProvider(ABC):
    """Abstract search provider."""

    name: str = ""

    @abstractmethod
    async def search(self, query: str, max_results: int = 5) -> list[SearchResult]:
        ...


class TavilyProvider(SearchProvider):
    name = "tavily"

    def __init__(self, api_key_env: str = "TAVILY_API_KEY") -> None:
        self._api_key = os.environ.get(api_key_env, "")

    async def search(self, query: str, max_results: int = 5) -> list[SearchResult]:
        if not self._api_key:
            logger.warning("Tavily API key not set, skipping")
            return []
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.post(
                "https://api.tavily.com/search",
                json={
                    "api_key": self._api_key,
                    "query": query,
                    "max_results": max_results,
                    "include_answer": False,
                },
            )
            resp.raise_for_status()
            data = resp.json()

        return [
            SearchResult(
                title=r.get("title", ""),
                url=r.get("url", ""),
                snippet=r.get("content", ""),
                score=r.get("score", 0.0),
                source_provider=self.name,
            )
            for r in data.get("results", [])
        ]


class SerpAPIProvider(SearchProvider):
    name = "serpapi"

    def __init__(self, api_key_env: str = "SERPAPI_API_KEY") -> None:
        self._api_key = os.environ.get(api_key_env, "")

    async def search(self, query: str, max_results: int = 5) -> list[SearchResult]:
        if not self._api_key:
            logger.warning("SerpAPI key not set, skipping")
            return []
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.get(
                "https://serpapi.com/search",
                params={
                    "api_key": self._api_key,
                    "q": query,
                    "num": max_results,
                    "engine": "google",
                },
            )
            resp.raise_for_status()
            data = resp.json()

        return [
            SearchResult(
                title=r.get("title", ""),
                url=r.get("link", ""),
                snippet=r.get("snippet", ""),
                source_provider=self.name,
            )
            for r in data.get("organic_results", [])
        ]


class SemanticScholarProvider(SearchProvider):
    """Semantic Scholar API — free, no key required (100 req/5min)."""

    name = "semantic_scholar"

    async def search(self, query: str, max_results: int = 5) -> list[SearchResult]:
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.get(
                "https://api.semanticscholar.org/graph/v1/paper/search",
                params={
                    "query": query,
                    "limit": max_results,
                    "fields": "title,abstract,authors,year,citationCount,url",
                },
            )
            resp.raise_for_status()
            data = resp.json()

        results = []
        for paper in data.get("data", []):
            authors = ", ".join(
                a.get("name", "") for a in (paper.get("authors") or [])
            )
            results.append(SearchResult(
                title=paper.get("title", ""),
                url=paper.get("url", ""),
                snippet=paper.get("abstract", "") or "",
                source_provider=self.name,
                authors=authors,
                year=paper.get("year"),
                citation_count=paper.get("citationCount"),
            ))
        return results


class PerplexityProvider(SearchProvider):
    """Perplexity Sonar API — OpenAI-compatible chat endpoint with citations."""

    name = "perplexity"

    def __init__(self, api_key_env: str = "PERPLEXITY_API_KEY") -> None:
        self._api_key = os.environ.get(api_key_env, "")

    async def search(self, query: str, max_results: int = 3) -> list[SearchResult]:
        if not self._api_key:
            logger.warning("Perplexity API key not set, skipping")
            return []
        async with httpx.AsyncClient(timeout=60) as client:
            resp = await client.post(
                "https://api.perplexity.ai/chat/completions",
                headers={
                    "Authorization": f"Bearer {self._api_key}",
                    "Content-Type": "application/json",
                },
                json={
                    "model": "sonar",
                    "messages": [
                        {"role": "user", "content": query},
                    ],
                },
            )
            resp.raise_for_status()
            data = resp.json()

        # Extract citations from response
        results = []
        citations = data.get("citations", [])
        content = ""
        if data.get("choices"):
            content = data["choices"][0].get("message", {}).get("content", "")

        if citations:
            for i, url in enumerate(citations[:max_results]):
                results.append(SearchResult(
                    title=f"Perplexity citation {i + 1}",
                    url=url,
                    snippet=content[:500] if i == 0 else "",
                    source_provider=self.name,
                ))
        elif content:
            # No citations but got a synthesized answer
            results.append(SearchResult(
                title="Perplexity synthesized answer",
                url="",
                snippet=content[:1000],
                source_provider=self.name,
            ))
        return results


# ── Factory ──────────────────────────────────────────────────────────────────

_PROVIDER_MAP: dict[str, type[SearchProvider]] = {
    "tavily": TavilyProvider,
    "serpapi": SerpAPIProvider,
    "semantic_scholar": SemanticScholarProvider,
    "perplexity": PerplexityProvider,
}


def create_search_provider(config: SearchProviderConfig) -> SearchProvider | None:
    """Create a search provider from config. Returns None if unknown name."""
    cls = _PROVIDER_MAP.get(config.name)
    if cls is None:
        logger.warning("Unknown search provider: %s", config.name)
        return None
    if config.api_key_env:
        return cls(api_key_env=config.api_key_env)
    return cls()
