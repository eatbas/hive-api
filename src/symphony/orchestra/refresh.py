"""Hot-reload a provider's model list after a CLI update.

Called by the updater when model discovery detects that a CLI update
changed the available models.  Adjusts the Orchestra's musician pools
without requiring a full restart.
"""
from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING

from ..config import load_config
from ..models import InstrumentName

if TYPE_CHECKING:
    from .orchestra import Orchestra

logger = logging.getLogger("symphony.orchestra")


async def refresh_provider_models(
    orchestra: "Orchestra", provider: InstrumentName,
) -> bool:
    """Reload config for *provider* from disk and adjust musician pools.

    * Creates and starts musicians for newly discovered models.
    * Stops and removes musicians for models that no longer exist
      (only if they are idle — busy musicians are left running with
      a warning).
    * Updates the in-memory ``orchestra.config.providers[provider]``.

    Returns ``True`` if the model list changed.
    """
    fresh_config = load_config(orchestra.config.config_path)
    fresh_instrument = fresh_config.providers.get(provider)
    if fresh_instrument is None:
        return False

    current_instrument = orchestra.config.providers.get(provider)
    if current_instrument is None:
        return False

    old_models = set(current_instrument.models)
    new_models = set(fresh_instrument.models)

    if old_models == new_models:
        return False

    # Persist the updated config section in memory.
    orchestra.config.providers[provider] = fresh_instrument

    added = new_models - old_models
    removed = old_models - new_models

    adapter = orchestra.registry[provider]
    executable = adapter.resolve_executable(fresh_instrument.executable)

    # ------------------------------------------------------------------
    # Remove musicians for models that disappeared from the CLI.
    # ------------------------------------------------------------------
    for model in removed:
        key = (provider, model)
        pool = orchestra.musicians.get(key, [])
        busy = [m for m in pool if m.busy or m.queue.qsize() > 0]
        idle = [m for m in pool if m not in busy]

        if busy:
            logger.warning(
                "Model %s/%s removed but %d musician(s) still busy — "
                "deferring teardown until next restart",
                provider.value, model, len(busy),
            )

        await asyncio.gather(
            *(m.stop() for m in idle), return_exceptions=True,
        )

        if not busy:
            orchestra.musicians.pop(key, None)
            logger.info("Removed musician pool for %s/%s", provider.value, model)
        else:
            # Keep only the busy musicians in the pool.
            orchestra.musicians[key] = busy

    # ------------------------------------------------------------------
    # Create musicians for newly discovered models.
    # ------------------------------------------------------------------
    from .musician import Musician

    for model in sorted(added):
        key = (provider, model)
        if key in orchestra.musicians:
            continue
        musician = Musician(
            provider=provider,
            model=model,
            adapter=adapter,
            executable=executable,
            shell_path=orchestra.shell_path,
            default_options=fresh_instrument.default_options,
            session_models=orchestra.session_models,
            cli_timeout=fresh_instrument.cli_timeout,
            idle_timeout=fresh_instrument.idle_timeout,
        )
        await musician.start()
        orchestra.musicians[key] = [musician]
        logger.info("Created musician pool for %s/%s", provider.value, model)

    return True
