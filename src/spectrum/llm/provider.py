"""LLM Provider abstraction — Anthropic + OpenAI-compatible dual protocol."""

from __future__ import annotations

import logging
import os
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any

import openai

from spectrum.config import LLMProviderConfig

logger = logging.getLogger(__name__)


@dataclass
class ToolCall:
    name: str
    arguments: dict[str, Any]
    id: str = ""


@dataclass
class LLMResponse:
    content: str = ""
    tool_calls: list[ToolCall] = field(default_factory=list)
    usage: dict[str, int] = field(default_factory=dict)
    stop_reason: str = ""


class LLMProvider(ABC):
    """Abstract base for LLM providers."""

    @abstractmethod
    async def complete(
        self,
        system: str,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        max_tokens: int = 4096,
        temperature: float = 0.3,
    ) -> LLMResponse: ...

    @abstractmethod
    async def complete_with_tool_loop(
        self,
        system: str,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        tool_executor: Any | None = None,
        max_tokens: int = 4096,
        temperature: float = 0.3,
        max_rounds: int = 10,
    ) -> LLMResponse:
        """Run a complete-then-execute-tools loop until the model stops calling tools."""
        ...


class OpenAICompatProvider(LLMProvider):
    """OpenAI-compatible API (DeepSeek, Qwen, etc.)."""

    def __init__(self, config: LLMProviderConfig) -> None:
        api_key = os.environ.get(config.api_key_env, "")
        base_url = config.base_url
        if not base_url and config.base_url_env:
            base_url = os.environ.get(config.base_url_env, "")
        self._client = openai.AsyncOpenAI(api_key=api_key, base_url=base_url or None)
        self._model = config.model

    async def complete(
        self,
        system: str,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        max_tokens: int = 4096,
        temperature: float = 0.3,
    ) -> LLMResponse:
        oai_messages = [{"role": "system", "content": system}]
        oai_messages.extend(messages)

        kwargs: dict[str, Any] = {
            "model": self._model,
            "max_tokens": max_tokens,
            "temperature": temperature,
            "messages": oai_messages,
        }
        if tools:
            # Convert Anthropic tool format to OpenAI function format
            oai_tools = []
            for t in tools:
                oai_tools.append({
                    "type": "function",
                    "function": {
                        "name": t["name"],
                        "description": t.get("description", ""),
                        "parameters": t.get("input_schema", {}),
                    },
                })
            kwargs["tools"] = oai_tools

        resp = await self._client.chat.completions.create(**kwargs)
        choice = resp.choices[0]

        content = choice.message.content or ""
        tool_calls = []
        if choice.message.tool_calls:
            import json
            for tc in choice.message.tool_calls:
                tool_calls.append(ToolCall(
                    name=tc.function.name,
                    arguments=json.loads(tc.function.arguments),
                    id=tc.id,
                ))

        return LLMResponse(
            content=content,
            tool_calls=tool_calls,
            usage={
                "input": resp.usage.prompt_tokens if resp.usage else 0,
                "output": resp.usage.completion_tokens if resp.usage else 0,
            },
            stop_reason=choice.finish_reason or "",
        )

    async def complete_with_tool_loop(
        self,
        system: str,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        tool_executor: Any | None = None,
        max_tokens: int = 4096,
        temperature: float = 0.3,
        max_rounds: int = 10,
    ) -> LLMResponse:
        import json

        oai_messages = [{"role": "system", "content": system}]
        oai_messages.extend(messages)
        final_response = LLMResponse()
        collected_tool_results: list[str] = []

        oai_tools = None
        if tools:
            oai_tools = [{
                "type": "function",
                "function": {
                    "name": t["name"],
                    "description": t.get("description", ""),
                    "parameters": t.get("input_schema", {}),
                },
            } for t in tools]

        for round_num in range(max_rounds):
            kwargs: dict[str, Any] = {
                "model": self._model,
                "max_tokens": max_tokens,
                "temperature": temperature,
                "messages": oai_messages,
            }
            if oai_tools:
                kwargs["tools"] = oai_tools

            resp = await self._client.chat.completions.create(**kwargs)
            choice = resp.choices[0]

            if resp.usage:
                final_response.usage = {
                    "input": final_response.usage.get("input", 0) + resp.usage.prompt_tokens,
                    "output": final_response.usage.get("output", 0) + resp.usage.completion_tokens,
                }

            if not choice.message.tool_calls or tool_executor is None:
                final_response.content = choice.message.content or ""
                final_response.stop_reason = choice.finish_reason or ""
                logger.debug(
                    "Tool loop finished after %d rounds, content length: %d",
                    round_num + 1, len(final_response.content),
                )
                return final_response

            # Append assistant message with tool calls
            oai_messages.append(choice.message.model_dump())

            # Execute tools and collect results
            for tc in choice.message.tool_calls:
                args = json.loads(tc.function.arguments)
                logger.debug("Calling tool %s with args: %s", tc.function.name, args)
                result = await tool_executor(tc.function.name, args)
                collected_tool_results.append(result)
                oai_messages.append({
                    "role": "tool",
                    "tool_call_id": tc.id,
                    "content": str(result),
                })

        # max_rounds exhausted — ask model for final summary with collected context
        logger.warning("Tool loop hit max_rounds (%d), requesting final summary", max_rounds)
        oai_messages.append({
            "role": "user",
            "content": "你已经完成了所有搜索。请根据以上工具返回的结果，按照要求的 JSON 格式输出最终结果。不要再调用任何工具。",
        })
        kwargs = {
            "model": self._model,
            "max_tokens": max_tokens,
            "temperature": temperature,
            "messages": oai_messages,
        }
        resp = await self._client.chat.completions.create(**kwargs)
        choice = resp.choices[0]
        final_response.content = choice.message.content or ""
        final_response.stop_reason = "max_rounds"
        return final_response


def create_provider(config: LLMProviderConfig) -> LLMProvider:
    """Factory: create the right provider from config."""
    if config.provider == "openai_compat":
        return OpenAICompatProvider(config)
    else:
        raise ValueError(f"Unknown LLM provider: {config.provider}")
