from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, patch

import pytest

from ai_cli_api.config import UpdaterConfig
from ai_cli_api.models import ProviderName
from ai_cli_api.updater import (
    CLIPackageInfo,
    CLIUpdater,
    PACKAGE_REGISTRY,
    _parse_version,
    _version_tuple,
)
from ai_cli_api.worker import WorkerManager


# ------------------------------------------------------------------
# Unit helpers
# ------------------------------------------------------------------


class TestParseVersion:
    def test_simple_semver(self):
        assert _parse_version("1.2.3") == "1.2.3"

    def test_prefix_text(self):
        assert _parse_version("claude v1.0.16") == "1.0.16"

    def test_at_version(self):
        assert _parse_version("@google/gemini-cli@0.3.1") == "0.3.1"

    def test_no_match(self):
        assert _parse_version("no version here") is None

    def test_empty(self):
        assert _parse_version("") is None

    def test_multiline_output(self):
        output = "Gemini CLI\nVersion: 0.5.2\nNode.js v20.0.0"
        assert _parse_version(output) == "0.5.2"


class TestVersionTuple:
    def test_basic(self):
        assert _version_tuple("1.2.3") == (1, 2, 3)

    def test_comparison(self):
        assert _version_tuple("1.2.3") < _version_tuple("1.3.0")
        assert _version_tuple("2.0.0") > _version_tuple("1.99.99")
        assert _version_tuple("1.0.0") == _version_tuple("1.0.0")


class TestPackageRegistry:
    def test_all_providers_registered(self):
        assert "claude" in PACKAGE_REGISTRY
        assert "codex" in PACKAGE_REGISTRY
        assert "gemini" in PACKAGE_REGISTRY
        assert "kimi" in PACKAGE_REGISTRY

    def test_claude_is_npm(self):
        info = PACKAGE_REGISTRY["claude"]
        assert info.manager == "npm"
        assert info.package == "@anthropic-ai/claude-code"

    def test_kimi_is_uv(self):
        info = PACKAGE_REGISTRY["kimi"]
        assert info.manager == "uv"
        assert info.package == "kimi-cli"


# ------------------------------------------------------------------
# CLIUpdater tests (mocked subprocess)
# ------------------------------------------------------------------


@pytest.fixture()
def updater(loaded_config):
    manager = WorkerManager(loaded_config)
    config = UpdaterConfig(enabled=True, interval_hours=4.0, auto_update=True)
    return CLIUpdater(manager=manager, config=config)


class TestGetCurrentVersion:
    @pytest.mark.asyncio()
    async def test_parses_version_from_stdout(self, updater):
        with patch.object(updater, "_run_cmd", new_callable=AsyncMock) as mock_cmd:
            mock_cmd.return_value = (0, "claude v1.0.16\n")
            version = await updater.get_current_version("claude")
            assert version == "1.0.16"
            mock_cmd.assert_called_once_with("claude", "--version")

    @pytest.mark.asyncio()
    async def test_returns_none_on_failure(self, updater):
        with patch.object(updater, "_run_cmd", new_callable=AsyncMock) as mock_cmd:
            mock_cmd.return_value = (-1, "")
            version = await updater.get_current_version("claude")
            assert version is None


class TestGetLatestVersion:
    @pytest.mark.asyncio()
    async def test_npm_package(self, updater):
        pkg = CLIPackageInfo(ProviderName.CLAUDE, "npm", "@anthropic-ai/claude-code")
        with patch.object(updater, "_run_cmd", new_callable=AsyncMock) as mock_cmd:
            mock_cmd.return_value = (0, "1.0.17\n")
            version = await updater.get_latest_version(pkg)
            assert version == "1.0.17"
            mock_cmd.assert_called_once_with("npm", "view", "@anthropic-ai/claude-code", "version")

    @pytest.mark.asyncio()
    async def test_uv_package(self, updater):
        pkg = CLIPackageInfo(ProviderName.KIMI, "uv", "kimi-cli")
        with patch.object(updater, "_run_cmd", new_callable=AsyncMock) as mock_cmd:
            mock_cmd.return_value = (0, "kimi-cli v1.2.0\n- kimi\nother-tool v0.1.0\n")
            version = await updater.get_latest_version(pkg)
            assert version == "1.2.0"

    @pytest.mark.asyncio()
    async def test_uv_package_not_found(self, updater):
        pkg = CLIPackageInfo(ProviderName.KIMI, "uv", "kimi-cli")
        with patch.object(updater, "_run_cmd", new_callable=AsyncMock) as mock_cmd:
            mock_cmd.return_value = (0, "other-tool v0.1.0\n")
            version = await updater.get_latest_version(pkg)
            assert version is None

    @pytest.mark.asyncio()
    async def test_npm_failure(self, updater):
        pkg = CLIPackageInfo(ProviderName.CLAUDE, "npm", "@anthropic-ai/claude-code")
        with patch.object(updater, "_run_cmd", new_callable=AsyncMock) as mock_cmd:
            mock_cmd.return_value = (1, "npm ERR!")
            version = await updater.get_latest_version(pkg)
            assert version is None


