"""Shared LLM response parsing utilities for agents."""

from __future__ import annotations

import json
import logging
import re

logger = logging.getLogger(__name__)


def sanitize_json(text: str) -> str:
    """Fix common LLM JSON mistakes (trailing commas, etc.)."""
    return re.sub(r",\s*([}\]])", r"\1", text)


def _try_fix_truncated(text: str) -> object | None:
    """Attempt to recover a truncated JSON array by finding the last complete element.

    Walks backwards from the end of the text to find the last ``}`` or ``]``
    that, when the outer brackets are balanced, yields valid JSON.
    """
    for i in range(len(text) - 1, -1, -1):
        if text[i] in ("}", "]"):
            candidate = text[: i + 1]
            # Balance outer brackets
            open_braces = candidate.count("{") - candidate.count("}")
            open_brackets = candidate.count("[") - candidate.count("]")
            candidate += "}" * max(0, open_braces)
            candidate += "]" * max(0, open_brackets)
            try:
                return json.loads(candidate)
            except (json.JSONDecodeError, ValueError):
                continue
    return None


def extract_json_from_llm(content: str, expect_type: type = list):
    """Extract JSON from LLM response, handling code blocks, common errors,
    and truncated output.

    Strips markdown code fences, locates JSON boundaries, fixes trailing
    commas, then parses.  If normal parsing fails, attempts to recover
    truncated JSON by bracket completion.

    Raises ``json.JSONDecodeError`` or ``TypeError`` on failure so callers
    can fall back gracefully.
    """
    text = content.strip()

    # Strip markdown code fences
    if "```" in text:
        lines = text.split("\n")
        inside = False
        json_lines: list[str] = []
        for line in lines:
            if line.strip().startswith("```"):
                inside = not inside
                continue
            if inside:
                json_lines.append(line)
        if json_lines:
            text = "\n".join(json_lines)

    # Locate JSON boundaries
    if expect_type is dict:
        start, end = text.find("{"), text.rfind("}") + 1
    else:
        start, end = text.find("["), text.rfind("]") + 1

    if start >= 0 and end > start:
        text = text[start:end]

    text = sanitize_json(text)

    # Strategy 1: direct parse
    try:
        result = json.loads(text)
        if not isinstance(result, expect_type):
            raise TypeError(f"Expected {expect_type}, got {type(result)}")
        return result
    except (json.JSONDecodeError, ValueError):
        pass

    # Strategy 2: recover truncated JSON
    recovered = _try_fix_truncated(text)
    if recovered is not None:
        # Unwrap single-element list if expecting dict
        if expect_type is dict and isinstance(recovered, list) and len(recovered) == 1:
            recovered = recovered[0]
        if isinstance(recovered, expect_type):
            logger.warning(
                "Recovered truncated JSON (%d chars → %s with %s elements)",
                len(text),
                type(recovered).__name__,
                len(recovered) if isinstance(recovered, (list, dict)) else "?",
            )
            return recovered

    # Strategy 3: extract first complete object via JSONDecoder
    try:
        decoder = json.JSONDecoder()
        obj, _ = decoder.raw_decode(text.lstrip())
        if isinstance(obj, expect_type):
            logger.warning("Extracted first complete JSON object from partial output")
            return obj
    except (json.JSONDecodeError, ValueError):
        pass

    # All strategies failed — raise for caller to handle
    raise json.JSONDecodeError("Failed to extract JSON after all recovery strategies", text, 0)


def normalize_field(value) -> str:
    """Convert list/dict field values to readable text strings."""
    if isinstance(value, list):
        return "\n".join(str(item) for item in value)
    if isinstance(value, dict):
        return "\n".join(f"{k}: {v}" for k, v in value.items())
    return str(value) if value else ""
