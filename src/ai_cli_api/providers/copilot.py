from __future__ import annotations

from .base import CommandSpec, ParseState, ProviderAdapter
from ..models import ProviderName


class CopilotAdapter(ProviderAdapter):
    name = ProviderName.COPILOT
    default_executable = "copilot"
    session_reference_format = "uuid"

    def build_new_command(self, *, executable: str, prompt: str, model: str, provider_options: dict) -> CommandSpec:
        argv = [
            executable,
            "-p",
            prompt,
            "--output-format",
            "json",
            "--allow-all-tools",
            "--no-ask-user",
            "--no-auto-update",
        ]
        self._apply_model_override(argv, model)
        argv.extend(self._extra_args(provider_options))
        return CommandSpec(argv=argv)

    def build_resume_command(self, *, executable: str, prompt: str, model: str, session_ref: str, provider_options: dict) -> CommandSpec:
        argv = [
            executable,
            "-p",
            prompt,
            "--output-format",
            "json",
            "--allow-all-tools",
            "--no-ask-user",
            "--no-auto-update",
            "--resume",
            session_ref,
        ]
        self._apply_model_override(argv, model)
        argv.extend(self._extra_args(provider_options))
        return CommandSpec(argv=argv, preset_session_ref=session_ref)

    def parse_output_line(self, line: str, state: ParseState) -> list[dict[str, object]]:
        obj = self._parse_json_or_warn(line, state)
        if obj is None:
            return []

        events: list[dict[str, object]] = []
        event_type = obj.get("type", "")
        data = obj.get("data", {})

        # Text output: assistant.message → data.content (plain string)
        if event_type == "assistant.message" and isinstance(data, dict):
            content = data.get("content", "")
            if content:
                events.extend(self._append_chunk(state, str(content)))

        # Session ID and exit code from the final "result" event
        if event_type == "result":
            session_id = obj.get("sessionId")
            if session_id and state.session_ref != str(session_id):
                state.session_ref = str(session_id)
                events.append({"type": "provider_session", "provider_session_ref": state.session_ref})
            exit_code = obj.get("exitCode")
            if exit_code is not None and exit_code != 0:
                state.error_message = f"Copilot exited with code {exit_code}"

        return events

    def make_shell_script(self, workspace_path: str, command: CommandSpec) -> str:
        augmented_argv = list(command.argv) + ["--add-dir", workspace_path]
        augmented_command = CommandSpec(
            argv=augmented_argv,
            preset_session_ref=command.preset_session_ref,
        )
        return super().make_shell_script(workspace_path, augmented_command)
