from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from ..models import InstrumentName
from .musician import Musician

if TYPE_CHECKING:
    from .orchestra import Orchestra

logger = logging.getLogger("symphony.orchestra")


async def activate_provider(orchestra: "Orchestra", provider: InstrumentName) -> bool:
    if orchestra.available_providers.get(provider, False):
        return True

    instrument_config = orchestra.config.providers.get(provider)
    if instrument_config is None or not instrument_config.enabled:
        return False

    adapter = orchestra.registry[provider]
    if not adapter.is_available(instrument_config.executable):
        return False

    executable = adapter.resolve_executable(instrument_config.executable)
    orchestra.available_providers[provider] = True
    logger.info(
        "Instrument %s: CLI now available at '%s' -- creating musicians",
        provider.value,
        executable,
    )
    for model in instrument_config.models:
        if (provider, model) not in orchestra.musicians:
            musician = Musician(
                provider=provider,
                model=model,
                adapter=adapter,
                executable=executable,
                shell_path=orchestra.shell_path,
                default_options=instrument_config.default_options,
                session_models=orchestra.session_models,
                cli_timeout=instrument_config.cli_timeout,
                idle_timeout=instrument_config.idle_timeout,
            )
            await musician.start()
            orchestra.musicians[(provider, model)] = [musician]
    return True
