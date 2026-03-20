from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from typing import Any

from .config import AppConfig, ProviderConfig
from .models import ChatRequest, ChatResponse, ProviderCapability, ProviderName, WorkerInfo
from .providers.base import ParseState, ProviderAdapter
from .providers.registry import build_provider_registry
from .shells import BashSession, ShellSessionError, detect_bash_path


def _safe_error_message(exc: BaseException) -> str:
    """Return a non-empty error description for *any* exception."""
    msg = str(exc)
    if msg:
        return msg
    return repr(exc) or type(exc).__name__ or "unknown error"


@dataclass(slots=True)
class JobHandle:
    events: asyncio.Queue[dict[str, Any]] = field(default_factory=asyncio.Queue)
    result_future: asyncio.Future[ChatResponse] | None = None

    async def publish(self, event: dict[str, Any]) -> None:
        await self.events.put(event)


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
        except Exception as exc:  # pragma: no cover - startup failures are surfaced via health.
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
        """Run a short command on this worker's shell, returning (exit_code, output).

        Only safe to call when the worker is idle (not busy, empty queue).
        """
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

                # Only mark the worker as "down" when the bash shell
                # itself has died.  CLI-level failures (non-zero exit
                # code, bad model, validation errors) leave the shell
                # alive and the worker should stay ready.
                shell_alive = (
                    self.shell.process is not None
                    and self.shell.process.returncode is None
                )
                if not shell_alive:
                    self.ready = False

                # _execute_request already publishes a detailed
                # "failed" event for CLI errors.  Publish a fallback
                # only when the failure happened before that (e.g.
                # validation, shell crash).
                failure = {
                    "type": "failed",
                    "error": error_msg,
                    "provider": self.provider.value,
                    "model": self.model,
                }
                await handle.publish(failure)
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
            await handle.publish(
                {
                    "type": "provider_session",
                    "provider_session_ref": parse_state.session_ref,
                }
            )

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
            error_message = (
                parse_state.error_message
                or f"{self.provider.value} exited with code {exit_code}"
            )
            if not error_message:
                error_message = f"{self.provider.value} command failed (exit {exit_code})"
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


class WorkerManager:
    def __init__(self, config: AppConfig):
        self.config = config
        self.shell_path = detect_bash_path(config.shell.path)
        self.registry = build_provider_registry()
        self.workers: dict[tuple[ProviderName, str], WarmWorker] = {}
        self.session_models: dict[tuple[ProviderName, str], str] = {}

    async def start(self) -> None:
        for provider, provider_config in self.config.providers.items():
            if not provider_config.enabled:
                continue
            adapter = self.registry[provider]
            executable = adapter.resolve_executable(provider_config.executable)
            for model in provider_config.models:
                worker = WarmWorker(
                    provider=provider,
                    model=model,
                    adapter=adapter,
                    executable=executable,
                    shell_path=self.shell_path,
                    default_options=provider_config.default_options,
                    session_models=self.session_models,
                )
                await worker.start()
                self.workers[(provider, model)] = worker

    async def stop(self) -> None:
        await asyncio.gather(*(worker.stop() for worker in self.workers.values()), return_exceptions=True)

    def get_worker(self, provider: ProviderName, model: str) -> WarmWorker | None:
        return self.workers.get((provider, model))

    def capabilities(self) -> list[ProviderCapability]:
        capabilities: list[ProviderCapability] = []
        for provider, adapter in self.registry.items():
            provider_config: ProviderConfig = self.config.providers[provider]
            capabilities.append(
                ProviderCapability(
                    provider=provider,
                    executable=adapter.resolve_executable(provider_config.executable),
                    enabled=provider_config.enabled,
                    supports_resume=adapter.supports_resume,
                    supports_streaming=adapter.supports_streaming,
                    supports_model_override=adapter.supports_model_override,
                    session_reference_format=adapter.session_reference_format,
                )
            )
        return capabilities

    def worker_info(self) -> list[WorkerInfo]:
        return [worker.info() for worker in self.workers.values()]

    def workers_for_provider(self, provider: ProviderName) -> list[WarmWorker]:
        return [w for (p, _), w in self.workers.items() if p == provider]

    async def restart_provider(self, provider: ProviderName) -> None:
        for worker in self.workers_for_provider(provider):
            await worker.stop()
            await worker.start()

    def get_idle_worker(self, provider: ProviderName) -> WarmWorker | None:
        """Return the first idle, ready worker for *provider*, or None."""
        for worker in self.workers_for_provider(provider):
            if worker.ready and not worker.busy and worker.queue.qsize() == 0:
                return worker
        return None

    async def get_bash_version(self) -> str | None:
        """Get the bash version using any available idle worker shell."""
        for worker in self.workers.values():
            if worker.ready and not worker.busy and worker.queue.qsize() == 0:
                try:
                    _, output = await worker.run_quick_command("bash --version | head -1\n__ai_cli_exit=0")
                    return output.strip() if output.strip() else None
                except Exception:
                    return None
        return None

    def health_details(self) -> list[str]:
        details: list[str] = []
        for worker in self.workers.values():
            if worker.last_error:
                details.append(f"{worker.provider.value}/{worker.model}: {worker.last_error}")
        return details
