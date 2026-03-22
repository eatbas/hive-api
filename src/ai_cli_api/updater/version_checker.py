from __future__ import annotations

import asyncio
import logging
import os
import subprocess
from collections.abc import Awaitable, Callable

from ..models import ProviderName
from ..worker import WarmWorker, WorkerManager
from .registry import CLIPackageInfo, _parse_version

logger = logging.getLogger("ai_cli_api.updater")
_CMD_TIMEOUT = 60

RunCmd = Callable[..., Awaitable[tuple[int, str]]]


async def run_cmd(*args: str, timeout: int = _CMD_TIMEOUT) -> tuple[int, str]:
    kwargs: dict[str, int] = {}
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


async def get_current_version(
    *,
    manager: WorkerManager,
    runner: RunCmd,
    executable: str,
    provider: ProviderName | None = None,
) -> str | None:
    if provider is not None:
        worker = manager.get_idle_worker(provider)
        if worker is not None and worker.ready:
            try:
                code, output = await worker.run_quick_command(f"{executable} --version 2>&1\n__ai_cli_exit=$?")
                if code == 0 and output:
                    version = _parse_version(output)
                    if version:
                        return version
            except Exception:
                logger.debug("Shell version check failed for %s, falling back", executable)

    code, output = await runner(executable, "--version")
    if code != 0:
        logger.warning("Failed to get version for %s (exit %d)", executable, code)
        return None
    return _parse_version(output)


async def get_latest_version(*, manager: WorkerManager, runner: RunCmd, pkg_info: CLIPackageInfo) -> str | None:
    worker = manager.get_idle_worker(pkg_info.provider)
    if worker is not None and worker.ready:
        try:
            result = await get_latest_version_via_shell(worker=worker, pkg_info=pkg_info)
            if result:
                return result
        except Exception:
            logger.debug("Shell latest-version check failed for %s, falling back", pkg_info.package)
    return await get_latest_version_subprocess(runner=runner, pkg_info=pkg_info)


async def get_latest_version_via_shell(*, worker: WarmWorker, pkg_info: CLIPackageInfo) -> str | None:
    if pkg_info.manager == "npm":
        code, output = await worker.run_quick_command(f"npm view {pkg_info.package} version 2>&1\n__ai_cli_exit=$?")
        if code == 0 and output:
            return _parse_version(output)
    elif pkg_info.manager == "uv":
        code, output = await worker.run_quick_command("uv tool list 2>&1\n__ai_cli_exit=$?")
        if code == 0 and output:
            for line in output.splitlines():
                if pkg_info.package in line:
                    return _parse_version(line)
    return None


async def get_latest_version_subprocess(*, runner: RunCmd, pkg_info: CLIPackageInfo) -> str | None:
    if pkg_info.manager == "npm":
        code, output = await runner("npm", "view", pkg_info.package, "version")
        if code != 0:
            logger.warning("npm view failed for %s (exit %d)", pkg_info.package, code)
            return None
        return _parse_version(output)

    if pkg_info.manager == "uv":
        code, output = await runner("uv", "tool", "list")
        if code != 0:
            logger.warning("uv tool list failed (exit %d)", code)
            return None
        for line in output.splitlines():
            if pkg_info.package in line:
                return _parse_version(line)
        logger.warning("Package %s not found in uv tool list", pkg_info.package)
    return None
