from __future__ import annotations

import asyncio
import logging
import os
import re
import subprocess
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from .config import UpdaterConfig
from .models import CLIVersionStatus, ProviderName
from .worker import WorkerManager

logger = logging.getLogger("ai_cli_api.updater")

_VERSION_RE = re.compile(r"(\d+\.\d+\.\d+)")
_CMD_TIMEOUT = 60


@dataclass(slots=True)
class CLIPackageInfo:
    provider: ProviderName
    manager: str   # "npm" or "uv"
    package: str   # registry package name


PACKAGE_REGISTRY: dict[str, CLIPackageInfo] = {
    "claude": CLIPackageInfo(ProviderName.CLAUDE, "npm", "@anthropic-ai/claude-code"),
    "codex":  CLIPackageInfo(ProviderName.CODEX,  "npm", "@openai/codex"),
    "gemini": CLIPackageInfo(ProviderName.GEMINI, "npm", "@google/gemini-cli"),
    "kimi":   CLIPackageInfo(ProviderName.KIMI,   "uv",  "kimi-cli"),
}


def _parse_version(text: str) -> str | None:
    """Extract the first semver-like version string from *text*."""
    match = _VERSION_RE.search(text)
    return match.group(1) if match else None


def _version_tuple(version: str) -> tuple[int, ...]:
    """Convert ``'1.2.3'`` to ``(1, 2, 3)`` for comparison."""
    return tuple(int(part) for part in version.split("."))


