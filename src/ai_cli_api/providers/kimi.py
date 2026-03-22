from __future__ import annotations

import shlex

from .base import CommandSpec, ParseState, ProviderAdapter
from ..models import ProviderName
from ..shells import to_bash_path


class KimiAdapter(ProviderAdapter):
    name = ProviderName.KIMI
    default_executable = "kimi"
    session_reference_format = "opaque-string"

    def new_session_ref(self) -> str | None:
        return self._uuid()

    def build_new_command(self, *, executable: str, prompt: str, model: str, provider_options: dict) -> CommandSpec:
        session_ref = self.new_session_ref()
        argv = [
            executable,
            "--session",
            session_ref,
            "--print",
            "--prompt",
            prompt,
            "--output-format",
            "stream-json",
        ]
        self._apply_model_override(argv, model)
        argv.extend(self._extra_args(provider_options))
        return CommandSpec(argv=argv, preset_session_ref=session_ref)

    def build_resume_command(self, *, executable: str, prompt: str, model: str, session_ref: str, provider_options: dict) -> CommandSpec:
        argv = [
            executable,
            "--session",
            session_ref,
            "--print",
            "--prompt",
            prompt,
            "--output-format",
            "stream-json",
        ]
        self._apply_model_override(argv, model)
        argv.extend(self._extra_args(provider_options))
        return CommandSpec(argv=argv, preset_session_ref=session_ref)

    def make_shell_script(self, workspace_path: str, command: CommandSpec) -> str:
        workspace = shlex.quote(to_bash_path(workspace_path))
        shell_command = shlex.join(self._normalize_argv(command.argv))
        return (
            f"export PYTHONIOENCODING=utf-8\n"
            f"if ! cd -- {workspace}; then\n"
            f"  echo 'Failed to enter workspace: {workspace_path}'\n"
            f"  __ai_cli_exit=97\n"
            f"else\n"
            f"  {shell_command} < /dev/null\n"
            f"  __ai_cli_exit=$?\n"
            f"fi"
        )

    def parse_output_line(self, line: str, state: ParseState) -> list[dict[str, object]]:
        obj = self._parse_json_or_warn(line, state)
        if obj is None:
            return []

        events: list[dict[str, object]] = []
        for item in obj.get("content", []):
            if item.get("type") == "text":
                events.extend(self._append_chunk(state, str(item.get("text", ""))))
        return events
