from __future__ import annotations

import asyncio
from typing import Any

from ...models import ChatRequest, InstrumentName, MusicianInfo
from ...providers.base import ProviderAdapter
from ...shells import BashSession
from ..score import ScoreHandle
from .executor import _ExecutorMixin
from .runner import _RunnerMixin


class Musician(_RunnerMixin, _ExecutorMixin):
    def __init__(
        self,
        *,
        provider: InstrumentName,
        model: str,
        adapter: ProviderAdapter,
        executable: str,
        shell_path: str,
        default_options: dict[str, Any],
        session_models: dict[tuple[InstrumentName, str], str],
        cli_timeout: float = 300.0,
        idle_timeout: float = 300.0,
    ) -> None:
        self.provider = provider
        self.model = model
        self.adapter = adapter
        self.executable = executable
        self.shell_backend = shell_path
        self.default_options = default_options
        self.session_models = session_models
        self.cli_timeout = cli_timeout or 0.0
        self.idle_timeout = idle_timeout or 0.0
        self.shell = BashSession(shell_path)
        self.queue: asyncio.Queue[tuple[ChatRequest, ScoreHandle]] = asyncio.Queue()
        self.busy = False
        self.ready = False
        self.last_error: str | None = None
        self._runner_task: asyncio.Task[None] | None = None
        self._current_handle: ScoreHandle | None = None
        # Set during stop() so the runner supervisor knows the exit was
        # intentional and must NOT respawn the worker.
        self._stopping = False

    async def start(self) -> None:
        try:
            await self.shell.start()
            self.ready = True
            self.last_error = None
        except Exception as exc:  # pragma: no cover
            self.ready = False
            self.last_error = str(exc)
        self._stopping = False
        self._ensure_runner_alive()

    async def stop(self) -> None:
        self._stopping = True
        if self._runner_task:
            self._runner_task.cancel()
            try:
                await self._runner_task
            except asyncio.CancelledError:
                pass
            self._runner_task = None
        await self.shell.stop()

    async def submit(self, request: ChatRequest, handle: ScoreHandle | None = None) -> ScoreHandle:
        loop = asyncio.get_running_loop()
        handle = handle or ScoreHandle(
            result_future=loop.create_future(),
            provider=request.provider,
            model=request.model,
        )
        if handle.result_future is None:
            handle.result_future = loop.create_future()
        handle.provider = request.provider
        handle.model = request.model
        # Defensive: if a previous unhandled exception killed the worker
        # task, items would otherwise sit in the queue forever and the
        # caller would block indefinitely waiting for output. Resurrect
        # the supervisor before queueing so we always have a consumer.
        self._ensure_runner_alive()
        await self.queue.put((request, handle))
        return handle

    async def run_quick_command(self, script: str, timeout: float | None = None) -> tuple[int, str]:
        lines: list[str] = []

        async def collect(line: str) -> None:
            lines.append(line)

        coro = self.shell.run_script(script, collect)
        if timeout is not None:
            exit_code = await asyncio.wait_for(coro, timeout=timeout)
        else:
            exit_code = await coro
        return exit_code, "\n".join(lines)

    def info(self) -> MusicianInfo:
        return MusicianInfo(
            provider=self.provider,
            model=self.model,
            shell_backend=self.shell_backend,
            ready=self.ready,
            busy=self.busy,
            queue_length=self.queue.qsize(),
            last_error=self.last_error,
        )

    @property
    def is_idle(self) -> bool:
        return self.ready and not self.busy and self.queue.qsize() == 0
