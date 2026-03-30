from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from .enums import ChatMode, ScoreStatus, InstrumentName


class ChatRequest(BaseModel):
    """Request body for submitting a prompt to an AI CLI instrument."""

    provider: InstrumentName = Field(description="AI CLI instrument to use for this chat session.")
    model: str = Field(
        min_length=1,
        description="Model identifier within the instrument (e.g. 'sonnet', 'opus', 'codex-mini').",
    )
    workspace_path: str = Field(
        min_length=1,
        description=(
            "Absolute path to the workspace directory for the CLI session. "
            "Must start with '/' (Unix) or a drive letter like 'C:\\' (Windows)."
        ),
    )
    mode: ChatMode = Field(
        description="'new' starts a fresh session; 'resume' continues a previous conversation.",
    )
    prompt: str = Field(min_length=1, description="Prompt or instruction to send to the AI instrument.")
    provider_session_ref: str | None = Field(
        default=None,
        description="Required when mode is 'resume'. Obtained from prior chat output.",
    )
    stream: bool = Field(
        default=True,
        description="When true (default), returns Server-Sent Events. Otherwise returns JSON.",
    )
    provider_options: dict[str, Any] = Field(
        default_factory=dict,
        description=(
            "Instrument-specific passthrough options. "
            "Common keys: extra_args (list[str]) for raw CLI flags; "
            "effort ('low'|'medium'|'high') and max_turns (int) for Claude."
        ),
    )

    model_config = ConfigDict(
        json_schema_extra={
            "examples": [
                {
                    "provider": "claude",
                    "model": "sonnet",
                    "workspace_path": "/home/user/project",
                    "mode": "new",
                    "prompt": "Explain the main entry point of this project.",
                    "stream": True,
                    "provider_options": {},
                },
                {
                    "provider": "claude",
                    "model": "sonnet",
                    "workspace_path": "/home/user/project",
                    "mode": "resume",
                    "prompt": "Now refactor that function to use async/await.",
                    "provider_session_ref": "a1b2c3d4-e5f6-7890-abcd-ef1234567890",
                    "stream": False,
                    "provider_options": {"extra_args": ["--verbose"]},
                },
            ]
        }
    )

    @field_validator("workspace_path")
    @classmethod
    def workspace_path_must_be_absolute(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("workspace_path must not be empty")
        if normalized.startswith("/"):
            return normalized
        if len(normalized) >= 3 and normalized[1:3] in {":\\", ":/"}:
            return normalized
        raise ValueError("workspace_path must be an absolute path")

    @model_validator(mode="after")
    def validate_resume_fields(self) -> "ChatRequest":
        if self.mode is ChatMode.RESUME and not self.provider_session_ref:
            raise ValueError("provider_session_ref is required for resume mode")
        return self


class ChatResponse(BaseModel):
    """Response returned for non-streaming chat requests."""

    provider: InstrumentName = Field(description="Instrument that handled the request.")
    model: str = Field(description="Model that was used.")
    provider_session_ref: str | None = Field(description="Session reference that can be used for resume.")
    final_text: str = Field(description="Complete accumulated output text.")
    exit_code: int = Field(description="CLI process exit code. 0 indicates success.")
    warnings: list[str] = Field(default_factory=list, description="Non-fatal warnings.")
    score_id: str | None = Field(default=None, description="Score ID for tracking and cancellation.")

    model_config = ConfigDict(
        json_schema_extra={
            "examples": [
                {
                    "provider": "claude",
                    "model": "sonnet",
                    "provider_session_ref": "a1b2c3d4-e5f6-7890-abcd-ef1234567890",
                    "final_text": "The main entry point is in main.py.",
                    "exit_code": 0,
                    "warnings": [],
                    "score_id": "a1b2c3d4e5f67890abcdef1234567890",
                }
            ]
        }
    )


class StopResponse(BaseModel):
    """Response returned when a score stop is requested."""

    score_id: str = Field(description="ID of the score.")
    status: ScoreStatus = Field(description="Resulting score status after the stop request.")
    provider: InstrumentName | None = Field(default=None, description="Instrument of the score, if known.")
    model: str | None = Field(default=None, description="Model of the score, if known.")
