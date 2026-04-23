from __future__ import annotations

import json
from pathlib import Path
from typing import Any


_REASONING_LABELS = {
    "low": "Low",
    "medium": "Medium",
    "high": "High",
    "xhigh": "Extra high",
}

SUPPORTED_REASONING_EFFORTS = frozenset(_REASONING_LABELS)


def codex_model_options(model: str) -> list[dict[str, Any]]:
    entry = _find_model_entry(model)
    if entry is None:
        return []

    levels = entry.get("supported_reasoning_levels")
    if not isinstance(levels, list):
        return []

    choices: list[dict[str, str | None]] = []
    for item in levels:
        if not isinstance(item, dict):
            continue
        effort = item.get("effort")
        if not isinstance(effort, str) or not effort:
            continue
        description = item.get("description")
        choices.append(
            {
                "value": effort,
                "label": _REASONING_LABELS.get(effort, effort),
                "description": description if isinstance(description, str) else None,
            }
        )

    if not choices:
        return []

    default = entry.get("default_reasoning_level")
    return [
        {
            "key": "thinking_level",
            "label": "Thinking",
            "type": "select",
            "default": default if isinstance(default, str) else None,
            "choices": choices,
        }
    ]


def _find_model_entry(model: str) -> dict[str, Any] | None:
    data = _read_codex_models_cache()
    if data is None:
        return None

    entries = data.get("models")
    if not isinstance(entries, list):
        return None

    for entry in entries:
        if isinstance(entry, dict) and entry.get("slug") == model:
            return entry
    return None


def _read_codex_models_cache() -> dict[str, Any] | None:
    path = Path.home() / ".codex" / "models_cache.json"
    try:
        with path.open("r", encoding="utf-8") as handle:
            data = json.load(handle)
    except (OSError, json.JSONDecodeError):
        return None
    return data if isinstance(data, dict) else None
