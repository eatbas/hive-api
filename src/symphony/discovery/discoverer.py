"""Automatic model discovery — runs on every Symphony startup.

For each provider, attempts to discover available models by querying the
installed CLI.  Currently only OpenCode exposes a ``models`` subcommand;
all other providers keep whatever is already in ``config.toml``.

When a CLI gains model-listing support in the future, add a
``_discover_<provider>`` method here and it will be picked up
automatically on the next launch.
"""
from __future__ import annotations

import logging
import os
import re
import shutil
import subprocess
from pathlib import Path

from ..models import InstrumentName

logger = logging.getLogger("symphony.discovery")


# ---------------------------------------------------------------------------
# Per-provider discovery functions
# ---------------------------------------------------------------------------

def _discover_codex() -> list[str] | None:
    """Read ``~/.codex/models_cache.json`` for available Codex models.

    The Codex CLI fetches its model list from the OpenAI API and caches
    it locally.  We read that cache and return models with
    ``visibility == "list"`` (the ones shown in the CLI's model picker).

    Returns ``None`` if the cache file does not exist or is unreadable.
    """
    import json

    cache_path = Path.home() / ".codex" / "models_cache.json"
    if not cache_path.exists():
        return None

    try:
        data = json.loads(cache_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as exc:
        logger.warning("Failed to read Codex models cache: %s", exc)
        return None

    models: list[str] = []
    for entry in data.get("models", []):
        if entry.get("visibility") == "list":
            slug = entry.get("slug", "")
            if slug:
                models.append(slug)

    return models if models else None


def _discover_opencode() -> list[str] | None:
    """Run ``opencode models`` and return zai-coding-plan (GLM) model IDs only.

    OpenCode lists models from multiple providers (opencode/, zai-coding-plan/).
    We only include zai-coding-plan/ models here.  The prefix is stripped
    because the adapter re-adds it at runtime.

    Returns ``None`` if the CLI is not installed or discovery fails,
    signalling the caller to keep the existing config.
    """
    exe = shutil.which("opencode")
    if exe is None:
        return None

    try:
        result = subprocess.run(
            [exe, "models"],
            capture_output=True,
            text=True,
            timeout=15,
        )
    except (subprocess.TimeoutExpired, OSError) as exc:
        logger.warning("opencode models failed: %s", exc)
        return None

    models: list[str] = []
    for line in result.stdout.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        # Keep only zai-coding-plan/ GLM models.
        if stripped.startswith("zai-coding-plan/"):
            models.append(stripped.removeprefix("zai-coding-plan/"))
    return sorted(models) if models else None


# Registry: provider → discovery function.
# Add new entries here when a CLI gains model-listing support.
_DISCOVERERS: dict[InstrumentName, callable] = {
    InstrumentName.CODEX: _discover_codex,
    InstrumentName.OPENCODE: _discover_opencode,
}


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
    return [m.strip().strip('"').strip("'") for m in raw.split(",") if m.strip().strip('"').strip("'")]


def _format_models_toml(models: list[str]) -> str:
    """Format a models list as a TOML array string."""
    if len(models) <= 3:
        return "[" + ", ".join(f'"{m}"' for m in models) + "]"
    lines = ["["]
    for m in models:
        lines.append(f'  "{m}",')
    lines.append("]")
    return "\n".join(lines)


def _replace_models_in_toml(text: str, provider: str, new_models: list[str]) -> str:
    """Replace the models array for *provider* in raw TOML text."""
    pattern = rf'(\[providers\.{re.escape(provider)}\].*?models\s*=\s*)\[.*?\]'
    replacement = _format_models_toml(new_models)
    return re.sub(pattern, rf'\g<1>{replacement}', text, count=1, flags=re.DOTALL)


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

    for provider, discover_fn in _DISCOVERERS.items():
        provider_name = provider.value
        try:
            discovered = discover_fn()
        except Exception:
            logger.exception("Discovery failed for %s", provider_name)
            continue

        if discovered is None:
            logger.debug("No discovery result for %s — keeping config as-is", provider_name)
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
            updated_text = _replace_models_in_toml(updated_text, provider_name, discovered)
            changed = True
        else:
            logger.debug("Models for %s unchanged", provider_name)

    if changed:
        config_path.write_text(updated_text, encoding="utf-8")
        logger.info("config.toml updated with discovered models")

    return changed
