from __future__ import annotations

from fastapi import APIRouter, Query, Request

from ..models import ModelDetail, ProviderCapability, MusicianInfo
from ._deps import get_ready_orchestra

router = APIRouter()


@router.get(
    "/v1/providers",
    tags=["Providers"],
    summary="List instrument capabilities",
    description="Returns only instruments whose CLI is installed and available. Pass `?all=true` to include unavailable ones.",
    response_model=list[ProviderCapability],
)
async def providers(
    request: Request,
    all: bool = Query(False, description="Include unavailable instruments"),
) -> list[ProviderCapability]:
    orchestra = await get_ready_orchestra(request)
    caps = orchestra.capabilities()
    if all:
        return caps
    return [c for c in caps if c.available]


@router.get(
    "/v1/models",
    tags=["Models"],
    summary="List all supported models with chat examples",
    response_model=list[ModelDetail],
)
async def models(request: Request) -> list[ModelDetail]:
    orchestra = await get_ready_orchestra(request)
    return orchestra.model_details()


@router.get(
    "/v1/musicians",
    tags=["Musicians"],
    summary="List active musicians",
    response_model=list[MusicianInfo],
)
async def musicians(request: Request) -> list[MusicianInfo]:
    orchestra = await get_ready_orchestra(request)
    return orchestra.musician_info()
