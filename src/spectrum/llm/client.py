"""Unified LLM client — routes requests to the correct provider per agent."""

from __future__ import annotations

import logging
from typing import Any

from spectrum.config import LLMConfig
from spectrum.llm.provider import LLMProvider, LLMResponse, create_provider

logger = logging.getLogger(__name__)


class LLMClient:
    """Manages per-agent LLM providers based on config."""

    def __init__(self, config: LLMConfig) -> None:
        self._config = config
        self._providers: dict[str, LLMProvider] = {}
        self._default = create_provider(config.default)
        # Cumulative token usage tracking
        self.total_usage: dict[str, int] = {"input": 0, "output": 0, "calls": 0}
        self.agent_usage: dict[str, dict[str, int]] = {}

    def _track_usage(self, agent_name: str, response: LLMResponse) -> None:
        """Accumulate token usage from a response."""
        inp = response.usage.get("input", 0)
        out = response.usage.get("output", 0)
        self.total_usage["input"] += inp
        self.total_usage["output"] += out
        self.total_usage["calls"] += 1
        if agent_name not in self.agent_usage:
            self.agent_usage[agent_name] = {"input": 0, "output": 0, "calls": 0}
        self.agent_usage[agent_name]["input"] += inp
        self.agent_usage[agent_name]["output"] += out
        self.agent_usage[agent_name]["calls"] += 1

    def for_agent(self, agent_name: str) -> LLMProvider:
        """Get or create the provider for a specific agent."""
        if agent_name not in self._providers:
            agent_config = self._config.for_agent(agent_name)
            # Reuse default if config matches
            if agent_config == self._config.default:
                self._providers[agent_name] = self._default
            else:
                self._providers[agent_name] = create_provider(agent_config)
        return self._providers[agent_name]

    async def complete(
        self,
        agent_name: str,
        system: str,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
    ) -> LLMResponse:
        """Single completion call with automatic continuation on truncation.

        If the LLM output is truncated (finish_reason=length), automatically
        sends a continuation request (up to 2 times) and concatenates the results.
        """
        provider = self.for_agent(agent_name)
        config = self._config.for_agent(agent_name)
        response = await provider.complete(
            system=system,
            messages=messages,
            tools=tools,
            max_tokens=config.max_tokens,
            temperature=config.temperature,
        )
        self._track_usage(agent_name, response)

        # Auto-continue if truncated (up to 2 continuations)
        if response.stop_reason == "length" and response.content and not tools:
            response = await self._auto_continue(
                provider, system, messages, response, config.max_tokens, config.temperature,
                agent_name,
            )

        return response

    async def _auto_continue(
        self,
        provider: LLMProvider,
        system: str,
        original_messages: list[dict[str, Any]],
        response: LLMResponse,
        max_tokens: int,
        temperature: float,
        agent_name: str,
        max_continuations: int = 2,
    ) -> LLMResponse:
        """Continue a truncated response by asking the LLM to pick up where it left off."""
        accumulated = response.content
        for i in range(max_continuations):
            logger.info(
                "Auto-continuing truncated output for %s (continuation %d/%d, "
                "accumulated %d chars)",
                agent_name, i + 1, max_continuations, len(accumulated),
            )
            cont_messages = original_messages + [
                {"role": "assistant", "content": accumulated},
                {"role": "user", "content": "你的输出被截断了，请从截断处继续输出。不要重复已输出的内容，直接续写。"},
            ]
            cont_response = await provider.complete(
                system=system,
                messages=cont_messages,
                max_tokens=max_tokens,
                temperature=temperature,
            )
            self._track_usage(agent_name, cont_response)

            if cont_response.content:
                accumulated += cont_response.content

            if cont_response.stop_reason != "length":
                break

        response.content = accumulated
        response.stop_reason = "stop"
        return response

    async def complete_with_tools(
        self,
        agent_name: str,
        system: str,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        tool_executor: Any | None = None,
        max_rounds: int = 10,
    ) -> LLMResponse:
        """Multi-round tool-use loop for an agent."""
        provider = self.for_agent(agent_name)
        config = self._config.for_agent(agent_name)
        response = await provider.complete_with_tool_loop(
            system=system,
            messages=messages,
            tools=tools,
            tool_executor=tool_executor,
            max_tokens=config.max_tokens,
            temperature=config.temperature,
            max_rounds=max_rounds,
        )
        self._track_usage(agent_name, response)
        return response
