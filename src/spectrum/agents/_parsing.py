"""Shared LLM response parsing utilities for agents."""

from __future__ import annotations

import json
import re


def sanitize_json(text: str) -> str:
    """Fix common LLM JSON mistakes (trailing commas, etc.)."""
    return re.sub(r",\s*([}\]])", r"\1", text)


def extract_json_from_llm(content: str, expect_type: type = list):
    """Extract JSON from LLM response, handling code blocks and common errors.

    Strips markdown code fences, locates JSON boundaries, fixes trailing
    commas, then parses.  Raises ``json.JSONDecodeError`` or ``TypeError``
    on failure so callers can fall back gracefully.
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
    result = json.loads(text)
    if not isinstance(result, expect_type):
        raise TypeError(f"Expected {expect_type}, got {type(result)}")
    return result


def normalize_field(value) -> str:
    """Convert list/dict field values to readable text strings."""
    if isinstance(value, list):
        return "\n".join(str(item) for item in value)
    if isinstance(value, dict):
        return "\n".join(f"{k}: {v}" for k, v in value.items())
    return str(value) if value else ""
