from __future__ import annotations

from collections.abc import Iterable

from ..config import AppConfig
from ..models import InstrumentName, ModelDetail, MusicianInfo, ProviderCapability
from ..providers.base import ProviderAdapter
from .musician import Musician


def build_capabilities(
    *,
    config: AppConfig,
    registry: dict[InstrumentName, ProviderAdapter],
    available_providers: dict[InstrumentName, bool],
) -> list[ProviderCapability]:
    capabilities: list[ProviderCapability] = []
    for instrument, adapter in registry.items():
        instrument_config = config.providers[instrument]
        capabilities.append(
            ProviderCapability(
                provider=instrument,
                executable=adapter.resolve_executable(instrument_config.executable),
                enabled=instrument_config.enabled,
                available=available_providers.get(instrument, False),
                models=instrument_config.models,
                supports_resume=adapter.supports_resume,
                supports_model_override=adapter.supports_model_override,
                session_reference_format=adapter.session_reference_format,
            )
        )
    return capabilities


def build_model_details(
    *,
    musicians: Iterable[Musician],
    registry: dict[InstrumentName, ProviderAdapter],
) -> list[ModelDetail]:
    details: list[ModelDetail] = []
    seen: set[tuple[InstrumentName, str]] = set()
    for musician in musicians:
        key = (musician.provider, musician.model)
        if key in seen:
            continue
        seen.add(key)
        adapter = registry[musician.provider]
        details.append(
            ModelDetail(
                provider=musician.provider,
                model=musician.model,
                ready=musician.ready,
                busy=musician.busy,
                supports_resume=adapter.supports_resume,
                provider_options_schema=adapter.model_option_schema(musician.model),
                chat_request_example={
                    "provider": musician.provider.value,
                    "model": musician.model,
                    "workspace_path": "/path/to/your/project",
                    "mode": "new",
                    "prompt": "Your prompt here",
                    "provider_options": {},
                },
            )
        )
    return details


def build_musician_info(musicians: Iterable[Musician]) -> list[MusicianInfo]:
    return [musician.info() for musician in musicians]


def build_health_details(musicians: Iterable[Musician]) -> list[str]:
    return [
        f"{musician.provider.value}/{musician.model}: {musician.last_error}"
        for musician in musicians
        if musician.last_error
    ]
