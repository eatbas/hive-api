from __future__ import annotations

from typing import TYPE_CHECKING

from fastapi import Request

if TYPE_CHECKING:
    from ..updater import CLIUpdater
    from ..worker import WorkerManager


def get_manager(request: Request) -> WorkerManager:
    """Retrieve the WorkerManager from application state."""
    return request.app.state.worker_manager


def get_updater(request: Request) -> CLIUpdater:
    """Retrieve the CLIUpdater from application state."""
    return request.app.state.updater