class CLIUpdater:
    """Periodically checks CLI versions and auto-updates when workers are idle."""

    def __init__(
        self,
        manager: WorkerManager,
        config: UpdaterConfig,
    ) -> None:
        self.manager = manager
        self.config = config
        self._last_results: list[CLIVersionStatus] = []
        self._task: asyncio.Task[None] | None = None

    # ------------------------------------------------------------------
    # Subprocess helper
    # ------------------------------------------------------------------

    async def _run_cmd(self, *args: str, timeout: int = _CMD_TIMEOUT) -> tuple[int, str]:
        """Run a command and return ``(exit_code, stdout)``."""
        kwargs: dict = {}
        if os.name == "nt":
            kwargs["creationflags"] = subprocess.CREATE_NO_WINDOW
        try:
            proc = await asyncio.create_subprocess_exec(
                *args,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.STDOUT,
                **kwargs,
            )
            stdout_bytes, _ = await asyncio.wait_for(proc.communicate(), timeout=timeout)
            return proc.returncode or 0, stdout_bytes.decode("utf-8", errors="replace").strip()
        except asyncio.TimeoutError:
            logger.warning("Command timed out: %s", " ".join(args))
            return -1, ""
        except FileNotFoundError:
            return -1, ""

    # ------------------------------------------------------------------
    # Version detection
    # ------------------------------------------------------------------

    async def get_current_version(self, executable: str, provider: ProviderName | None = None) -> str | None:
        # Prefer using an existing warm worker shell if one is idle
        if provider is not None:
            worker = self.manager.get_idle_worker(provider)
            if worker is not None and worker.ready:
                try:
                    code, output = await worker.run_quick_command(
                        f"{executable} --version 2>&1\n__ai_cli_exit=$?"
                    )
                    if code == 0 and output:
                        version = _parse_version(output)
                        if version:
                            return version
                except Exception:
                    logger.debug("Shell version check failed for %s, falling back", executable)

        # Fallback: spawn a new subprocess
        code, output = await self._run_cmd(executable, "--version")
        if code != 0:
            logger.warning("Failed to get version for %s (exit %d)", executable, code)
            return None
        return _parse_version(output)

    async def get_latest_version(self, pkg_info: CLIPackageInfo) -> str | None:
        # Try using a warm worker shell first (npm/uv may not be on the
        # uvicorn process PATH but are available inside Git Bash).
        worker = self.manager.get_idle_worker(pkg_info.provider)
        if worker is not None and worker.ready:
            try:
                result = await self._get_latest_version_via_shell(worker, pkg_info)
                if result:
                    return result
            except Exception:
                logger.debug("Shell latest-version check failed for %s, falling back", pkg_info.package)

        # Fallback: spawn a new subprocess
        return await self._get_latest_version_subprocess(pkg_info)

    async def _get_latest_version_via_shell(self, worker, pkg_info: CLIPackageInfo) -> str | None:
        if pkg_info.manager == "npm":
            code, output = await worker.run_quick_command(
                f"npm view {pkg_info.package} version 2>&1\n__ai_cli_exit=$?"
            )
            if code == 0 and output:
                return _parse_version(output)
        elif pkg_info.manager == "uv":
            code, output = await worker.run_quick_command(
                "uv tool list 2>&1\n__ai_cli_exit=$?"
            )
            if code == 0 and output:
                for line in output.splitlines():
                    if pkg_info.package in line:
                        return _parse_version(line)
        return None

    async def _get_latest_version_subprocess(self, pkg_info: CLIPackageInfo) -> str | None:
        if pkg_info.manager == "npm":
            code, output = await self._run_cmd("npm", "view", pkg_info.package, "version")
            if code != 0:
                logger.warning("npm view failed for %s (exit %d)", pkg_info.package, code)
                return None
            return _parse_version(output)

        if pkg_info.manager == "uv":
            code, output = await self._run_cmd("uv", "tool", "list")
            if code != 0:
                logger.warning("uv tool list failed (exit %d)", code)
                return None
            for line in output.splitlines():
                if pkg_info.package in line:
                    return _parse_version(line)
            logger.warning("Package %s not found in uv tool list", pkg_info.package)
            return None

        return None

    # ------------------------------------------------------------------
    # Idle check
    # ------------------------------------------------------------------

    def is_provider_idle(self, provider: ProviderName) -> bool:
        workers = self.manager.workers_for_provider(provider)
        if not workers:
            return True
        return all(
            not worker.busy and worker.queue.qsize() == 0
            for worker in workers
        )

    # ------------------------------------------------------------------
    # Update
    # ------------------------------------------------------------------

    async def update_cli(self, pkg_info: CLIPackageInfo) -> bool:
        logger.info("Updating %s (%s) …", pkg_info.package, pkg_info.manager)

        if pkg_info.manager == "npm":
            cmd_str = f"npm install -g {pkg_info.package}@latest 2>&1\n__ai_cli_exit=$?"
        elif pkg_info.manager == "uv":
            cmd_str = f"uv tool upgrade {pkg_info.package} --no-cache 2>&1\n__ai_cli_exit=$?"
        else:
            return False

        # Try warm worker shell first (npm/uv are on Git Bash PATH)
        worker = self.manager.get_idle_worker(pkg_info.provider)
        if worker is not None and worker.ready:
            try:
                code, output = await worker.run_quick_command(cmd_str, timeout=120)
                if code == 0:
                    logger.info("Successfully updated %s", pkg_info.package)
                    return True
                logger.error("Update failed for %s (shell): %s", pkg_info.package, output)
                return False
            except asyncio.TimeoutError:
                logger.warning("Shell update timed out for %s, restarting worker shell", pkg_info.package)
                # Timeout leaves the shell in an undefined state; restart it
                await worker.stop()
                await worker.start()
                return False
            except Exception:
                logger.debug("Shell update failed for %s, falling back to subprocess", pkg_info.package)

        # Fallback: subprocess
        if pkg_info.manager == "npm":
            code, output = await self._run_cmd(
                "npm", "install", "-g", f"{pkg_info.package}@latest",
                timeout=120,
            )
        elif pkg_info.manager == "uv":
            code, output = await self._run_cmd(
                "uv", "tool", "upgrade", pkg_info.package, "--no-cache",
                timeout=120,
            )
        else:
            return False

        if code != 0:
            logger.error("Update failed for %s: %s", pkg_info.package, output)
            return False

        logger.info("Successfully updated %s", pkg_info.package)
        return True

    # ------------------------------------------------------------------
    # Main check-and-update cycle
    # ------------------------------------------------------------------

    def _next_check_at(self) -> str:
        return (datetime.now(timezone.utc) + timedelta(hours=self.config.interval_hours)).isoformat()

    async def _check_single_provider(
        self,
        provider: ProviderName,
        now: str,
        next_check: str,
    ) -> CLIVersionStatus | None:
        """Check a single provider's version — designed to run concurrently."""
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

        current, latest = await asyncio.gather(
            self.get_current_version(executable or adapter.default_executable, provider),
            self.get_latest_version(pkg_info),
        )

        needs_update = False
        skip_reason: str | None = None
        last_updated: str | None = None

        if current and latest:
            try:
                needs_update = _version_tuple(current) < _version_tuple(latest)
            except (ValueError, TypeError):
                needs_update = current != latest

        if needs_update and self.config.auto_update:
            if self.is_provider_idle(provider):
                success = await self.update_cli(pkg_info)
                if success:
                    await self.manager.restart_provider(provider)
                    last_updated = datetime.now(timezone.utc).isoformat()
                    current = await self.get_current_version(
                        executable or adapter.default_executable, provider
                    )
                    if current and latest:
                        try:
                            needs_update = _version_tuple(current) < _version_tuple(latest)
                        except (ValueError, TypeError):
                            needs_update = current != latest
                else:
                    skip_reason = "update command failed"
            else:
                skip_reason = "workers busy"
                logger.warning(
                    "Skipping update for %s: workers are busy", provider.value
                )
        elif needs_update and not self.config.auto_update:
            skip_reason = "auto_update disabled"

        return CLIVersionStatus(
            provider=provider,
            executable=executable,
            current_version=current,
            latest_version=latest,
            needs_update=needs_update,
            last_checked=now,
            next_check_at=next_check,
            auto_update=self.config.auto_update,
            last_updated=last_updated,
            update_skipped_reason=skip_reason,
        )

    async def check_and_update_all(self) -> list[CLIVersionStatus]:
        now = datetime.now(timezone.utc).isoformat()
        next_check = self._next_check_at()

        providers = [p for p in self.manager.config.providers if self.manager.config.providers[p].enabled]
        check_results = await asyncio.gather(
            *(self._check_single_provider(p, now, next_check) for p in providers)
        )
        results = [r for r in check_results if r is not None]

        self._last_results = results
        return results

    async def update_single_provider(self, provider: ProviderName) -> CLIVersionStatus:
        """Force-update a single provider CLI regardless of auto_update setting."""
        now = datetime.now(timezone.utc).isoformat()
        next_check = self._next_check_at()

        provider_config = self.manager.config.providers.get(provider)
        if provider_config is None or not provider_config.enabled:
            return CLIVersionStatus(
                provider=provider, executable=None,
                current_version=None, latest_version=None,
                needs_update=False, last_checked=now,
                next_check_at=next_check, auto_update=self.config.auto_update,
                last_updated=None, update_skipped_reason="provider not enabled",
            )

        adapter = self.manager.registry.get(provider)
        if adapter is None:
            return CLIVersionStatus(
                provider=provider, executable=None,
                current_version=None, latest_version=None,
                needs_update=False, last_checked=now,
                next_check_at=next_check, auto_update=self.config.auto_update,
                last_updated=None, update_skipped_reason="no adapter",
            )

        executable = adapter.resolve_executable(provider_config.executable)
        pkg_info = PACKAGE_REGISTRY.get(adapter.default_executable)
        if pkg_info is None:
            return CLIVersionStatus(
                provider=provider, executable=executable,
                current_version=None, latest_version=None,
                needs_update=False, last_checked=now,
                next_check_at=next_check, auto_update=self.config.auto_update,
                last_updated=None, update_skipped_reason="unknown package",
            )

        current = await self.get_current_version(executable or adapter.default_executable, provider)
        latest = await self.get_latest_version(pkg_info)
        skip_reason: str | None = None
        last_updated: str | None = None

        if not self.is_provider_idle(provider):
            return CLIVersionStatus(
                provider=provider, executable=executable,
                current_version=current, latest_version=latest,
                needs_update=bool(current and latest and _version_tuple(current) < _version_tuple(latest)),
                last_checked=now, next_check_at=next_check, auto_update=self.config.auto_update,
                last_updated=None, update_skipped_reason="workers busy",
            )

        success = await self.update_cli(pkg_info)
        if success:
            await self.manager.restart_provider(provider)
            last_updated = datetime.now(timezone.utc).isoformat()
            current = await self.get_current_version(executable or adapter.default_executable, provider)
        else:
            skip_reason = "update command failed"

        needs_update = False
        if current and latest:
            try:
                needs_update = _version_tuple(current) < _version_tuple(latest)
            except (ValueError, TypeError):
                needs_update = current != latest

        result = CLIVersionStatus(
            provider=provider, executable=executable,
            current_version=current, latest_version=latest,
            needs_update=needs_update, last_checked=now,
            next_check_at=next_check, auto_update=self.config.auto_update,
            last_updated=last_updated, update_skipped_reason=skip_reason,
        )

        # Update the cached results for this provider
        self._last_results = [
            result if r.provider == provider else r
            for r in self._last_results
        ]
        if not any(r.provider == provider for r in self._last_results):
            self._last_results.append(result)

        return result

    # ------------------------------------------------------------------
    # Periodic background loop
    # ------------------------------------------------------------------

    async def _periodic_loop(self) -> None:
        while True:
            try:
                results = await self.check_and_update_all()
                for r in results:
                    if r.needs_update:
                        logger.info(
                            "%s: %s → %s (update %s)",
                            r.provider.value,
                            r.current_version,
                            r.latest_version,
                            r.update_skipped_reason or "applied",
                        )
                    else:
                        logger.info(
                            "%s: %s (up to date)", r.provider.value, r.current_version
                        )
            except Exception:
                logger.exception("Error during periodic CLI version check")
            await asyncio.sleep(self.config.interval_hours * 3600)

    def start(self) -> None:
        if not self.config.enabled:
            logger.info("CLI updater is disabled")
            return
        if self._task is None:
            logger.info(
                "Starting CLI updater (interval=%.1fh, auto_update=%s)",
                self.config.interval_hours,
                self.config.auto_update,
            )
            self._task = asyncio.create_task(self._periodic_loop())

    async def stop(self) -> None:
        if self._task is not None:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None

    @property
    def last_results(self) -> list[CLIVersionStatus]:
        return list(self._last_results)
