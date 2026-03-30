from __future__ import annotations

import asyncio
import uuid
from dataclasses import dataclass, field
from typing import Any

from ..models import ChatResponse
from ..models.enums import ScoreStatus, InstrumentName


def _safe_error_message(exc: BaseException) -> str:
    """Return a non-empty error description for any exception."""

    msg = str(exc)
    if msg:
        return msg
    return repr(exc) or type(exc).__name__ or "unknown error"


_MAX_EVENT_QUEUE_SIZE = 1024


@dataclass(slots=True)
class ScoreHandle:
    events: asyncio.Queue[dict[str, Any]] = field(
        default_factory=lambda: asyncio.Queue(maxsize=_MAX_EVENT_QUEUE_SIZE),
    )
    result_future: asyncio.Future[ChatResponse] | None = None
    score_id: str = field(default_factory=lambda: uuid.uuid4().hex)
    cancelled: asyncio.Event = field(default_factory=asyncio.Event)
    status: ScoreStatus = ScoreStatus.QUEUED
    provider: InstrumentName | None = None
    model: str | None = None

    async def publish(self, event: dict[str, Any]) -> None:
        await self.events.put(event)

    def publish_nowait(self, event: dict[str, Any]) -> None:
        """Non-blocking publish; silently drops the event if the queue is full."""
        try:
            self.events.put_nowait(event)
        except asyncio.QueueFull:
            pass


def stopped_event(handle: ScoreHandle) -> dict[str, Any]:
    """Build a terminal 'stopped' SSE event for the given handle."""
    return {
        "type": "stopped",
        "score_id": handle.score_id,
        "provider": handle.provider.value if handle.provider else None,
        "model": handle.model,
    }
