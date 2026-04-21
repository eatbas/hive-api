from __future__ import annotations

import asyncio
import os
import signal

import pytest

import symphony.parent_watchdog as parent_watchdog


@pytest.fixture(autouse=True)
async def _reset_watchdog_task() -> None:
    """Ensure each test starts and ends with no active watchdog task."""
    await parent_watchdog.stop_parent_watchdog()
    yield
    await parent_watchdog.stop_parent_watchdog()


@pytest.mark.asyncio
async def test_start_is_noop_on_windows(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(parent_watchdog, "sys", _FakeSys("win32"), raising=False)
    monkeypatch.setenv("MAESTRO_PARENT_PID", "12345")

    parent_watchdog.start_parent_watchdog()

    assert parent_watchdog._task is None


@pytest.mark.asyncio
async def test_start_is_noop_without_parent_pid(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(parent_watchdog, "sys", _FakeSys("linux"), raising=False)
    monkeypatch.delenv("MAESTRO_PARENT_PID", raising=False)

    parent_watchdog.start_parent_watchdog()

    assert parent_watchdog._task is None


@pytest.mark.asyncio
async def test_start_is_noop_for_invalid_parent_pid(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(parent_watchdog, "sys", _FakeSys("linux"), raising=False)
    monkeypatch.setenv("MAESTRO_PARENT_PID", "not-a-number")

    parent_watchdog.start_parent_watchdog()

    assert parent_watchdog._task is None


@pytest.mark.asyncio
async def test_start_is_noop_for_init_pid(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(parent_watchdog, "sys", _FakeSys("linux"), raising=False)
    monkeypatch.setenv("MAESTRO_PARENT_PID", "1")

    parent_watchdog.start_parent_watchdog()

    assert parent_watchdog._task is None


@pytest.mark.asyncio
async def test_start_then_stop_creates_and_cancels_task(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(parent_watchdog, "sys", _FakeSys("linux"), raising=False)
    monkeypatch.setenv("MAESTRO_PARENT_PID", str(os.getpid()))

    parent_watchdog.start_parent_watchdog()

    assert parent_watchdog._task is not None
    assert not parent_watchdog._task.done()

    await parent_watchdog.stop_parent_watchdog()

    assert parent_watchdog._task is None


def test_pid_alive_returns_false_when_process_missing(monkeypatch: pytest.MonkeyPatch) -> None:
    def _raise_missing(_pid: int, _sig: int) -> None:
        raise ProcessLookupError

    monkeypatch.setattr(parent_watchdog.os, "kill", _raise_missing)

    assert parent_watchdog._pid_alive(9999) is False


def test_pid_alive_returns_true_when_permission_denied(monkeypatch: pytest.MonkeyPatch) -> None:
    def _raise_denied(_pid: int, _sig: int) -> None:
        raise PermissionError

    monkeypatch.setattr(parent_watchdog.os, "kill", _raise_denied)

    assert parent_watchdog._pid_alive(9999) is True


def test_pid_alive_returns_true_when_signal_succeeds(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[tuple[int, int]] = []

    def _record(pid: int, sig: int) -> None:
        calls.append((pid, sig))

    monkeypatch.setattr(parent_watchdog.os, "kill", _record)

    assert parent_watchdog._pid_alive(4242) is True
    assert calls == [(4242, 0)]


def test_trigger_shutdown_sends_sigterm_to_self(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[tuple[int, int]] = []

    def _capture(pid: int, sig: int) -> None:
        calls.append((pid, sig))

    monkeypatch.setattr(parent_watchdog.os, "kill", _capture)
    monkeypatch.setattr(parent_watchdog.os, "getpid", lambda: 7777)

    parent_watchdog._trigger_shutdown()

    assert calls == [(7777, signal.SIGTERM)]


@pytest.mark.asyncio
async def test_watch_triggers_shutdown_when_parent_dies(monkeypatch: pytest.MonkeyPatch) -> None:
    alive_responses = iter([True, False])

    def _fake_alive(_pid: int) -> bool:
        return next(alive_responses)

    shutdown_called = asyncio.Event()

    def _fake_shutdown() -> None:
        shutdown_called.set()

    monkeypatch.setattr(parent_watchdog, "_pid_alive", _fake_alive)
    monkeypatch.setattr(parent_watchdog, "_trigger_shutdown", _fake_shutdown)
    monkeypatch.setattr(parent_watchdog, "_POLL_INTERVAL_SECONDS", 0.01)

    await asyncio.wait_for(parent_watchdog._watch(12345), timeout=1.0)

    assert shutdown_called.is_set()


class _FakeSys:
    """Minimal sys-shim so platform branches can be exercised on any host."""

    def __init__(self, platform: str) -> None:
        self.platform = platform
