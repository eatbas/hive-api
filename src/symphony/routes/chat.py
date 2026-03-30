from __future__ import annotations

import json
from collections.abc import AsyncIterator

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse, StreamingResponse

from ..models import ChatRequest, ChatResponse, ErrorDetail, StopResponse
from ..models.enums import ScoreStatus
from ..orchestra import ScoreHandle
from ._deps import get_orchestra, get_ready_orchestra

router = APIRouter()

_TERMINAL_EVENTS = {"completed", "failed", "stopped"}


async def _stream_handle_events(handle: ScoreHandle) -> AsyncIterator[str]:
    _SCORE_TERMINAL = {ScoreStatus.COMPLETED, ScoreStatus.FAILED, ScoreStatus.STOPPED}
    try:
        while True:
            event = await handle.events.get()
            payload = dict(event)
            event_name = payload.pop("type")
            yield f"event: {event_name}\ndata: {json.dumps(payload)}\n\n"
            if event_name in _TERMINAL_EVENTS:
                break
    finally:
        # When the SSE client disconnects (e.g. the desktop app aborts the pipeline),
        # the async generator is closed.  If the score is still running, set the
        # cancelled flag so the musician's cancel watcher kills the CLI.
        if handle.status not in _SCORE_TERMINAL:
            handle.cancelled.set()


@router.post(
    "/v1/chat",
    tags=["Chat"],
    summary="Send a prompt to an AI instrument",
    response_model=ChatResponse,
    responses={
        404: {"description": "No musician configured for instrument/model.", "model": ErrorDetail},
        500: {"description": "Instrument CLI crashed or returned an unrecoverable error.", "model": ErrorDetail},
    },
)
async def chat(request: Request, body: ChatRequest) -> StreamingResponse | JSONResponse:
    orchestra = await get_ready_orchestra(request)

    if not orchestra.available_providers.get(body.provider, False):
        raise HTTPException(
            status_code=400,
            detail=(
                f"Instrument '{body.provider.value}' is not available. "
                f"The CLI is not installed or was not found on PATH."
            ),
        )

    musician = await orchestra.acquire_musician(body.provider, body.model)
    if musician is None:
        raise HTTPException(
            status_code=404,
            detail=f"No musician configured for instrument={body.provider.value} model={body.model}",
        )

    handle = await musician.submit(body)
    orchestra.register_score(handle)

    if body.stream:
        return StreamingResponse(
            _stream_handle_events(handle),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "Connection": "keep-alive"},
        )

    try:
        result = await handle.result_future
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    return JSONResponse(content=result.model_dump())


@router.post(
    "/v1/chat/{score_id}/stop",
    tags=["Chat"],
    summary="Stop a running or queued score",
    response_model=StopResponse,
    responses={
        404: {"description": "Score ID not found.", "model": ErrorDetail},
    },
)
async def stop_score(request: Request, score_id: str) -> StopResponse:
    orchestra = get_orchestra(request)
    handle = await orchestra.stop_score(score_id)
    if handle is None:
        raise HTTPException(status_code=404, detail=f"Score '{score_id}' not found")
    return StopResponse(
        score_id=score_id,
        status=handle.status,
        provider=handle.provider,
        model=handle.model,
    )
