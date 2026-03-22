from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter
from fastapi.responses import HTMLResponse

UI_INDEX = Path(__file__).resolve().parent.parent / "ui" / "index.html"

router = APIRouter(tags=["Console"])


@router.get(
    "/",
    response_class=HTMLResponse,
    summary="Web test console",
    description="Serves the built-in HTML console for interacting with workers in a browser.",
)
async def index() -> HTMLResponse:
    return HTMLResponse(UI_INDEX.read_text(encoding="utf-8"))
