import asyncio
from pathlib import Path
from unittest.mock import patch

import pytest

from ai_cli_api.models import ChatMode, ChatRequest, ProviderName
from ai_cli_api.worker import WorkerManager


def _new_request(provider, model, prompt="hello", workspace=None):
    resolved_workspace = workspace or str(Path.cwd().resolve())
    return ChatRequest(
        provider=provider,
        model=model,
        workspace_path=resolved_workspace,
        mode=ChatMode.NEW,
        prompt=prompt,
        stream=False,
    )


@pytest.mark.asyncio()
async def test_worker_manager_boots_all_workers(loaded_config):
    manager = WorkerManager(loaded_config)
    await manager.start()
    try:
        workers = manager.worker_info()
        assert len(workers) == 9
        assert all(worker.ready for worker in workers)
    finally:
        await manager.stop()


@pytest.mark.asyncio()
async def test_worker_ready_busy_idle_lifecycle(loaded_config):
    manager = WorkerManager(loaded_config)
    await manager.start()
    try:
        worker = manager.get_worker(ProviderName.CLAUDE, "sonnet")
        assert worker is not None
        assert worker.ready
        assert not worker.busy

        handle = await worker.submit(_new_request(ProviderName.CLAUDE, "sonnet"))
        result = await handle.result_future
        assert result.exit_code == 0
        assert not worker.busy
        assert worker.ready
    finally:
        await manager.stop()


@pytest.mark.asyncio()
async def test_resume_rejects_model_change_in_same_runtime(loaded_config):
    manager = WorkerManager(loaded_config)
    await manager.start()
    try:
        worker = manager.get_worker(ProviderName.GEMINI, "gemini-2.5-pro")
        assert worker is not None
        handle = await worker.submit(_new_request(ProviderName.GEMINI, "gemini-2.5-pro"))
        result = await handle.result_future
        assert result.provider_session_ref == "gemini-session-new"

        alt_worker = manager.get_worker(ProviderName.GEMINI, "gemini-2.5-flash")
        assert alt_worker is not None
        resume_request = ChatRequest(
            provider=ProviderName.GEMINI,
            model="gemini-2.5-flash",
            workspace_path=str(Path.cwd().resolve()),
            mode=ChatMode.RESUME,
            prompt="again",
            provider_session_ref=result.provider_session_ref,
            stream=False,
        )
        handle = await alt_worker.submit(resume_request)
        with pytest.raises(Exception):
            await handle.result_future
    finally:
        await manager.stop()


@pytest.mark.asyncio()
async def test_concurrent_requests_serialize_on_same_worker(loaded_config):
    """Two requests to the same worker should run one after the other."""
    manager = WorkerManager(loaded_config)
    await manager.start()
    try:
        worker = manager.get_worker(ProviderName.CLAUDE, "sonnet")
        assert worker is not None

        h1 = await worker.submit(_new_request(ProviderName.CLAUDE, "sonnet", prompt="first"))
        h2 = await worker.submit(_new_request(ProviderName.CLAUDE, "sonnet", prompt="second"))

        r1, r2 = await asyncio.gather(h1.result_future, h2.result_future)
        assert "first" in r1.final_text
        assert "second" in r2.final_text
    finally:
        await manager.stop()


@pytest.mark.asyncio()
async def test_get_worker_returns_none_for_unknown(loaded_config):
    manager = WorkerManager(loaded_config)
    await manager.start()
    try:
        assert manager.get_worker(ProviderName.CLAUDE, "nonexistent") is None
    finally:
        await manager.stop()


@pytest.mark.asyncio()
async def test_failed_prompt_sets_worker_error(loaded_config):
    manager = WorkerManager(loaded_config)
    await manager.start()
    try:
        worker = manager.get_worker(ProviderName.CLAUDE, "sonnet")
        assert worker is not None
        handle = await worker.submit(_new_request(ProviderName.CLAUDE, "sonnet", prompt="fail"))
        with pytest.raises(Exception):
            await handle.result_future
        assert worker.last_error is not None
    finally:
        await manager.stop()


@pytest.mark.asyncio()
async def test_worker_recovers_after_failure(loaded_config):
    """After a failure, the next request should still work."""
    manager = WorkerManager(loaded_config)
    await manager.start()
    try:
        worker = manager.get_worker(ProviderName.CODEX, "codex-5.3")
        assert worker is not None

        # First request fails
        h1 = await worker.submit(_new_request(ProviderName.CODEX, "codex-5.3", prompt="fail"))
        with pytest.raises(Exception):
            await h1.result_future

        # Second request should succeed (worker recovers)
        h2 = await worker.submit(_new_request(ProviderName.CODEX, "codex-5.3", prompt="recover"))
        r2 = await h2.result_future
        assert "recover" in r2.final_text
    finally:
        await manager.stop()


@pytest.mark.asyncio()
async def test_health_details_reports_worker_errors(loaded_config):
    manager = WorkerManager(loaded_config)
    await manager.start()
    try:
        worker = manager.get_worker(ProviderName.CLAUDE, "sonnet")
        handle = await worker.submit(_new_request(ProviderName.CLAUDE, "sonnet", prompt="fail"))
        with pytest.raises(Exception):
            await handle.result_future

        details = manager.health_details()
        assert len(details) > 0
        assert "claude" in details[0].lower()
    finally:
        await manager.stop()


@pytest.mark.asyncio()
async def test_unavailable_provider_skips_worker_creation(loaded_config):
    """When a CLI is not found, no workers should be created for that provider."""
    import shutil

    original_which = shutil.which

    def _fake_which(cmd: str, **kwargs) -> str | None:  # type: ignore[override]
        if "claude" in str(cmd):
            return None
        return original_which(cmd, **kwargs)

    with patch("ai_cli_api.providers.base.shutil.which", side_effect=_fake_which):
        manager = WorkerManager(loaded_config)
        await manager.start()
        try:
            assert manager.get_worker(ProviderName.CLAUDE, "sonnet") is None
            assert manager.get_worker(ProviderName.CLAUDE, "opus") is None
            assert manager.available_providers[ProviderName.CLAUDE] is False

            # Other providers should still have workers
            assert manager.get_worker(ProviderName.GEMINI, "gemini-2.5-flash") is not None
            assert manager.available_providers[ProviderName.GEMINI] is True

            # capabilities() should report available=False for claude
            caps = {c.provider: c for c in manager.capabilities()}
            assert caps[ProviderName.CLAUDE].available is False
            assert caps[ProviderName.GEMINI].available is True
        finally:
            await manager.stop()


@pytest.mark.asyncio()
async def test_capabilities_include_available_field(loaded_config):
    """All providers should have the available field in capabilities."""
    manager = WorkerManager(loaded_config)
    await manager.start()
    try:
        caps = manager.capabilities()
        for cap in caps:
            assert hasattr(cap, "available")
            # All test providers use absolute paths so should be available
            assert cap.available is True
    finally:
        await manager.stop()
