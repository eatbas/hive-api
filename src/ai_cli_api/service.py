from __future__ import annotations

import json
from contextlib import asynccontextmanager
from pathlib import Path
from typing import AsyncIterator

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, JSONResponse, StreamingResponse

from .config import load_config
from .models import ChatRequest, HealthResponse
from .worker import WorkerManager

UI_INDEX = Path(__file__).with_name("ui") / "index.html"


async def _stream_handle_events(handle) -> AsyncIterator[str]:
    while True:
        event = await handle.events.get()
        payload = dict(event)
        event_name = payload.pop("type")
        yield f"event: {event_name}\ndata: {json.dumps(payload)}\n\n"
        if event_name in {"completed", "failed"}:
            break


def create_app() -> FastAPI:
    config = load_config()
    manager = WorkerManager(config)

    @asynccontextmanager
    async def lifespan(_: FastAPI):
        await manager.start()
        try:
            yield
        finally:
            await manager.stop()

    app = FastAPI(title="AI CLI API", lifespan=lifespan)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.state.config = config
    app.state.worker_manager = manager

    @app.get("/", response_class=HTMLResponse)
    async def index() -> HTMLResponse:
        return HTMLResponse(UI_INDEX.read_text(encoding="utf-8"))

    @app.get("/health")
    async def health() -> HealthResponse:
        details = manager.health_details()
        return HealthResponse(
            status="ok" if not details else "degraded",
            config_path=str(config.config_path),
            shell_path=manager.shell_path,
            workers_booted=all(worker.ready for worker in manager.workers.values()) if manager.workers else False,
            worker_count=len(manager.workers),
            details=details,
        )

    @app.get("/v1/providers")
    async def providers():
        return manager.capabilities()

    @app.get("/v1/workers")
    async def workers():
        return manager.worker_info()

    @app.post("/v1/chat")
    async def chat(request: ChatRequest):
        worker = manager.get_worker(request.provider, request.model)
        if worker is None:
            raise HTTPException(
                status_code=404,
                detail=f"No warm worker configured for provider={request.provider.value} model={request.model}",
            )

        handle = await worker.submit(request)
        if request.stream:
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

    return app
