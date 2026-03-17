"""Web search tool — Tavily / SerpAPI backend for the Focus agent."""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass

import httpx

from spectrum.config import SearchConfig

logger = logging.getLogger(__name__)


@dataclass
class SearchResult:
    title: str
    url: str
    snippet: str
    score: float = 0.0


@dataclass
class PageContent:
    url: str
    title: str
    text: str


class WebSearchTool:
    """Unified web search interface. Supports Tavily (default) and SerpAPI."""

    def __init__(self, config: SearchConfig) -> None:
        self._provider = config.provider
        self._api_key = os.environ.get(config.api_key_env, "")
        self._max_results = config.max_results

    async def search(self, query: str, max_results: int | None = None) -> list[SearchResult]:
        """Search the web and return results."""
        limit = max_results or self._max_results
        if self._provider == "tavily":
            return await self._tavily_search(query, limit)
        elif self._provider == "serpapi":
            return await self._serpapi_search(query, limit)
        raise ValueError(f"Unknown search provider: {self._provider}")

    async def fetch_page(self, url: str) -> PageContent:
        """Fetch and extract main text content from a URL."""
        async with httpx.AsyncClient(timeout=30, follow_redirects=True) as client:
            resp = await client.get(url, headers={"User-Agent": "SpectrumOS/0.1"})
            resp.raise_for_status()
            text = resp.text
            # Basic extraction — strip HTML tags for plain text
            import re
            # Remove script/style blocks
            text = re.sub(r"<(script|style)[^>]*>.*?</\1>", "", text, flags=re.DOTALL)
            # Remove tags
            text = re.sub(r"<[^>]+>", " ", text)
            # Collapse whitespace
            text = re.sub(r"\s+", " ", text).strip()
            # Extract title
            title_match = re.search(r"<title[^>]*>(.*?)</title>", resp.text, re.DOTALL)
            title = title_match.group(1).strip() if title_match else url
            return PageContent(url=url, title=title, text=text[:10000])

    async def _tavily_search(self, query: str, max_results: int) -> list[SearchResult]:
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

        results = []
        for r in data.get("results", []):
            results.append(SearchResult(
                title=r.get("title", ""),
                url=r.get("url", ""),
                snippet=r.get("content", ""),
                score=r.get("score", 0.0),
            ))
        return results

    async def _serpapi_search(self, query: str, max_results: int) -> list[SearchResult]:
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

        results = []
        for r in data.get("organic_results", []):
            results.append(SearchResult(
                title=r.get("title", ""),
                url=r.get("link", ""),
                snippet=r.get("snippet", ""),
            ))
        return results

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
                "name": "fetch_page",
                "description": "抓取指定 URL 的页面内容，提取正文文本。",
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
        if tool_name == "web_search":
            results = await self.search(
                arguments["query"],
                arguments.get("max_results", 5),
            )
            return "\n\n".join(
                f"[{r.title}]({r.url})\n{r.snippet}" for r in results
            )
        elif tool_name == "fetch_page":
            page = await self.fetch_page(arguments["url"])
            return f"# {page.title}\n\n{page.text}"
        return f"Unknown tool: {tool_name}"
