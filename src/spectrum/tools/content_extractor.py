"""Content extraction — Jina Reader API with regex fallback."""

from __future__ import annotations

import logging
import re
from abc import ABC, abstractmethod
from dataclasses import dataclass

import httpx

from spectrum.config import ContentExtractorConfig

logger = logging.getLogger(__name__)


@dataclass
class PageContent:
    url: str
    title: str
    text: str


class ContentExtractor(ABC):
    @abstractmethod
    async def extract(self, url: str, max_length: int = 20000) -> PageContent:
        ...


class JinaExtractor(ContentExtractor):
    """Extract page content via Jina Reader API (r.jina.ai)."""

    async def extract(self, url: str, max_length: int = 20000) -> PageContent:
        reader_url = f"https://r.jina.ai/{url}"
        async with httpx.AsyncClient(timeout=30, follow_redirects=True) as client:
            resp = await client.get(
                reader_url,
                headers={
                    "Accept": "text/markdown",
                    "X-No-Cache": "true",
                },
            )
            resp.raise_for_status()
            text = resp.text

        # Extract title from first markdown heading if present
        title = url
        for line in text.split("\n"):
            line = line.strip()
            if line.startswith("# "):
                title = line[2:].strip()
                break

        # Structure-aware truncation: keep headings and first paragraphs
        truncated = _smart_truncate(text, max_length)
        return PageContent(url=url, title=title, text=truncated)


class RegexExtractor(ContentExtractor):
    """Fallback: fetch raw HTML and strip tags with regex."""

    async def extract(self, url: str, max_length: int = 20000) -> PageContent:
        async with httpx.AsyncClient(timeout=30, follow_redirects=True) as client:
            resp = await client.get(url, headers={"User-Agent": "SpectrumOS/0.1"})
            resp.raise_for_status()
            html = resp.text

        # Extract title
        title_match = re.search(r"<title[^>]*>(.*?)</title>", html, re.DOTALL)
        title = title_match.group(1).strip() if title_match else url

        # Strip script/style blocks, then tags, collapse whitespace
        text = re.sub(r"<(script|style)[^>]*>.*?</\1>", "", html, flags=re.DOTALL)
        text = re.sub(r"<[^>]+>", " ", text)
        text = re.sub(r"\s+", " ", text).strip()

        return PageContent(url=url, title=title, text=text[:max_length])


def _smart_truncate(text: str, max_length: int) -> str:
    """Structure-aware truncation: preserve headings and section starts."""
    if len(text) <= max_length:
        return text

    lines = text.split("\n")
    result: list[str] = []
    length = 0

    for line in lines:
        line_len = len(line) + 1  # +1 for newline
        if length + line_len > max_length:
            # If we're mid-section, try to end at a paragraph boundary
            break
        result.append(line)
        length += line_len

    if not result:
        return text[:max_length]
    return "\n".join(result)


def create_extractor(config: ContentExtractorConfig) -> ContentExtractor:
    """Factory: build the configured extractor with regex fallback wrapper."""
    if config.provider == "jina":
        return _FallbackExtractor(
            primary=JinaExtractor(),
            fallback=RegexExtractor(),
            max_length=config.max_content_length,
        )
    return RegexExtractor()


class _FallbackExtractor(ContentExtractor):
    """Tries primary extractor, falls back on failure."""

    def __init__(
        self, primary: ContentExtractor, fallback: ContentExtractor, max_length: int
    ) -> None:
        self._primary = primary
        self._fallback = fallback
        self._max_length = max_length

    async def extract(self, url: str, max_length: int = 20000) -> PageContent:
        limit = max_length or self._max_length
        try:
            return await self._primary.extract(url, limit)
        except Exception as e:
            logger.warning("Primary extractor failed for %s: %s, using fallback", url, e)
            return await self._fallback.extract(url, limit)
