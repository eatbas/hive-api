from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta, timezone

from ..config import UpdaterConfig
from ..discovery import discover_provider
from ..models import CLIVersionStatus, InstrumentName
from ..orchestra import Orchestra, refresh_provider_models
from . import lifecycle
from .registry import CLIPackageInfo, PACKAGE_REGISTRY, needs_update as _needs_update
from .single_provider import update_single_provider_impl
from .update_runner import run_update
from .version_checker import (
    get_current_version,
    get_latest_version,
    run_cmd,
    set_bash_path,
)

logger = logging.getLogger("symphony.updater")


class CLIUpdater:
    """Periodically checks CLI versions and auto-updates when musicians are idle."""

    def __init__(self, manager: Orchestra, config: UpdaterConfig) -> None:
        self.manager = manager
        self.config = config
        self._last_results: list[CLIVersionStatus] = []
        self._task: asyncio.Task[None] | None = None
        self._discovery_lock = asyncio.Lock()
        # Ensure the subprocess fallback also uses Git Bash.
        set_bash_path(manager.shell_path)

    async def _run_cmd(self, *args: str, timeout: int = 60) -> tuple[int, str]:
        return await run_cmd(*args, timeout=timeout)

    async def get_current_version(self, executable: str, provider: InstrumentName | None = None) -> str | None:
        return await get_current_version(
            manager=self.manager,
            runner=self._run_cmd,
            executable=executable,
            provider=provider,
        )

    async def get_latest_version(self, pkg_info: CLIPackageInfo) -> str | None:
        return await get_latest_version(manager=self.manager, runner=self._run_cmd, pkg_info=pkg_info)

    def is_provider_idle(self, provider: InstrumentName) -> bool:
        musicians = self.manager.musicians_for_provider(provider)
        if not musicians:
            return True
        return all(not m.busy and m.queue.qsize() == 0 for m in musicians)

    async def update_cli(self, pkg_info: CLIPackageInfo, *, executable: str | None = None) -> bool:
        return await run_update(
            manager=self.manager,
            run_cmd=self._run_cmd,
            pkg_info=pkg_info,
            executable=executable,
        )

    async def _rediscover_models(self, provider: InstrumentName) -> None:
        """Run model discovery for *provider* after a successful CLI update.

        Serialised via ``_discovery_lock`` to prevent concurrent
        config.toml writes when multiple providers update in parallel.
        """
        async with self._discovery_lock:
            config_path = self.manager.config.config_path
            changed = await asyncio.to_thread(discover_provider, provider, config_path)
        if changed:
            refreshed = await refresh_provider_models(self.manager, provider)
            if refreshed:
                logger.info("Models refreshed for %s after CLI update", provider.value)

    def _next_check_at(self) -> str:
        return (datetime.now(timezone.utc) + timedelta(hours=self.config.interval_hours)).isoformat()

    def _build_status(
        self,
        *,
        provider: InstrumentName,
        executable: str | None,
        current_version: str | None,
        latest_version: str | None,
        needs_update: bool,
        now: str,
        next_check: str,
        last_updated: str | None = None,
        skip_reason: str | None = None,
    ) -> CLIVersionStatus:
        return CLIVersionStatus(
            provider=provider,
            executable=executable,
            current_version=current_version,
            latest_version=latest_version,
            needs_update=needs_update,
            last_checked=now,
            next_check_at=next_check,
            auto_update=self.config.auto_update,
            last_updated=last_updated,
            update_skipped_reason=skip_reason,
        )

    def _available_providers(self) -> list[InstrumentName]:
        return [
            p
            for p in self.manager.config.providers
            if self.manager.config.providers[p].enabled
            and self.manager.available_providers.get(p, False)
        ]

    def _resolve_provider_context(
        self, provider: InstrumentName
    ) -> tuple[object, str | None, CLIPackageInfo] | None:
        """Return ``(adapter, executable, pkg_info)`` if all three are
        available, else ``None``. Pure dict lookups — no I/O, safe to
        call repeatedly."""
        provider_config = self.manager.config.providers.get(provider)
        if provider_config is None or not provider_config.enabled:
            return None
        adapter = self.manager.registry.get(provider)
        if adapter is None:
            return None
        executable = adapter.resolve_executable(provider_config.executable)
        pkg_info = PACKAGE_REGISTRY.get(adapter.default_executable)
        if pkg_info is None:
            return None
        return adapter, executable, pkg_info

    async def _probe_single_provider(
        self, provider: InstrumentName, now: str, next_check: str
    ) -> CLIVersionStatus | None:
        """Run the version probe for *provider* without ever installing.

        Used by the lazy GET path so the first response arrives in
        seconds, and reused by ``_check_single_provider`` so the install
        path inherits the same probe logic instead of duplicating it."""
        ctx = self._resolve_provider_context(provider)
        if ctx is None:
            return None
        adapter, executable, pkg_info = ctx
        resolved_exe = executable or adapter.default_executable

        current, latest = await asyncio.gather(
            self.get_current_version(resolved_exe, provider),
            self.get_latest_version(pkg_info),
        )

        update_needed = _needs_update(current, latest)
        skip_reason = (
            "auto_update disabled"
            if update_needed and not self.config.auto_update
            else None
        )

        return self._build_status(
            provider=provider,
            executable=executable,
            current_version=current,
            latest_version=latest,
            needs_update=update_needed,
            now=now,
            next_check=next_check,
            skip_reason=skip_reason,
        )

    async def _check_single_provider(
        self, provider: InstrumentName, now: str, next_check: str
    ) -> CLIVersionStatus | None:
        probe = await self._probe_single_provider(provider, now, next_check)
        if probe is None or not probe.needs_update or not self.config.auto_update:
            return probe

        ctx = self._resolve_provider_context(provider)
        assert ctx is not None  # probe would have returned None otherwise
        adapter, executable, pkg_info = ctx
        resolved_exe = executable or adapter.default_executable

        if not self.is_provider_idle(provider):
            logger.warning("Skipping update for %s: musicians are busy", provider.value)
            return self._build_status(
                provider=provider,
                executable=executable,
                current_version=probe.current_version,
                latest_version=probe.latest_version,
                needs_update=True,
                now=now,
                next_check=next_check,
                skip_reason="musicians busy",
            )

        success = await self.update_cli(pkg_info, executable=resolved_exe)
        if not success:
            return self._build_status(
                provider=provider,
                executable=executable,
                current_version=probe.current_version,
                latest_version=probe.latest_version,
                needs_update=True,
                now=now,
                next_check=next_check,
                skip_reason="update command failed",
            )

        await self.manager.restart_provider(provider)
        await self.manager.activate_provider(provider)
        await self._rediscover_models(provider)
        current = await self.get_current_version(resolved_exe, provider)
        return self._build_status(
            provider=provider,
            executable=executable,
            current_version=current,
            latest_version=probe.latest_version,
            needs_update=_needs_update(current, probe.latest_version),
            now=now,
            next_check=next_check,
            last_updated=datetime.now(timezone.utc).isoformat(),
        )

    async def check_single_provider(self, provider: InstrumentName) -> CLIVersionStatus | None:
        now = datetime.now(timezone.utc).isoformat()
        next_check = self._next_check_at()
        result = await self._check_single_provider(provider, now, next_check)
        if result is not None:
            self._cache_single(result)
        return result

    async def probe_versions_only(self) -> list[CLIVersionStatus]:
        """Parallel version probes for every available provider — no installs.

        Returns in seconds rather than minutes, so it is safe to call
        from request paths. Auto-updates run via :meth:`_periodic_loop`,
        never inside the request that triggers this method."""
        now = datetime.now(timezone.utc).isoformat()
        next_check = self._next_check_at()
        providers = self._available_providers()
        probe_results = await asyncio.gather(
            *(self._probe_single_provider(p, now, next_check) for p in providers)
        )
        results = [r for r in probe_results if r is not None]
        self._last_results = results
        return results

    async def check_and_update_all(self) -> list[CLIVersionStatus]:
        now = datetime.now(timezone.utc).isoformat()
        next_check = self._next_check_at()
        providers = self._available_providers()
        check_results = await asyncio.gather(
            *(self._check_single_provider(p, now, next_check) for p in providers)
        )
        results = [r for r in check_results if r is not None]
        self._last_results = results
        return results

    async def update_single_provider(self, provider: InstrumentName) -> CLIVersionStatus:
        return await update_single_provider_impl(self, provider)

    def _cache_single(self, result: CLIVersionStatus) -> None:
        self._last_results = [result if r.provider == result.provider else r for r in self._last_results]
        if not any(r.provider == result.provider for r in self._last_results):
            self._last_results.append(result)

    def start(self) -> None:
        lifecycle.start(self)

    async def stop(self) -> None:
        await lifecycle.stop(self)

    @property
    def last_results(self) -> list[CLIVersionStatus]:
        return list(self._last_results)
