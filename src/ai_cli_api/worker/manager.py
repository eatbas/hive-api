from __future__ import annotations

import asyncio
import logging

from ..config import AppConfig, ProviderConfig
from ..models import ModelDetail, ProviderCapability, ProviderName, WorkerInfo
from ..providers.registry import build_provider_registry
from ..shells import detect_bash_path
from .warm_worker import WarmWorker

logger = logging.getLogger("ai_cli_api.worker")


class WorkerManager:
    def __init__(self, config: AppConfig):
        self.config = config
        self.shell_path = detect_bash_path(config.shell.path)
        self.registry = build_provider_registry()
        self.workers: dict[tuple[ProviderName, str], WarmWorker] = {}
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
                    "Provider %s: CLI '%s' not found -- skipping worker creation",
                    provider.value,
                    executable,
                )
                continue

            self.available_providers[provider] = True
            logger.info(
                "Provider %s: CLI '%s' found -- starting %d worker(s)",
                provider.value,
                executable,
                len(provider_config.models),
            )
            pending: list[tuple[tuple[ProviderName, str], WarmWorker]] = []
            for model in provider_config.models:
                worker = WarmWorker(
                    provider=provider,
                    model=model,
                    adapter=adapter,
                    executable=executable,
                    shell_path=self.shell_path,
                    default_options=provider_config.default_options,
                    session_models=self.session_models,
                )
                pending.append(((provider, model), worker))
            await asyncio.gather(*(w.start() for _, w in pending))
            for key, w in pending:
                self.workers[key] = w

    async def stop(self) -> None:
        await asyncio.gather(*(worker.stop() for worker in self.workers.values()), return_exceptions=True)

    def get_worker(self, provider: ProviderName, model: str) -> WarmWorker | None:
        return self.workers.get((provider, model))

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
        for (provider, model), worker in self.workers.items():
            adapter = self.registry[provider]
            details.append(
                ModelDetail(
                    provider=provider,
                    model=model,
                    ready=worker.ready,
                    busy=worker.busy,
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

    def worker_info(self) -> list[WorkerInfo]:
        return [worker.info() for worker in self.workers.values()]

    def workers_for_provider(self, provider: ProviderName) -> list[WarmWorker]:
        return [w for (p, _), w in self.workers.items() if p == provider]

    async def restart_provider(self, provider: ProviderName) -> None:
        workers = self.workers_for_provider(provider)
        await asyncio.gather(*(w.stop() for w in workers), return_exceptions=True)
        await asyncio.gather(*(w.start() for w in workers))

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
        logger.info("Provider %s: CLI now available at '%s' -- creating workers", provider.value, executable)
        for model in provider_config.models:
            if (provider, model) not in self.workers:
                worker = WarmWorker(
                    provider=provider,
                    model=model,
                    adapter=adapter,
                    executable=executable,
                    shell_path=self.shell_path,
                    default_options=provider_config.default_options,
                    session_models=self.session_models,
                )
                await worker.start()
                self.workers[(provider, model)] = worker
        return True

    def get_idle_worker(self, provider: ProviderName) -> WarmWorker | None:
        for worker in self.workers_for_provider(provider):
            if worker.ready and not worker.busy and worker.queue.qsize() == 0:
                return worker
        return None

    async def get_bash_version(self) -> str | None:
        for worker in self.workers.values():
            if worker.ready and not worker.busy and worker.queue.qsize() == 0:
                try:
                    _, output = await worker.run_quick_command("bash --version | head -1\n__ai_cli_exit=0")
                    return output.strip() if output.strip() else None
                except Exception:
                    return None
        return None

    def health_details(self) -> list[str]:
        details: list[str] = []
        for worker in self.workers.values():
            if worker.last_error:
                details.append(f"{worker.provider.value}/{worker.model}: {worker.last_error}")
        return details
