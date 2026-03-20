from __future__ import annotations

from enum import StrEnum
from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator, model_validator


class ProviderName(StrEnum):
    GEMINI = "gemini"
    CODEX = "codex"
    CLAUDE = "claude"
    KIMI = "kimi"


class ChatMode(StrEnum):
    NEW = "new"
    RESUME = "resume"


class ChatRequest(BaseModel):
    provider: ProviderName
    model: str = Field(min_length=1)
    workspace_path: str = Field(min_length=1)
    mode: ChatMode
    prompt: str = Field(min_length=1)
    provider_session_ref: str | None = None
    stream: bool = True
    provider_options: dict[str, Any] = Field(default_factory=dict)

    @field_validator("workspace_path")
    @classmethod
    def workspace_path_must_be_absolute(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("workspace_path must not be empty")
        if normalized.startswith("/"):
            return normalized
        if len(normalized) >= 3 and normalized[1:3] == ":\\":
            return normalized
        if len(normalized) >= 3 and normalized[1:3] == ":/":
            return normalized
        raise ValueError("workspace_path must be an absolute path")

    @model_validator(mode="after")
    def validate_resume_fields(self) -> "ChatRequest":
        if self.mode is ChatMode.RESUME and not self.provider_session_ref:
            raise ValueError("provider_session_ref is required for resume mode")
        return self


class ProviderCapability(BaseModel):
    provider: ProviderName
    executable: str | None
    enabled: bool
    supports_resume: bool
    supports_streaming: bool
    supports_model_override: bool
    session_reference_format: str


class WorkerInfo(BaseModel):
    provider: ProviderName
    model: str
    shell_backend: str
    ready: bool
    busy: bool
    queue_length: int
    last_error: str | None = None


class HealthResponse(BaseModel):
    status: Literal["ok", "degraded"]
    config_path: str
    shell_path: str | None
    workers_booted: bool
    worker_count: int
    details: list[str] = Field(default_factory=list)


class ChatResponse(BaseModel):
    provider: ProviderName
    model: str
    provider_session_ref: str | None
    final_text: str
    exit_code: int
    warnings: list[str] = Field(default_factory=list)
