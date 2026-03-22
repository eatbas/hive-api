from __future__ import annotations

from fastapi import APIRouter, Request

from ..models import ModelDetail, ProviderCapability, WorkerInfo
from ._deps import get_manager

router = APIRouter()


@router.get(
    "/v1/providers",
    tags=["Providers"],
    summary="List provider capabilities",
    response_model=list[ProviderCapability],
)
async def providers(request: Request) -> list[ProviderCapability]:
    return get_manager(request).capabilities()


@router.get(
    "/v1/models",
    tags=["Models"],
    summary="List all supported models with chat examples",
    response_model=list[ModelDetail],
)
async def models(request: Request) -> list[ModelDetail]:
    return get_manager(request).model_details()


@router.get(
    "/v1/workers",
    tags=["Workers"],
    summary="List active workers",
    response_model=list[WorkerInfo],
)
async def workers(request: Request) -> list[WorkerInfo]:
    return get_manager(request).worker_info()