class TestIsProviderIdle:
    @pytest.mark.asyncio()
    async def test_idle_when_no_workers(self, updater):
        # Manager has no booted workers yet
        assert updater.is_provider_idle(ProviderName.CLAUDE) is True

    @pytest.mark.asyncio()
    async def test_idle_when_workers_not_busy(self, loaded_config):
        manager = WorkerManager(loaded_config)
        await manager.start()
        try:
            config = UpdaterConfig(enabled=True, interval_hours=4.0, auto_update=True)
            u = CLIUpdater(manager=manager, config=config)
            assert u.is_provider_idle(ProviderName.CLAUDE) is True
        finally:
            await manager.stop()


class TestUpdateCli:
    @pytest.mark.asyncio()
    async def test_npm_update_success(self, updater):
        pkg = CLIPackageInfo(ProviderName.CLAUDE, "npm", "@anthropic-ai/claude-code")
        with patch.object(updater, "_run_cmd", new_callable=AsyncMock) as mock_cmd:
            mock_cmd.return_value = (0, "added 1 package")
            result = await updater.update_cli(pkg)
            assert result is True
            mock_cmd.assert_called_once_with(
                "npm", "install", "-g", "@anthropic-ai/claude-code@latest",
                timeout=120,
            )

    @pytest.mark.asyncio()
    async def test_uv_update_success(self, updater):
        pkg = CLIPackageInfo(ProviderName.KIMI, "uv", "kimi-cli")
        with patch.object(updater, "_run_cmd", new_callable=AsyncMock) as mock_cmd:
            mock_cmd.return_value = (0, "Updated kimi-cli")
            result = await updater.update_cli(pkg)
            assert result is True
            mock_cmd.assert_called_once_with(
                "uv", "tool", "upgrade", "kimi-cli", "--no-cache",
                timeout=120,
            )

    @pytest.mark.asyncio()
    async def test_update_failure(self, updater):
        pkg = CLIPackageInfo(ProviderName.CLAUDE, "npm", "@anthropic-ai/claude-code")
        with patch.object(updater, "_run_cmd", new_callable=AsyncMock) as mock_cmd:
            mock_cmd.return_value = (1, "npm ERR!")
            result = await updater.update_cli(pkg)
            assert result is False


