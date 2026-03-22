from __future__ import annotations

import asyncio
from typing import Any

from ..models import ChatRequest, ChatResponse, ProviderName, WorkerInfo
from ..providers.base import ProviderAdapter
from ..shells import BashSession, ShellSessionError
from .handle import JobHandle, _safe_error_message


class WarmWorker:
    def __init__(
        self,
        *,
        provider: ProviderName,
        model: str,
        adapter: ProviderAdapter,
        executable: str,
        shell_path: str,
        default_options: dict[str, Any],
        session_models: dict[tuple[ProviderName, str], str],
    ) -> None:
        self.provider = provider
        self.model = model
        self.adapter = adapter
        self.executable = executable
        self.shell_backend = shell_path
        self.default_options = default_options
        self.session_models = session_models
        self.shell = BashSession(shell_path)
        self.queue: asyncio.Queue[tuple[ChatRequest, JobHandle]] = asyncio.Queue()
        self.busy = False
        self.ready = False
        self.last_error: str | None = None
        self._runner_task: asyncio.Task[None] | None = None

    async def start(self) -> None:
        try:
            await self.shell.start()
            self.ready = True
            self.last_error = None
        except Exception as exc:  # pragma: no cover
            self.ready = False
            self.last_error = str(exc)
        if self._runner_task is None:
            self._runner_task = asyncio.create_task(self._run())

    async def stop(self) -> None:
        if self._runner_task:
            self._runner_task.cancel()
            try:
                await self._runner_task
            except asyncio.CancelledError:
                pass
        await self.shell.stop()

    async def submit(self, request: ChatRequest) -> JobHandle:
        loop = asyncio.get_running_loop()
        handle = JobHandle(result_future=loop.create_future())
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

    def info(self) -> WorkerInfo:
        return WorkerInfo(
            provider=self.provider,
            model=self.model,
            shell_backend=self.shell_backend,
            ready=self.ready,
            busy=self.busy,
            queue_length=self.queue.qsize(),
            last_error=self.last_error,
        )

    async def _run(self) -> None:
        while True:
            request, handle = await self.queue.get()
            self.busy = True
            try:
                if not self.ready or self.shell.process is None or self.shell.process.returncode is not None:
                    await self.shell.start()
                    self.ready = True
                    self.last_error = None
                response = await self._execute_request(request, handle)
                if handle.result_future and not handle.result_future.done():
                    handle.result_future.set_result(response)
            except Exception as exc:
                error_msg = _safe_error_message(exc)
                self.last_error = error_msg

                shell_alive = self.shell.process is not None and self.shell.process.returncode is None
                if not shell_alive:
                    self.ready = False

                await handle.publish(
                    {
                        "type": "failed",
                        "error": error_msg,
                        "provider": self.provider.value,
                        "model": self.model,
                    }
                )
                if handle.result_future and not handle.result_future.done():
                    handle.result_future.set_exception(exc)
            finally:
                self.busy = False
                self.queue.task_done()

    async def _execute_request(self, request: ChatRequest, handle: JobHandle) -> ChatResponse:
        if request.mode.value == "resume" and request.provider_session_ref:
            existing_model = self.session_models.get((self.provider, request.provider_session_ref))
            if existing_model and existing_model != request.model:
                raise ShellSessionError(
                    f"Session {request.provider_session_ref} was created under model "
                    f"{existing_model} and cannot be resumed with {request.model}"
                )

        provider_options = {**self.default_options, **request.provider_options}
        command = self.adapter.build_command(
            executable=self.executable,
            mode=request.mode,
            prompt=request.prompt,
            model=request.model,
            session_ref=request.provider_session_ref,
            provider_options=provider_options,
        )
        parse_state = self.adapter.initial_parse_state(command.preset_session_ref or request.provider_session_ref)

        await handle.publish(
            {
                "type": "run_started",
                "provider": self.provider.value,
                "model": request.model,
            }
        )
        if parse_state.session_ref:
            await handle.publish({"type": "provider_session", "provider_session_ref": parse_state.session_ref})

        async def on_line(line: str) -> None:
            for event in self.adapter.parse_output_line(line, parse_state):
                await handle.publish(event)

        script = self.adapter.make_shell_script(request.workspace_path, command)
        exit_code = await self.shell.run_script(script, on_line)

        final_text = "\n".join(parse_state.output_chunks).strip()
        response = ChatResponse(
            provider=self.provider,
            model=request.model,
            provider_session_ref=parse_state.session_ref,
            final_text=final_text,
            exit_code=exit_code,
            warnings=parse_state.warnings,
        )

        if parse_state.error_message or exit_code != 0:
            error_message = parse_state.error_message or f"{self.provider.value} exited with code {exit_code}"
            await handle.publish(
                {
                    "type": "failed",
                    "provider": self.provider.value,
                    "model": request.model,
                    "provider_session_ref": parse_state.session_ref,
                    "exit_code": exit_code,
                    "warnings": parse_state.warnings,
                    "error": error_message,
                }
            )
            raise ShellSessionError(error_message)

        if parse_state.session_ref:
            self.session_models[(self.provider, parse_state.session_ref)] = request.model

        await handle.publish(
            {
                "type": "completed",
                "provider": self.provider.value,
                "model": request.model,
                "provider_session_ref": parse_state.session_ref,
                "final_text": final_text,
                "exit_code": exit_code,
                "warnings": parse_state.warnings,
            }
        )
        return response
