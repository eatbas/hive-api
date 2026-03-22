from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from typing import Any

from ..models import ChatResponse


def _safe_error_message(exc: BaseException) -> str:
    """Return a non-empty error description for any exception."""

    msg = str(exc)
    if msg:
        return msg
    return repr(exc) or type(exc).__name__ or "unknown error"


_MAX_EVENT_QUEUE_SIZE = 1024


@dataclass(slots=True)
class JobHandle:
    events: asyncio.Queue[dict[str, Any]] = field(
        default_factory=lambda: asyncio.Queue(maxsize=_MAX_EVENT_QUEUE_SIZE),
    )
    result_future: asyncio.Future[ChatResponse] | None = None

    async def publish(self, event: dict[str, Any]) -> None:
        await self.events.put(event)
