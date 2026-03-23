from __future__ import annotations

import asyncio
import logging

from ..config import AppConfig, ProviderConfig
from ..models import ModelDetail, ProviderCapability, ProviderName, DroneInfo
from ..providers.base import set_bash_path
from ..providers.registry import build_provider_registry
from ..shells import detect_bash_path
from .drone import Drone

logger = logging.getLogger("hive_api.colony")


class Colony:
    def __init__(self, config: AppConfig):
        self.config = config
        self.shell_path = detect_bash_path(config.shell.path)
        # Let the CLI smoke-test use the same Git Bash as the drones.
        set_bash_path(self.shell_path)
        self.registry = build_provider_registry()
        self.drones: dict[tuple[ProviderName, str], Drone] = {}
        self.session_models: dict[tuple[ProviderName, str], str] = {}
        self.available_providers: dict[ProviderName, bool] = {}

    async def start(self) -> None:
        for provider, provider_config in self.config.providers.items():
            if not provider_config.enabled:
                self.available_providers[provider] = False
                logger.info("Provider %s: disabled by configuration", provider.value)
                continue

            adapter = self.registry[provider]
            executable = adapter.resolve_executable(provider_config.executable)

            if not adapter.is_available(provider_config.executable):
                self.available_providers[provider] = False
                logger.warning(
                    "Provider %s: CLI '%s' not found -- skipping drone creation",
                    provider.value,
                    executable,
                )
                continue

            self.available_providers[provider] = True
            logger.info(
                "Provider %s: CLI '%s' found -- starting %d drone(s)",
                provider.value,
                executable,
                len(provider_config.models),
            )
            pending: list[tuple[tuple[ProviderName, str], Drone]] = []
            for model in provider_config.models:
                drone = Drone(
                    provider=provider,
                    model=model,
                    adapter=adapter,
                    executable=executable,
                    shell_path=self.shell_path,
                    default_options=provider_config.default_options,
                    session_models=self.session_models,
                    cli_timeout=provider_config.cli_timeout,
                )
                pending.append(((provider, model), drone))
            await asyncio.gather(*(w.start() for _, w in pending))
            for key, w in pending:
                self.drones[key] = w

    async def stop(self) -> None:
        await asyncio.gather(*(drone.stop() for drone in self.drones.values()), return_exceptions=True)

    def get_drone(self, provider: ProviderName, model: str) -> Drone | None:
        return self.drones.get((provider, model))

    def capabilities(self) -> list[ProviderCapability]:
        capabilities: list[ProviderCapability] = []
        for provider, adapter in self.registry.items():
            provider_config: ProviderConfig = self.config.providers[provider]
            capabilities.append(
                ProviderCapability(
                    provider=provider,
                    executable=adapter.resolve_executable(provider_config.executable),
                    enabled=provider_config.enabled,
                    available=self.available_providers.get(provider, False),
                    models=provider_config.models,
                    supports_resume=adapter.supports_resume,
                    supports_streaming=adapter.supports_streaming,
                    supports_model_override=adapter.supports_model_override,
                    session_reference_format=adapter.session_reference_format,
                )
            )
        return capabilities

    def model_details(self) -> list[ModelDetail]:
        details: list[ModelDetail] = []
        for (provider, model), drone in self.drones.items():
            adapter = self.registry[provider]
            details.append(
                ModelDetail(
                    provider=provider,
                    model=model,
                    ready=drone.ready,
                    busy=drone.busy,
                    supports_resume=adapter.supports_resume,
                    chat_request_example={
                        "provider": provider.value,
                        "model": model,
                        "workspace_path": "/path/to/your/project",
                        "mode": "new",
                        "prompt": "Your prompt here",
                        "stream": True,
                    },
                )
            )
        return details

    def drone_info(self) -> list[DroneInfo]:
        return [drone.info() for drone in self.drones.values()]

    def drones_for_provider(self, provider: ProviderName) -> list[Drone]:
        return [w for (p, _), w in self.drones.items() if p == provider]

    async def restart_provider(self, provider: ProviderName) -> None:
        drones = self.drones_for_provider(provider)
        await asyncio.gather(*(w.stop() for w in drones), return_exceptions=True)
        await asyncio.gather(*(w.start() for w in drones))

    async def activate_provider(self, provider: ProviderName) -> bool:
        if self.available_providers.get(provider, False):
            return True

        provider_config = self.config.providers.get(provider)
        if provider_config is None or not provider_config.enabled:
            return False

        adapter = self.registry[provider]
        if not adapter.is_available(provider_config.executable):
            return False

        executable = adapter.resolve_executable(provider_config.executable)
        self.available_providers[provider] = True
        logger.info("Provider %s: CLI now available at '%s' -- creating drones", provider.value, executable)
        for model in provider_config.models:
            if (provider, model) not in self.drones:
                drone = Drone(
                    provider=provider,
                    model=model,
                    adapter=adapter,
                    executable=executable,
                    shell_path=self.shell_path,
                    default_options=provider_config.default_options,
                    session_models=self.session_models,
                    cli_timeout=provider_config.cli_timeout,
                )
                await drone.start()
                self.drones[(provider, model)] = drone
        return True

    def get_idle_drone(self, provider: ProviderName) -> Drone | None:
        for drone in self.drones_for_provider(provider):
            if drone.ready and not drone.busy and drone.queue.qsize() == 0:
                return drone
        return None

    async def get_bash_version(self) -> str | None:
        for drone in self.drones.values():
            if drone.ready and not drone.busy and drone.queue.qsize() == 0:
                try:
                    _, output = await drone.run_quick_command("bash --version | head -1\n__hive_exit=0")
                    return output.strip() if output.strip() else None
                except Exception:
                    return None
        return None

    def health_details(self) -> list[str]:
        details: list[str] = []
        for drone in self.drones.values():
            if drone.last_error:
                details.append(f"{drone.provider.value}/{drone.model}: {drone.last_error}")
        return details
