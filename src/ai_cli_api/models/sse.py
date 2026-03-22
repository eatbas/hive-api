from __future__ import annotations

from pydantic import BaseModel, Field

from .enums import ProviderName


class SSERunStarted(BaseModel):
    """SSE event emitted when a CLI process starts."""

    provider: ProviderName = Field(description="Provider handling the request.")
    model: str = Field(description="Model being used.")


class SSEProviderSession(BaseModel):
    """SSE event emitted when a session reference is known."""

    provider_session_ref: str = Field(description="Session reference for resuming later.")


class SSEOutputDelta(BaseModel):
    """SSE event emitted for each output chunk."""

    text: str = Field(description="Incremental output text from the provider.")


class SSECompleted(BaseModel):
    """SSE event emitted when the CLI process succeeds."""

    provider: ProviderName = Field(description="Provider that handled the request.")
    model: str = Field(description="Model that was used.")
    provider_session_ref: str | None = Field(description="Session reference for resuming later.")
    final_text: str = Field(description="Complete accumulated output text.")
    exit_code: int = Field(description="CLI exit code (0 = success).")
    warnings: list[str] = Field(default_factory=list, description="Non-fatal warnings.")


class SSEFailed(BaseModel):
    """SSE event emitted when the CLI process fails."""

    provider: ProviderName = Field(description="Provider that handled the request.")
    model: str = Field(description="Model that was used.")
    provider_session_ref: str | None = Field(description="Session reference, if assigned.")
    exit_code: int = Field(description="CLI exit code (non-zero).")
    warnings: list[str] = Field(default_factory=list, description="Non-fatal warnings.")
    error: str = Field(description="Failure message.")
