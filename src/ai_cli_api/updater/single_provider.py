from __future__ import annotations

from datetime import datetime, timezone
from typing import TYPE_CHECKING

from ..models import CLIVersionStatus, ProviderName
from .registry import PACKAGE_REGISTRY, needs_update as _needs_update

if TYPE_CHECKING:
    from .updater import CLIUpdater


async def update_single_provider_impl(updater: "CLIUpdater", provider: ProviderName) -> CLIVersionStatus:
    now = datetime.now(timezone.utc).isoformat()
    next_check = updater._next_check_at()

    provider_config = updater.manager.config.providers.get(provider)
    if provider_config is None or not provider_config.enabled:
        return updater._build_status(
            provider=provider,
            executable=None,
            current_version=None,
            latest_version=None,
            needs_update=False,
            now=now,
            next_check=next_check,
            skip_reason="provider not enabled",
        )

    adapter = updater.manager.registry.get(provider)
    if adapter is None:
        return updater._build_status(
            provider=provider,
            executable=None,
            current_version=None,
            latest_version=None,
            needs_update=False,
            now=now,
            next_check=next_check,
            skip_reason="no adapter",
        )

    executable = adapter.resolve_executable(provider_config.executable)
    pkg_info = PACKAGE_REGISTRY.get(adapter.default_executable)
    if pkg_info is None:
        return updater._build_status(
            provider=provider,
            executable=executable,
            current_version=None,
            latest_version=None,
            needs_update=False,
            now=now,
            next_check=next_check,
            skip_reason="unknown package",
        )

    current = await updater.get_current_version(executable or adapter.default_executable, provider)
    latest = await updater.get_latest_version(pkg_info)

    if not updater.is_provider_idle(provider):
        result = updater._build_status(
            provider=provider,
            executable=executable,
            current_version=current,
            latest_version=latest,
            needs_update=_needs_update(current, latest),
            now=now,
            next_check=next_check,
            skip_reason="workers busy",
        )
        updater._cache_single(result)
        return result

    skip_reason: str | None = None
    last_updated: str | None = None

    success = await updater.update_cli(pkg_info)
    if success:
        await updater.manager.restart_provider(provider)
        await updater.manager.activate_provider(provider)
        last_updated = datetime.now(timezone.utc).isoformat()
        current = await updater.get_current_version(executable or adapter.default_executable, provider)
    else:
        skip_reason = "update command failed"

    result = updater._build_status(
        provider=provider,
        executable=executable,
        current_version=current,
        latest_version=latest,
        needs_update=_needs_update(current, latest),
        now=now,
        next_check=next_check,
        last_updated=last_updated,
        skip_reason=skip_reason,
    )
    updater._cache_single(result)
    return result
