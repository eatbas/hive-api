"""Playwright end-to-end tests for the web console UI.

These tests start the FastAPI app with fake CLI wrappers (same as
the unit tests) and drive the real browser to verify the full
request -> SSE-stream -> UI-render pipeline.

The server is started in a **subprocess** so that its asyncio event
loop does not interfere with pytest-asyncio tests in the same session.

IMPORTANT: These tests live under tests/e2e/ so they are collected
*after* all async unit tests.  Playwright's sync API installs a
persistent event loop that breaks pytest-asyncio's run_until_complete
if it runs first.
"""
from __future__ import annotations

import os
import signal
import socket
import subprocess
import sys
import time
from pathlib import Path

import pytest
from playwright.sync_api import Page, expect

from tests.conftest import make_config

# -- helpers ----------------------------------------------------------

_PORT = 18321  # unlikely to collide


def _wait_for_port(port: int, timeout: float = 15.0) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            with socket.create_connection(("127.0.0.1", port), timeout=0.5):
                return
        except OSError:
            time.sleep(0.25)
    raise RuntimeError(f"Server on port {port} did not start in time")


@pytest.fixture(scope="module")
def server(tmp_path_factory):
    """Module-scoped fixture: starts the API server in a subprocess."""
    tmp = tmp_path_factory.mktemp("ui")
    cfg = make_config(tmp)

    env = {**os.environ, "AI_CLI_API_CONFIG": str(cfg)}
    proc = subprocess.Popen(
        [
            sys.executable, "-m", "uvicorn",
            "ai_cli_api.main:app",
            "--host", "127.0.0.1",
            "--port", str(_PORT),
            "--log-level", "warning",
        ],
        env=env,
        # On Windows, use CREATE_NEW_PROCESS_GROUP for clean shutdown.
        creationflags=getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0),
    )
    _wait_for_port(_PORT)
    yield f"http://127.0.0.1:{_PORT}"

    # Shut down cleanly.
    if sys.platform == "win32":
        proc.send_signal(signal.CTRL_BREAK_EVENT)
    else:
        proc.terminate()
    try:
        proc.wait(timeout=5)
    except subprocess.TimeoutExpired:
        proc.kill()


@pytest.fixture()
def console_page(page: Page, server: str) -> Page:
    """Navigate to the console and wait for workers to load."""
    page.goto(server)
    # Wait for workers to appear (populated by JS on load)
    page.wait_for_selector(".worker-chip", timeout=10_000)
    return page


# -- tests ------------------------------------------------------------


class TestPageLoad:
    """Verify that the page loads and renders its initial state."""

    def test_title(self, console_page: Page):
        expect(console_page).to_have_title("AI CLI API Console")

    def test_hero_heading_visible(self, console_page: Page):
        heading = console_page.locator("h1")
        expect(heading).to_be_visible()
        expect(heading).to_contain_text("Probe every CLI")

    def test_health_status_ok(self, console_page: Page):
        status = console_page.locator("#health-status")
        expect(status).to_have_text("ok")

    def test_worker_count(self, console_page: Page):
        count = console_page.locator("#worker-count")
        expect(count).to_have_text("7")

    def test_all_workers_shown(self, console_page: Page):
        chips = console_page.locator(".worker-chip")
        expect(chips).to_have_count(7)

    def test_all_workers_ready(self, console_page: Page):
        chips = console_page.locator(".worker-chip")
        for i in range(chips.count()):
            expect(chips.nth(i)).to_contain_text("ready")


class TestProviderModelDropdowns:
    """The model dropdown should update when the provider changes."""

    def test_provider_options_exist(self, console_page: Page):
        options = console_page.locator("#provider option")
        providers = [options.nth(i).get_attribute("value") for i in range(options.count())]
        assert "gemini" in providers
        assert "claude" in providers
        assert "codex" in providers
        assert "kimi" in providers

    def test_model_dropdown_updates_on_provider_change(self, console_page: Page):
        console_page.select_option("#provider", "claude")
        console_page.wait_for_timeout(200)
        model_options = console_page.locator("#model option")
        models = [model_options.nth(i).get_attribute("value") for i in range(model_options.count())]
        assert "sonnet" in models
        assert "opus" in models

    def test_codex_models(self, console_page: Page):
        console_page.select_option("#provider", "codex")
        console_page.wait_for_timeout(200)
        model_options = console_page.locator("#model option")
        models = [model_options.nth(i).get_attribute("value") for i in range(model_options.count())]
        assert "codex-5.3" in models
        assert "gpt-5.4" in models
        assert "gpt-5.4-mini" in models

    def test_kimi_models(self, console_page: Page):
        console_page.select_option("#provider", "kimi")
        console_page.wait_for_timeout(200)
        model_options = console_page.locator("#model option")
        models = [model_options.nth(i).get_attribute("value") for i in range(model_options.count())]
        assert "default" in models


