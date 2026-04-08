"""Automatic model discovery — runs on every Symphony startup.

For each provider, attempts to discover available models by querying the
installed CLI, reading local caches, or calling the provider's API using
locally-stored credentials.

Discovery functions live in ``providers.py``.  When a provider gains a
new discovery mechanism, update or add a function there and register it
in ``DISCOVERERS``.
"""
from __future__ import annotations

import logging
import os
import re
from pathlib import Path

from .providers import DISCOVERERS

logger = logging.getLogger("symphony.discovery")


# ---------------------------------------------------------------------------
# config.toml update helpers
# ---------------------------------------------------------------------------


def _parse_models_from_toml(text: str, provider: str) -> list[str]:
    """Extract the models array for *provider* from raw TOML text."""
    pattern = rf'\[providers\.{re.escape(provider)}\].*?models\s*=\s*\[(.*?)\]'
    match = re.search(pattern, text, re.DOTALL)
    if not match:
        return []
    raw = match.group(1)
    return [
        m.strip().strip('"').strip("'")
        for m in raw.split(",")
        if m.strip().strip('"').strip("'")
    ]


def _format_models_toml(models: list[str]) -> str:
    """Format a models list as a TOML array string."""
    if len(models) <= 3:
        return "[" + ", ".join(f'"{m}"' for m in models) + "]"
    lines = ["["]
    for m in models:
        lines.append(f'  "{m}",')
    lines.append("]")
    return "\n".join(lines)


def _replace_models_in_toml(
    text: str, provider: str, new_models: list[str],
) -> str:
    """Replace the models array for *provider* in raw TOML text."""
    pattern = rf'(\[providers\.{re.escape(provider)}\].*?models\s*=\s*)\[.*?\]'
    replacement = _format_models_toml(new_models)
    return re.sub(
        pattern, rf'\g<1>{replacement}', text, count=1, flags=re.DOTALL,
    )


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def run_startup_discovery(config_path: Path) -> bool:
    """Discover models for all providers and update ``config.toml``.

    Called once during ``create_app()`` before the Orchestra is built.
    Returns ``True`` if config.toml was modified.

    Providers without a registered discovery function are left unchanged.
    If discovery returns ``None`` (CLI missing or errored), the existing
    config models are preserved.

    Set ``SYMPHONY_SKIP_DISCOVERY=1`` to disable (used in tests).
    """
    if os.environ.get("SYMPHONY_SKIP_DISCOVERY"):
        return False

    if not config_path.exists():
        return False

    text = config_path.read_text(encoding="utf-8")
    updated_text = text
    changed = False

    for provider, discover_fn in DISCOVERERS.items():
        provider_name = provider.value
        try:
            discovered = discover_fn()
        except Exception:
            logger.exception("Discovery failed for %s", provider_name)
            continue

        if discovered is None:
            logger.debug(
                "No discovery result for %s — keeping config as-is",
                provider_name,
            )
            continue

        current = _parse_models_from_toml(updated_text, provider_name)
        if set(discovered) != set(current):
            added = set(discovered) - set(current)
            removed = set(current) - set(discovered)
            logger.info(
                "Model update for %s: +%s -%s",
                provider_name,
                list(added) if added else "none",
                list(removed) if removed else "none",
            )
            updated_text = _replace_models_in_toml(
                updated_text, provider_name, discovered,
            )
            changed = True
        else:
            logger.debug("Models for %s unchanged", provider_name)

    if changed:
        config_path.write_text(updated_text, encoding="utf-8")
        logger.info("config.toml updated with discovered models")

    return changed
