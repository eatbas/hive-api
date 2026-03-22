from __future__ import annotations

from .base import CommandSpec, ParseState, ProviderAdapter
from ..models import ProviderName


class CodexAdapter(ProviderAdapter):
    name = ProviderName.CODEX
    default_executable = "codex"
    session_reference_format = "thread-id"
    model_aliases = {
        "codex-5.3": "gpt-5.3-codex",
    }

    def build_new_command(self, *, executable: str, prompt: str, model: str, provider_options: dict) -> CommandSpec:
        argv = [executable, "exec", "--json", "--full-auto", "--skip-git-repo-check"]
        self._apply_model_override(argv, self._resolve_model(model), flag="-m")
        argv.extend(self._extra_args(provider_options))
        argv.append(prompt)
        return CommandSpec(argv=argv)

    def build_resume_command(self, *, executable: str, prompt: str, model: str, session_ref: str, provider_options: dict) -> CommandSpec:
        argv = [executable, "exec", "resume", "--json", "--full-auto"]
        self._apply_model_override(argv, self._resolve_model(model), flag="-m")
        argv.extend(self._extra_args(provider_options))
        argv.extend([session_ref, prompt])
        return CommandSpec(argv=argv, preset_session_ref=session_ref)

    def parse_output_line(self, line: str, state: ParseState) -> list[dict[str, object]]:
        obj = self._parse_json_or_warn(line, state)
        if obj is None:
            return []

        events: list[dict[str, object]] = []
        if obj.get("type") == "thread.started" and obj.get("thread_id"):
            state.session_ref = str(obj["thread_id"])
            events.append({"type": "provider_session", "provider_session_ref": state.session_ref})

        if obj.get("type") == "item.completed":
            item = obj.get("item", {})
            item_type = item.get("type")
            if item_type == "agent_message":
                events.extend(self._append_chunk(state, str(item.get("text", ""))))
            elif item_type == "error":
                state.warnings.append(str(item.get("message", "Codex reported an error item")))
        return events

    def _resolve_model(self, model: str) -> str:
        return self.model_aliases.get(model, model)
