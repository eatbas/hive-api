from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
import tomllib
from typing import Any

from .models import ProviderName


@dataclass(slots=True)
class ServerConfig:
    host: str = "127.0.0.1"
    port: int = 8000


@dataclass(slots=True)
class ShellConfig:
    path: str | None = None


@dataclass(slots=True)
class ProviderConfig:
    enabled: bool = True
    executable: str | None = None
    models: list[str] = field(default_factory=lambda: ["default"])
    default_options: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class UpdaterConfig:
    enabled: bool = True
    interval_hours: float = 4.0
    auto_update: bool = True


@dataclass(slots=True)
class AppConfig:
    server: ServerConfig
    shell: ShellConfig
    providers: dict[ProviderName, ProviderConfig]
    updater: UpdaterConfig
    config_path: Path


def _provider_config(raw: dict[str, Any] | None) -> ProviderConfig:
    raw = raw or {}
    models = [str(item) for item in raw.get("models", ["default"]) if str(item).strip()]
    return ProviderConfig(
        enabled=bool(raw.get("enabled", True)),
        executable=(str(raw["executable"]).strip() or None) if raw.get("executable") is not None else None,
        models=models or ["default"],
        default_options=dict(raw.get("default_options", {})),
    )


def _default_provider_map(raw: dict[str, Any]) -> dict[ProviderName, ProviderConfig]:
    provider_section = raw.get("providers", {})
    return {
        provider: _provider_config(provider_section.get(provider.value))
        for provider in ProviderName
    }


def load_config(path: str | os.PathLike[str] | None = None) -> AppConfig:
    config_path = Path(
        path
        or os.environ.get("AI_CLI_API_CONFIG")
        or Path.cwd() / "config.toml"
    )
    if not config_path.exists():
        raise FileNotFoundError(f"Config file not found: {config_path}")

    with config_path.open("rb") as handle:
        raw = tomllib.load(handle)

    server = raw.get("server", {})
    shell = raw.get("shell", {})
    updater = raw.get("updater", {})

    return AppConfig(
        server=ServerConfig(
            host=str(server.get("host", "127.0.0.1")),
            port=int(server.get("port", 8000)),
        ),
        shell=ShellConfig(
            path=(str(shell["path"]).strip() or None) if shell.get("path") is not None else None,
        ),
        providers=_default_provider_map(raw),
        updater=UpdaterConfig(
            enabled=bool(updater.get("enabled", True)),
            interval_hours=float(updater.get("interval_hours", 4.0)),
            auto_update=bool(updater.get("auto_update", True)),
        ),
        config_path=config_path,
    )
