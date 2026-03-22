from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request

from ..models import CLIVersionStatus, ErrorDetail, ProviderName
from ._deps import get_updater

router = APIRouter(tags=["Updates"])


@router.get("/v1/cli-versions", summary="List CLI version statuses", response_model=list[CLIVersionStatus])
async def cli_versions(request: Request) -> list[CLIVersionStatus]:
    return get_updater(request).last_results


@router.post(
    "/v1/cli-versions/check",
    summary="Trigger an immediate version check",
    response_model=list[CLIVersionStatus],
)
async def cli_versions_check(request: Request) -> list[CLIVersionStatus]:
    return await get_updater(request).check_and_update_all()


@router.post(
    "/v1/cli-versions/{provider}/check",
    summary="Check a single CLI provider for updates",
    response_model=CLIVersionStatus,
    responses={404: {"description": "Unknown provider name.", "model": ErrorDetail}},
)
async def cli_version_check_single(request: Request, provider: ProviderName) -> CLIVersionStatus:
    result = await get_updater(request).check_single_provider(provider)
    if result is None:
        raise HTTPException(status_code=404, detail=f"Provider '{provider.value}' not found or not enabled")
    return result


@router.post(
    "/v1/cli-versions/{provider}/update",
    summary="Force-update a single CLI provider",
    response_model=CLIVersionStatus,
    responses={404: {"description": "Unknown provider name.", "model": ErrorDetail}},
)
async def cli_version_update(request: Request, provider: ProviderName) -> CLIVersionStatus:
    return await get_updater(request).update_single_provider(provider)
