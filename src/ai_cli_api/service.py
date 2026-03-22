from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from .config import load_config
from .routes import (
    _parse_generate_response,
    chat_router,
    console_router,
    providers_router,
    testlab_router,
    updates_router,
)
from .updater import CLIUpdater
from .worker import WorkerManager

logger = logging.getLogger("ai_cli_api.service")

UI_STATIC_DIR = Path(__file__).with_name("ui") / "static"

API_DESCRIPTION = """\
Warm-worker API wrapper for AI coding CLIs (Gemini, Codex, Claude, Kimi, Copilot, OpenCode).

The API maintains persistent warm workers for configured provider/model pairs,
enabling low-latency prompt execution without cold-start overhead.
"""

OPENAPI_TAGS = [
    {"name": "Health", "description": "System health and readiness checks."},
    {"name": "Providers", "description": "Query registered AI CLI providers and capabilities."},
    {"name": "Models", "description": "Discover configured models across providers."},
    {"name": "Workers", "description": "Inspect runtime state of warm worker processes."},
    {"name": "Chat", "description": "Submit prompts to AI providers with JSON or SSE responses."},
    {"name": "Updates", "description": "CLI version checking and auto-update management."},
    {"name": "Test Lab", "description": "Multi-model harness for NEW/RESUME verification workflows."},
    {"name": "Console", "description": "Built-in browser UI for interactive testing."},
]


def create_app() -> FastAPI:
    config = load_config()
    manager = WorkerManager(config)
    updater = CLIUpdater(manager=manager, config=config.updater)

    @asynccontextmanager
    async def lifespan(_: FastAPI):
        await manager.start()

        available = [p.value for p, ok in manager.available_providers.items() if ok]
        unavailable = [p.value for p, ok in manager.available_providers.items() if not ok]
        logger.info(
            "CLI availability: available=%s, unavailable=%s, workers=%d",
            available or "none",
            unavailable or "none",
            len(manager.workers),
        )

        updater.start()
        try:
            yield
        finally:
            await updater.stop()
            await manager.stop()

    app = FastAPI(
        title="AI CLI API",
        version="0.1.0",
        summary="Warm-worker API wrapper for AI coding CLIs",
        description=API_DESCRIPTION,
        openapi_tags=OPENAPI_TAGS,
        lifespan=lifespan,
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_methods=["*"],
        allow_headers=["*"],
    )

    app.state.config = config
    app.state.worker_manager = manager
    app.state.updater = updater

    app.mount("/static", StaticFiles(directory=UI_STATIC_DIR), name="static")

    @app.get("/health", tags=["Health"], summary="System health check")
    async def health():
        details = manager.health_details()
        bash_version = await manager.get_bash_version()
        return {
            "status": "ok" if not details else "degraded",
            "config_path": str(config.config_path),
            "shell_path": manager.shell_path,
            "bash_version": bash_version,
            "workers_booted": all(worker.ready for worker in manager.workers.values()) if manager.workers else False,
            "worker_count": len(manager.workers),
            "details": details,
        }

    app.include_router(console_router)
    app.include_router(providers_router)
    app.include_router(chat_router)
    app.include_router(updates_router)
    app.include_router(testlab_router)

    return app


__all__ = ["create_app", "_parse_generate_response"]
