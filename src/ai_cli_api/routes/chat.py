from __future__ import annotations

import json
from collections.abc import AsyncIterator

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse, StreamingResponse

from ..models import ChatRequest, ChatResponse, ErrorDetail
from ..worker import JobHandle
from ._deps import get_manager

router = APIRouter()


async def _stream_handle_events(handle: JobHandle) -> AsyncIterator[str]:
    while True:
        event = await handle.events.get()
        payload = dict(event)
        event_name = payload.pop("type")
        yield f"event: {event_name}\ndata: {json.dumps(payload)}\n\n"
        if event_name in {"completed", "failed"}:
            break


@router.post(
    "/v1/chat",
    tags=["Chat"],
    summary="Send a prompt to an AI provider",
    response_model=ChatResponse,
    responses={
        404: {"description": "No warm worker configured for provider/model.", "model": ErrorDetail},
        500: {"description": "Provider CLI crashed or returned an unrecoverable error.", "model": ErrorDetail},
    },
)
async def chat(request: Request, body: ChatRequest) -> StreamingResponse | JSONResponse:
    manager = get_manager(request)
    worker = manager.get_worker(body.provider, body.model)
    if worker is None:
        raise HTTPException(
            status_code=404,
            detail=f"No warm worker configured for provider={body.provider.value} model={body.model}",
        )

    handle = await worker.submit(body)
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
