from __future__ import annotations

import asyncio
import os
import re
import shutil
import subprocess
import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from pathlib import Path

_WINDOWS_DRIVE = re.compile(r"^(?P<drive>[A-Za-z]):[\\/](?P<rest>.*)$")


class ShellSessionError(RuntimeError):
    pass


@dataclass(slots=True)
class _ActiveRun:
    token: str
    on_line: Callable[[str], Awaitable[None]]
    future: asyncio.Future[int]
    started: bool = False


def to_bash_path(value: str) -> str:
    match = _WINDOWS_DRIVE.match(value)
    if match:
        rest = match.group("rest").replace("\\", "/")
        return f"/{match.group('drive').lower()}/{rest}"
    return value.replace("\\", "/")


def detect_bash_path(override: str | None = None) -> str:
    if override:
        return override
    if os.name != "nt":
        return shutil.which("bash") or "bash"

    candidates = [
        r"C:\Program Files\Git\bin\bash.exe",
        r"C:\Program Files\Git\usr\bin\bash.exe",
    ]
    for candidate in candidates:
        if Path(candidate).exists():
            return candidate
    return shutil.which("bash") or "bash"


class BashSession:
    def __init__(self, shell_path: str):
        self.shell_path = shell_path
        self.process: asyncio.subprocess.Process | None = None
        self._reader_task: asyncio.Task[None] | None = None
        self._current_run: _ActiveRun | None = None
        self._run_lock = asyncio.Lock()

    async def ensure_started(self) -> None:
        if self.process and self.process.returncode is None:
            return
        await self.start()

    async def start(self) -> None:
        if self.process and self.process.returncode is None:
            return
        kwargs: dict = {}
        env = {**os.environ, "PYTHONUTF8": "1"}
        if os.name == "nt":
            kwargs["creationflags"] = subprocess.CREATE_NO_WINDOW
        self.process = await asyncio.create_subprocess_exec(
            self.shell_path,
            "--noprofile",
            "--norc",
            "-s",
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
            env=env,
            **kwargs,
        )
        self._reader_task = asyncio.create_task(self._reader_loop())

    async def stop(self) -> None:
        process = self.process
        if process is None:
            return
        if process.stdin and not process.stdin.is_closing():
            process.stdin.write(b"exit\n")
            try:
                await process.stdin.drain()
            except ConnectionResetError:
                pass
        await process.wait()
        if self._reader_task:
            await self._reader_task

    async def run_script(self, script: str, on_line: Callable[[str], Awaitable[None]]) -> int:
        await self.ensure_started()
        assert self.process and self.process.stdin

        async with self._run_lock:
            token = uuid.uuid4().hex
            loop = asyncio.get_running_loop()
            future: asyncio.Future[int] = loop.create_future()
            self._current_run = _ActiveRun(token=token, on_line=on_line, future=future)
            wrapped = self._wrap_script(token, script)
            self.process.stdin.write(wrapped.encode("utf-8"))
            await self.process.stdin.drain()
            try:
                return await future
            finally:
                self._current_run = None

    def _wrap_script(self, token: str, script: str) -> str:
        begin = f"__AI_CLI_API_BEGIN__{token}"
        end = f"__AI_CLI_API_END__{token}"
        return (
            f"printf '%s\\n' '{begin}'\n"
            f"__ai_cli_exit=0\n"
            f"{script}\n"
            f"printf '%s:%s\\n' '{end}' \"$__ai_cli_exit\"\n"
        )

    async def _reader_loop(self) -> None:
        assert self.process and self.process.stdout
        while True:
            raw_line = await self.process.stdout.readline()
            if not raw_line:
                current = self._current_run
                if current and not current.future.done():
                    current.future.set_exception(ShellSessionError("bash worker terminated unexpectedly"))
                break

            line = raw_line.decode("utf-8", errors="replace").rstrip("\r\n")
            current = self._current_run
            if current is None:
                continue

            begin_marker = f"__AI_CLI_API_BEGIN__{current.token}"
            end_prefix = f"__AI_CLI_API_END__{current.token}:"
            if line == begin_marker:
                current.started = True
                continue
            if line.startswith(end_prefix):
                exit_code = int(line.split(":", 1)[1])
                if not current.future.done():
                    current.future.set_result(exit_code)
                current.started = False
                continue
            if current.started:
                await current.on_line(line)
