from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request

from ..models import CLIVersionStatus, ErrorDetail, ProviderName
from ._deps import get_colony, get_updater

router = APIRouter(tags=["Updates"])


def _require_available(request: Request, provider: ProviderName) -> None:
    """Raise 400 if the provider's CLI is not installed."""
    colony = get_colony(request)
    if not colony.available_providers.get(provider, False):
        raise HTTPException(
            status_code=400,
            detail=f"Provider '{provider.value}' is not available. CLI not installed.",
        )


@router.get("/v1/cli-versions", summary="List CLI version statuses", response_model=list[CLIVersionStatus])
async def cli_versions(request: Request) -> list[CLIVersionStatus]:
    colony = get_colony(request)
    available = {p for p, ok in colony.available_providers.items() if ok}
    return [r for r in get_updater(request).last_results if r.provider in available]


@router.post(
    "/v1/cli-versions/check",
    summary="Trigger an immediate version check",
    response_model=list[CLIVersionStatus],
)
async def cli_versions_check(request: Request) -> list[CLIVersionStatus]:
    colony = get_colony(request)
    available = {p for p, ok in colony.available_providers.items() if ok}
    results = await get_updater(request).check_and_update_all()
    return [r for r in results if r.provider in available]


@router.post(
    "/v1/cli-versions/{provider}/check",
    summary="Check a single CLI provider for updates",
    response_model=CLIVersionStatus,
    responses={
        400: {"description": "Provider CLI not installed.", "model": ErrorDetail},
        404: {"description": "Unknown provider name.", "model": ErrorDetail},
    },
)
async def cli_version_check_single(request: Request, provider: ProviderName) -> CLIVersionStatus:
    _require_available(request, provider)
    result = await get_updater(request).check_single_provider(provider)
    if result is None:
        raise HTTPException(status_code=404, detail=f"Provider '{provider.value}' not found or not enabled")
    return result


@router.post(
    "/v1/cli-versions/{provider}/update",
    summary="Force-update a single CLI provider",
    response_model=CLIVersionStatus,
    responses={
        400: {"description": "Provider CLI not installed.", "model": ErrorDetail},
        404: {"description": "Unknown provider name.", "model": ErrorDetail},
    },
)
async def cli_version_update(request: Request, provider: ProviderName) -> CLIVersionStatus:
    _require_available(request, provider)
    return await get_updater(request).update_single_provider(provider)