class TestStreamingRequest:
    """Send a streaming request through the UI and verify SSE events."""

    def test_claude_streaming_request(self, console_page: Page, tmp_path):
        console_page.select_option("#provider", "claude")
        console_page.select_option("#model", "sonnet")
        console_page.fill("#workspace_path", str(tmp_path.resolve()))
        console_page.fill("#prompt", "hello from playwright")
        console_page.click("#send-button")

        # Wait for the "Request completed." status
        console_page.wait_for_function(
            "document.getElementById('request-meta').textContent.includes('completed')",
            timeout=15_000,
        )

        console = console_page.locator("#console")
        text = console.inner_text()

        # Verify SSE events rendered
        assert "[run_started]" in text
        assert "[provider_session]" in text
        assert "[completed]" in text
        assert "claude:hello from playwright" in text

        # Session ref should have been captured
        session_el = console_page.locator("#session-ref")
        expect(session_el).not_to_have_text("none")

        # Event count should be > 0
        count_el = console_page.locator("#event-count")
        count = int(count_el.inner_text())
        assert count >= 3  # run_started, provider_session, output_delta, completed

    def test_gemini_streaming_request(self, console_page: Page, tmp_path):
        console_page.select_option("#provider", "gemini")
        console_page.select_option("#model", "gemini-2.5-flash")
        console_page.fill("#workspace_path", str(tmp_path.resolve()))
        console_page.fill("#prompt", "hello gemini")
        console_page.click("#send-button")

        console_page.wait_for_function(
            "document.getElementById('request-meta').textContent.includes('completed')",
            timeout=15_000,
        )

        console = console_page.locator("#console")
        text = console.inner_text()
        assert "[completed]" in text
        assert "gemini:hello gemini" in text

    def test_codex_streaming_request(self, console_page: Page, tmp_path):
        console_page.select_option("#provider", "codex")
        console_page.select_option("#model", "codex-5.3")
        console_page.fill("#workspace_path", str(tmp_path.resolve()))
        console_page.fill("#prompt", "hello codex")
        console_page.click("#send-button")

        console_page.wait_for_function(
            "document.getElementById('request-meta').textContent.includes('completed')",
            timeout=15_000,
        )

        console = console_page.locator("#console")
        text = console.inner_text()
        assert "[completed]" in text
        assert "codex:hello codex" in text

    def test_codex_mini_streaming_request(self, console_page: Page, tmp_path):
        console_page.select_option("#provider", "codex")
        console_page.select_option("#model", "gpt-5.4-mini")
        console_page.fill("#workspace_path", str(tmp_path.resolve()))
        console_page.fill("#prompt", "hello codex mini")
        console_page.click("#send-button")

        console_page.wait_for_function(
            "document.getElementById('request-meta').textContent.includes('completed')",
            timeout=15_000,
        )

        console = console_page.locator("#console")
        text = console.inner_text()
        assert "[completed]" in text
        assert "codex:hello codex mini" in text

    def test_kimi_streaming_request(self, console_page: Page, tmp_path):
        console_page.select_option("#provider", "kimi")
        console_page.select_option("#model", "default")
        console_page.fill("#workspace_path", str(tmp_path.resolve()))
        console_page.fill("#prompt", "hello kimi")
        console_page.click("#send-button")

        console_page.wait_for_function(
            "document.getElementById('request-meta').textContent.includes('completed')",
            timeout=15_000,
        )

        console = console_page.locator("#console")
        text = console.inner_text()
        assert "[completed]" in text
        assert "kimi:hello kimi" in text


