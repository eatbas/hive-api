from __future__ import annotations

from typing import Any

from .base import CommandSpec, ParseState, ProviderAdapter
from ..models import ProviderName


class OpenCodeAdapter(ProviderAdapter):
    """Adapter for the OpenCode CLI (opencode-ai)."""

    name = ProviderName.OPENCODE
    default_executable = "opencode"
    session_reference_format = "opaque-string"

    # Default provider prefix for models that don't already include one.
    _DEFAULT_PROVIDER = "zai-coding-plan"

    def _resolve_model(self, model: str) -> str:
        """Ensure the model has a provider/ prefix for the CLI."""
        if "/" in model or model == "default":
            return model
        return f"{self._DEFAULT_PROVIDER}/{model}"

    def build_new_command(
        self,
        *,
        executable: str,
        prompt: str,
        model: str,
        provider_options: dict[str, Any],
    ) -> CommandSpec:
        argv = [executable, "run", "--format", "json"]
        self._apply_model_override(argv, self._resolve_model(model))
        argv.extend(self._extra_args(provider_options))
        argv.append(prompt)
        return CommandSpec(argv=argv)

    def build_resume_command(
        self,
        *,
        executable: str,
        prompt: str,
        model: str,
        session_ref: str,
        provider_options: dict[str, Any],
    ) -> CommandSpec:
        argv = [executable, "run", "--format", "json", "--session", session_ref]
        self._apply_model_override(argv, self._resolve_model(model))
        argv.extend(self._extra_args(provider_options))
        argv.append(prompt)
        return CommandSpec(argv=argv, preset_session_ref=session_ref)

    def parse_output_line(self, line: str, state: ParseState) -> list[dict[str, Any]]:
        obj = self._parse_json_or_warn(line, state)
        if obj is None:
            return []

        events: list[dict[str, Any]] = []
        event_type = obj.get("type", "")

        # Session ID is at the top level of every JSON event
        session_id = obj.get("sessionID") or obj.get("sessionId") or obj.get("session_id")
        if not session_id:
            part = obj.get("part", {})
            if isinstance(part, dict):
                session_id = part.get("sessionID")

        if session_id and state.session_ref != str(session_id):
            state.session_ref = str(session_id)
            events.append({"type": "provider_session", "provider_session_ref": state.session_ref})

        # Text content: type "text" with part.text
        if event_type == "text":
            part = obj.get("part", {})
            if isinstance(part, dict):
                text = part.get("text", "")
                if isinstance(text, str) and text:
                    events.extend(self._append_chunk(state, text))

        # Error handling
        if event_type == "error" or obj.get("error"):
            error_data = obj.get("error") or obj.get("part", {}).get("error")
            state.error_message = str(error_data or obj.get("message", str(obj)))

        return events
