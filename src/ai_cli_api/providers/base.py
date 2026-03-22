from __future__ import annotations

import json
import shlex
import shutil
import uuid
from dataclasses import dataclass, field
from typing import Any

from ..models import ChatMode, ProviderName
from ..shells import to_bash_path


def check_cli_available(executable: str) -> bool:
    """Return True if *executable* is found on PATH or at the given path.

    Works for both bare command names (``'claude'``) and absolute paths
    (``'/usr/local/bin/claude'``).
    """
    return shutil.which(executable) is not None


@dataclass(slots=True)
class CommandSpec:
    argv: list[str]
    preset_session_ref: str | None = None


@dataclass(slots=True)
class ParseState:
    session_ref: str | None = None
    warnings: list[str] = field(default_factory=list)
    output_chunks: list[str] = field(default_factory=list)
    last_emitted_chunk: str | None = None
    error_message: str | None = None


class ProviderAdapter:
    name: ProviderName
    supports_resume = True
    supports_streaming = True
    supports_model_override = True
    session_reference_format = "provider-native"
    default_executable: str

    def resolve_executable(self, override: str | None) -> str:
        return override or self.default_executable

    def is_available(self, override: str | None = None) -> bool:
        """Check whether the resolved CLI executable is findable on PATH."""
        return check_cli_available(self.resolve_executable(override))

    def build_command(
        self,
        *,
        executable: str,
        mode: ChatMode,
        prompt: str,
        model: str,
        session_ref: str | None,
        provider_options: dict[str, Any],
    ) -> CommandSpec:
        if mode is ChatMode.NEW:
            return self.build_new_command(
                executable=executable,
                prompt=prompt,
                model=model,
                provider_options=provider_options,
            )
        if session_ref is None:
            raise ValueError("session_ref required for resume mode")
        return self.build_resume_command(
            executable=executable,
            prompt=prompt,
            model=model,
            session_ref=session_ref,
            provider_options=provider_options,
        )

    def build_new_command(
        self,
        *,
        executable: str,
        prompt: str,
        model: str,
        provider_options: dict[str, Any],
    ) -> CommandSpec:
        raise NotImplementedError

    def build_resume_command(
        self,
        *,
        executable: str,
        prompt: str,
        model: str,
        session_ref: str,
        provider_options: dict[str, Any],
    ) -> CommandSpec:
        raise NotImplementedError

    def initial_parse_state(self, preset_session_ref: str | None = None) -> ParseState:
        return ParseState(session_ref=preset_session_ref)

    def parse_output_line(self, line: str, state: ParseState) -> list[dict[str, Any]]:
        raise NotImplementedError

    def make_shell_script(self, workspace_path: str, command: CommandSpec) -> str:
        workspace = shlex.quote(to_bash_path(workspace_path))
        shell_command = shlex.join(self._normalize_argv(command.argv))
        return (
            f"if ! cd -- {workspace}; then\n"
            f"  echo 'Failed to enter workspace: {workspace_path}'\n"
            f"  __ai_cli_exit=97\n"
            f"else\n"
            f"  {shell_command} < /dev/null\n"
            f"  __ai_cli_exit=$?\n"
            f"fi"
        )

    def _normalize_argv(self, argv: list[str]) -> list[str]:
        normalized: list[str] = []
        for arg in argv:
            if len(arg) >= 3 and arg[1:3] == ":\\":
                normalized.append(to_bash_path(arg))
            else:
                normalized.append(arg)
        return normalized

    def _extra_args(self, provider_options: dict[str, Any]) -> list[str]:
        raw = provider_options.get("extra_args", [])
        if raw is None:
            return []
        if not isinstance(raw, list) or any(not isinstance(item, str) for item in raw):
            raise ValueError("provider_options.extra_args must be a list of strings")
        return raw

    def _apply_model_override(self, argv: list[str], model: str, *, flag: str = "--model") -> None:
        if model != "default":
            argv.extend([flag, model])

    def _parse_json_or_warn(self, line: str, state: ParseState) -> dict[str, Any] | None:
        obj = self._parse_json(line)
        if obj is None:
            state.warnings.append(line)
            return None
        return obj

    def _append_chunk(self, state: ParseState, chunk: str) -> list[dict[str, Any]]:
        text = chunk.strip()
        if not text:
            return []
        if state.last_emitted_chunk == text:
            return []
        state.last_emitted_chunk = text
        state.output_chunks.append(text)
        return [{"type": "output_delta", "text": text}]

    def _parse_json(self, line: str) -> dict[str, Any] | None:
        try:
            return json.loads(line)
        except json.JSONDecodeError:
            return None

    def new_session_ref(self) -> str | None:
        return None

    def _uuid(self) -> str:
        return str(uuid.uuid4())