class TestCheckAndUpdateAll:
    @pytest.mark.asyncio()
    async def test_up_to_date_no_update(self, loaded_config):
        manager = WorkerManager(loaded_config)
        await manager.start()
        try:
            config = UpdaterConfig(enabled=True, interval_hours=4.0, auto_update=True)
            u = CLIUpdater(manager=manager, config=config)

            with patch.object(u, "get_current_version", new_callable=AsyncMock) as mock_curr, \
                 patch.object(u, "get_latest_version", new_callable=AsyncMock) as mock_latest, \
                 patch.object(u, "update_cli", new_callable=AsyncMock) as mock_update:
                mock_curr.return_value = "1.0.0"
                mock_latest.return_value = "1.0.0"

                results = await u.check_and_update_all()
                assert len(results) == 4
                assert all(not r.needs_update for r in results)
                mock_update.assert_not_called()
        finally:
            await manager.stop()

    @pytest.mark.asyncio()
    async def test_outdated_and_idle_triggers_update(self, loaded_config):
        manager = WorkerManager(loaded_config)
        await manager.start()
        try:
            config = UpdaterConfig(enabled=True, interval_hours=4.0, auto_update=True)
            u = CLIUpdater(manager=manager, config=config)

            call_counts: dict[str, int] = {}

            async def version_side_effect(executable, provider=None):
                key = str(provider or executable)
                call_counts[key] = call_counts.get(key, 0) + 1
                # First call: old version; second call (post-update): new version
                return "1.0.0" if call_counts[key] == 1 else "1.1.0"

            with patch.object(u, "get_current_version", side_effect=version_side_effect) as mock_curr, \
                 patch.object(u, "get_latest_version", new_callable=AsyncMock) as mock_latest, \
                 patch.object(u, "update_cli", new_callable=AsyncMock) as mock_update, \
                 patch.object(manager, "restart_provider", new_callable=AsyncMock):
                mock_latest.return_value = "1.1.0"
                mock_update.return_value = True

                results = await u.check_and_update_all()
                assert len(results) == 4
                assert mock_update.call_count == 4
        finally:
            await manager.stop()

    @pytest.mark.asyncio()
    async def test_outdated_but_busy_skips(self, loaded_config):
        manager = WorkerManager(loaded_config)
        await manager.start()
        try:
            config = UpdaterConfig(enabled=True, interval_hours=4.0, auto_update=True)
            u = CLIUpdater(manager=manager, config=config)

            # Mark a claude worker as busy
            claude_workers = manager.workers_for_provider(ProviderName.CLAUDE)
            claude_workers[0].busy = True

            with patch.object(u, "get_current_version", new_callable=AsyncMock) as mock_curr, \
                 patch.object(u, "get_latest_version", new_callable=AsyncMock) as mock_latest, \
                 patch.object(u, "update_cli", new_callable=AsyncMock) as mock_update:
                mock_curr.return_value = "1.0.0"
                mock_latest.return_value = "1.1.0"

                results = await u.check_and_update_all()
                claude_result = next(r for r in results if r.provider == ProviderName.CLAUDE)
                assert claude_result.needs_update is True
                assert claude_result.update_skipped_reason == "workers busy"
        finally:
            await manager.stop()

    @pytest.mark.asyncio()
    async def test_auto_update_disabled(self, loaded_config):
        manager = WorkerManager(loaded_config)
        await manager.start()
        try:
            config = UpdaterConfig(enabled=True, interval_hours=4.0, auto_update=False)
            u = CLIUpdater(manager=manager, config=config)

            with patch.object(u, "get_current_version", new_callable=AsyncMock) as mock_curr, \
                 patch.object(u, "get_latest_version", new_callable=AsyncMock) as mock_latest, \
                 patch.object(u, "update_cli", new_callable=AsyncMock) as mock_update:
                mock_curr.return_value = "1.0.0"
                mock_latest.return_value = "1.1.0"

                results = await u.check_and_update_all()
                assert all(r.update_skipped_reason == "auto_update disabled" for r in results)
                mock_update.assert_not_called()
        finally:
            await manager.stop()


class TestStartStop:
    @pytest.mark.asyncio()
    async def test_start_creates_task(self, updater):
        updater.start()
        assert updater._task is not None
        await updater.stop()
        assert updater._task is None

    @pytest.mark.asyncio()
    async def test_disabled_does_not_start(self, loaded_config):
        manager = WorkerManager(loaded_config)
        config = UpdaterConfig(enabled=False, interval_hours=4.0, auto_update=True)
        u = CLIUpdater(manager=manager, config=config)
        u.start()
        assert u._task is None


class TestLastResults:
    @pytest.mark.asyncio()
    async def test_empty_before_first_check(self, updater):
        assert updater.last_results == []

    @pytest.mark.asyncio()
    async def test_populated_after_check(self, loaded_config):
        manager = WorkerManager(loaded_config)
        await manager.start()
        try:
            config = UpdaterConfig(enabled=True, interval_hours=4.0, auto_update=False)
            u = CLIUpdater(manager=manager, config=config)

            with patch.object(u, "get_current_version", new_callable=AsyncMock) as mock_curr, \
                 patch.object(u, "get_latest_version", new_callable=AsyncMock) as mock_latest:
                mock_curr.return_value = "1.0.0"
                mock_latest.return_value = "1.0.0"

                await u.check_and_update_all()
                assert len(u.last_results) == 4
        finally:
            await manager.stop()


class TestAPIEndpoints:
    def test_cli_versions_returns_empty_initially(self, config_path):
        from fastapi.testclient import TestClient
        from ai_cli_api.service import create_app

        app = create_app()
        with TestClient(app) as client:
            response = client.get("/v1/cli-versions")
            assert response.status_code == 200
            assert response.json() == []

    def test_cli_versions_check_returns_results(self, config_path):
        from fastapi.testclient import TestClient
        from ai_cli_api.service import create_app

        app = create_app()
        with TestClient(app) as client:
            with patch(
                "ai_cli_api.updater.CLIUpdater._run_cmd",
                new_callable=AsyncMock,
            ) as mock_cmd:
                mock_cmd.return_value = (0, "1.0.0")
                response = client.post("/v1/cli-versions/check")
                assert response.status_code == 200
                data = response.json()
                assert len(data) == 4
                for item in data:
                    assert "provider" in item
                    assert "current_version" in item
                    assert "latest_version" in item
                    assert "needs_update" in item