class TestFailedRequest:
    """Verify the UI handles failures gracefully."""

    def test_failed_request_shows_error(self, console_page: Page, tmp_path):
        console_page.select_option("#provider", "claude")
        console_page.select_option("#model", "sonnet")
        console_page.fill("#workspace_path", str(tmp_path.resolve()))
        console_page.fill("#prompt", "fail")
        console_page.click("#send-button")

        # Wait for the meta to update (either completed or error)
        console_page.wait_for_function(
            """
            (() => {
                const meta = document.getElementById('request-meta').textContent;
                return meta.includes('completed') || meta.includes('fail') || meta.includes('error');
            })()
            """,
            timeout=15_000,
        )

        console = console_page.locator("#console")
        text = console.inner_text()
        assert "[failed]" in text

    def test_worker_stays_ready_after_cli_failure(self, console_page: Page, tmp_path):
        """After a CLI failure the worker should still show 'ready'."""
        console_page.select_option("#provider", "claude")
        console_page.select_option("#model", "sonnet")
        console_page.fill("#workspace_path", str(tmp_path.resolve()))
        console_page.fill("#prompt", "fail")
        console_page.click("#send-button")

        console_page.wait_for_function(
            """
            (() => {
                const meta = document.getElementById('request-meta').textContent;
                return meta.includes('completed') || meta.includes('fail') || meta.includes('error');
            })()
            """,
            timeout=15_000,
        )

        # Refresh worker state
        console_page.click("#refresh-button")
        console_page.wait_for_timeout(1000)

        # The claude/sonnet worker should still be "ready" (not "down")
        chips = console_page.locator(".worker-chip")
        found_claude_sonnet = False
        for i in range(chips.count()):
            chip_text = chips.nth(i).inner_text()
            if "claude/sonnet" in chip_text:
                found_claude_sonnet = True
                assert "ready" in chip_text, f"Expected 'ready' but got: {chip_text}"
                break
        assert found_claude_sonnet, "claude/sonnet worker chip not found"

    def test_recovery_after_failure(self, console_page: Page, tmp_path):
        """After a failure, the next request should succeed."""
        # First: send a failing request
        console_page.select_option("#provider", "codex")
        console_page.select_option("#model", "codex-5.3")
        console_page.fill("#workspace_path", str(tmp_path.resolve()))
        console_page.fill("#prompt", "fail")
        console_page.click("#send-button")

        console_page.wait_for_function(
            """
            (() => {
                const meta = document.getElementById('request-meta').textContent;
                return meta.includes('completed') || meta.includes('fail') || meta.includes('error');
            })()
            """,
            timeout=15_000,
        )

        # Second: send a successful request (re-select provider since
        # the dropdowns may have been repopulated by the state refresh)
        console_page.select_option("#provider", "codex")
        console_page.select_option("#model", "codex-5.3")
        console_page.fill("#workspace_path", str(tmp_path.resolve()))
        console_page.fill("#prompt", "recover")
        console_page.click("#send-button")

        console_page.wait_for_function(
            "document.getElementById('request-meta').textContent.includes('completed')",
            timeout=15_000,
        )

        console = console_page.locator("#console")
        text = console.inner_text()
        assert "[completed]" in text
        assert "codex:recover" in text


class TestRefreshWorkerState:
    """The 'Refresh Worker State' button should update the chips."""

    def test_refresh_button_works(self, console_page: Page):
        console_page.click("#refresh-button")
        console_page.wait_for_timeout(500)
        meta = console_page.locator("#request-meta")
        expect(meta).to_have_text("State refreshed.")

    def test_workers_remain_after_refresh(self, console_page: Page):
        console_page.click("#refresh-button")
        console_page.wait_for_timeout(500)
        chips = console_page.locator(".worker-chip")
        expect(chips).to_have_count(7)


class TestModeToggle:
    """Resume mode should enable the session ref input."""

    def test_session_ref_disabled_in_new_mode(self, console_page: Page):
        console_page.select_option("#mode", "new")
        console_page.wait_for_timeout(100)
        session_input = console_page.locator("#provider_session_ref")
        expect(session_input).to_be_disabled()

    def test_session_ref_enabled_in_resume_mode(self, console_page: Page):
        console_page.select_option("#mode", "resume")
        console_page.wait_for_timeout(100)
        session_input = console_page.locator("#provider_session_ref")
        expect(session_input).to_be_enabled()
