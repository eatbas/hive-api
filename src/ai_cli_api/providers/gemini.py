from __future__ import annotations

import shlex

from .base import CommandSpec, ParseState, ProviderAdapter
from ..models import ProviderName
from ..shells import to_bash_path


class GeminiAdapter(ProviderAdapter):
    name = ProviderName.GEMINI
    default_executable = "gemini"
    session_reference_format = "uuid"

    def build_new_command(self, *, executable: str, prompt: str, model: str, provider_options: dict) -> CommandSpec:
        argv = [executable, "-p", prompt, "-o", "stream-json"]
        self._apply_model_override(argv, model, flag="-m")
        argv.extend(self._extra_args(provider_options))
        return CommandSpec(argv=argv)

    def build_resume_command(self, *, executable: str, prompt: str, model: str, session_ref: str, provider_options: dict) -> CommandSpec:
        # Store UUID in preset_session_ref; make_shell_script maps it to an index at runtime.
        argv = [executable, "-p", prompt, "-o", "stream-json", "--resume", "__GEMINI_IDX__"]
        self._apply_model_override(argv, model, flag="-m")
        argv.extend(self._extra_args(provider_options))
        return CommandSpec(argv=argv, preset_session_ref=session_ref)

    def make_shell_script(self, workspace_path: str, command: CommandSpec) -> str:
        workspace = shlex.quote(to_bash_path(workspace_path))
        shell_command = shlex.join(self._normalize_argv(command.argv))

        # For resume commands, look up the UUID→index before running.
        if "__GEMINI_IDX__" in shell_command:
            session_uuid = command.preset_session_ref or ""
            executable = command.argv[0]
            exe_bash = shlex.quote(to_bash_path(executable) if executable else "gemini")
            resume_cmd = shell_command.replace("__GEMINI_IDX__", '"$__gemini_idx"')
            return (
                f"if ! cd -- {workspace}; then\n"
                f"  echo 'Failed to enter workspace: {workspace_path}'\n"
                f"  __ai_cli_exit=97\n"
                f"else\n"
                f"  __gemini_idx=$({exe_bash} --list-sessions < /dev/null 2>/dev/null"
                f" | grep '\\[{session_uuid}\\]'"
                f" | head -1 | sed 's/^ *//' | cut -d. -f1)\n"
                f"  if [ -z \"$__gemini_idx\" ]; then\n"
                f"    echo '{{\"type\":\"error\",\"message\":\"Session {session_uuid} not found in gemini --list-sessions\"}}'\n"
                f"    __ai_cli_exit=98\n"
                f"  else\n"
                f"    {resume_cmd} < /dev/null\n"
                f"    __ai_cli_exit=$?\n"
                f"  fi\n"
                f"fi"
            )

        return super().make_shell_script(workspace_path, command)

    def parse_output_line(self, line: str, state: ParseState) -> list[dict[str, object]]:
        obj = self._parse_json_or_warn(line, state)
        if obj is None:
            return []

        events: list[dict[str, object]] = []
        if obj.get("type") == "init" and obj.get("session_id"):
            state.session_ref = str(obj["session_id"])
            events.append({"type": "provider_session", "provider_session_ref": state.session_ref})
        if obj.get("type") == "message" and obj.get("role") == "assistant":
            events.extend(self._append_chunk(state, str(obj.get("content", ""))))
        if obj.get("type") == "result" and obj.get("status") != "success":
            state.error_message = str(obj)
        return events
