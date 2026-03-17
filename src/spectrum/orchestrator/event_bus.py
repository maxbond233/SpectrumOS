"""In-process async event bus — lightweight pub/sub for agent wake-up signals."""

from __future__ import annotations

import asyncio
import logging
from collections import defaultdict
from typing import Any, Callable, Coroutine

logger = logging.getLogger(__name__)

Listener = Callable[[str, Any], Coroutine[Any, Any, None]]


class EventBus:
    """Simple async event bus. Events are fire-and-forget wake-up signals."""

    def __init__(self) -> None:
        self._listeners: dict[str, list[Listener]] = defaultdict(list)

    def on(self, event_prefix: str, listener: Listener) -> None:
        """Register a listener for events matching a prefix."""
        self._listeners[event_prefix].append(listener)

    async def emit(self, event: str, data: Any = None) -> None:
        """Emit an event to all matching listeners."""
        for prefix, listeners in self._listeners.items():
            if event.startswith(prefix):
                for listener in listeners:
                    try:
                        await listener(event, data)
                    except Exception:
                        logger.exception("Event listener error for %s", event)

    async def emit_many(self, events: list[str]) -> None:
        """Emit multiple events."""
        for event in events:
            await self.emit(event)
