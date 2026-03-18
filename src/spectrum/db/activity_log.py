"""Activity Log recorder — decorator + direct API for audit trail.

Every write operation should be logged via @logged or ActivityLogger.log().
"""

from __future__ import annotations

import functools
import json
import logging
from typing import Any, Callable

from spectrum.db.operations import DatabaseOps

logger = logging.getLogger(__name__)


def _serialize(val: str | dict | Any) -> str:
    """Serialize before/after values: dicts → JSON, strings pass through."""
    if isinstance(val, dict):
        return json.dumps(val, ensure_ascii=False)
    return str(val) if val else ""


class ActivityLogger:
    """Writes entries to the activity_log table."""

    def __init__(self, db: DatabaseOps) -> None:
        self._db = db

    async def log(
        self,
        actor: str,
        action_type: str,
        target_db: str,
        description: str,
        target_record: str = "",
        before: str | dict = "",
        after: str | dict = "",
        confidence: float | None = None,
        needs_review: bool = False,
        notes: str = "",
    ) -> None:
        title = f"{action_type}｜{target_db}｜{description}"
        try:
            await self._db.create_log(
                title=title,
                actor=actor,
                action_type=action_type,
                target_db=target_db,
                target_record=target_record,
                before=_serialize(before),
                after=_serialize(after),
                confidence=confidence,
                needs_review=needs_review,
                notes=notes,
            )
            logger.debug("Logged: %s", title)
        except Exception:
            logger.exception("Failed to write activity log: %s", title)


def logged(
    actor: str,
    action_type: str,
    target_db: str,
    description_fn: Callable[..., str] | None = None,
) -> Callable:
    """Decorator that auto-logs a write operation.

    The decorated method's `self` must have `activity_logger: ActivityLogger`.
    """

    def decorator(fn: Callable) -> Callable:
        @functools.wraps(fn)
        async def wrapper(self: Any, *args: Any, **kwargs: Any) -> Any:
            result = await fn(self, *args, **kwargs)

            al: ActivityLogger | None = getattr(self, "activity_logger", None)
            if al is None:
                return result

            desc = ""
            if description_fn:
                try:
                    desc = description_fn(*args, **kwargs)
                except Exception:
                    desc = fn.__name__

            # Auto-flag review for status/priority changes
            needs_review = action_type == "Update"

            await al.log(
                actor=actor,
                action_type=action_type,
                target_db=target_db,
                description=desc,
                needs_review=needs_review,
            )
            return result

        return wrapper

    return decorator
