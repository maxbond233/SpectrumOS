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
        """Single completion call for an agent."""
        provider = self.for_agent(agent_name)
        config = self._config.for_agent(agent_name)
        return await provider.complete(
            system=system,
            messages=messages,
            tools=tools,
            max_tokens=config.max_tokens,
            temperature=config.temperature,
        )

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
        return await provider.complete_with_tool_loop(
            system=system,
            messages=messages,
            tools=tools,
            tool_executor=tool_executor,
            max_tokens=config.max_tokens,
            temperature=config.temperature,
            max_rounds=max_rounds,
        )
