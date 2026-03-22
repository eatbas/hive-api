from __future__ import annotations

from enum import StrEnum
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------

class ProviderName(StrEnum):
    """Supported AI CLI provider identifiers."""
    GEMINI = "gemini"
    CODEX = "codex"
    CLAUDE = "claude"
    KIMI = "kimi"
    COPILOT = "copilot"
    OPENCODE = "opencode"


class ChatMode(StrEnum):
    """Whether to start a new session or resume an existing one."""
    NEW = "new"
    RESUME = "resume"


# ---------------------------------------------------------------------------
# Request / Response models
# ---------------------------------------------------------------------------

class ChatRequest(BaseModel):
    """Request body for submitting a prompt to an AI CLI provider.

    Supports both new sessions and resuming previous conversations.
    The response can be delivered as a single JSON object or as a
    Server-Sent Events stream.
    """

    provider: ProviderName = Field(
        description="AI CLI provider to use for this chat session.",
    )
    model: str = Field(
        min_length=1,
        description="Model identifier within the provider (e.g. 'sonnet', 'opus', 'codex-mini').",
    )
    workspace_path: str = Field(
        min_length=1,
        description="Absolute path to the workspace directory for the CLI session. Must start with '/' (Unix) or a drive letter like 'C:\\' (Windows).",
    )
    mode: ChatMode = Field(
        description="'new' starts a fresh session; 'resume' continues a previous conversation (requires provider_session_ref).",
    )
    prompt: str = Field(
        min_length=1,
        description="The prompt or instruction to send to the AI provider.",
    )
    provider_session_ref: str | None = Field(
        default=None,
        description="Session reference for resuming a previous conversation. Required when mode is 'resume'. Obtained from a prior ChatResponse or SSE provider_session event.",
    )
    stream: bool = Field(
        default=True,
        description="When true (default), the response is delivered as Server-Sent Events. When false, a single JSON ChatResponse is returned after completion.",
    )
    provider_options: dict[str, Any] = Field(
        default_factory=dict,
        description="Provider-specific options passed through to the underlying CLI. Common key: 'extra_args' (list of additional CLI arguments).",
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
                {
                    "provider": "copilot",
                    "model": "claude-sonnet-4.6",
                    "workspace_path": "/home/user/project",
                    "mode": "new",
                    "prompt": "Add unit tests for the auth module.",
                    "stream": True,
                    "provider_options": {},
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


class ChatResponse(BaseModel):
    """Response returned for a non-streaming chat request, or the payload
    of the ``completed`` SSE event in streaming mode.
    """

    provider: ProviderName = Field(description="Provider that handled the request.")
    model: str = Field(description="Model that was used.")
    provider_session_ref: str | None = Field(description="Session reference that can be used to resume this conversation later.")
    final_text: str = Field(description="Complete accumulated output text from the AI provider.")
    exit_code: int = Field(description="CLI process exit code. 0 indicates success.")
    warnings: list[str] = Field(default_factory=list, description="Non-fatal warnings emitted during execution.")

    model_config = ConfigDict(
        json_schema_extra={
            "examples": [
                {
                    "provider": "claude",
                    "model": "sonnet",
                    "provider_session_ref": "a1b2c3d4-e5f6-7890-abcd-ef1234567890",
                    "final_text": "The main entry point is in `main.py`. It initializes the FastAPI application...",
                    "exit_code": 0,
                    "warnings": [],
                }
            ]
        }
    )


# ---------------------------------------------------------------------------
# Test Lab models
# ---------------------------------------------------------------------------

class TestVerifyItem(BaseModel):
    """A single model's test results to be verified against expected keywords."""

    provider: ProviderName = Field(description="Provider that was tested.")
    model: str = Field(description="Model that was tested.")
    new_exit_code: int = Field(description="Exit code from the NEW chat step. 0 indicates success.")
    resume_text: str = Field(description="Full response text from the RESUME chat step.")
    resume_exit_code: int = Field(description="Exit code from the RESUME chat step. 0 indicates success.")
    keywords: list[str] = Field(description="Keywords expected to appear in the resume response text.")


class TestVerifyRequest(BaseModel):
    """Request body for verifying test results across multiple models."""

    items: list[TestVerifyItem] = Field(description="List of per-model test results to verify.")

    model_config = ConfigDict(
        json_schema_extra={
            "examples": [
                {
                    "items": [
                        {
                            "provider": "claude",
                            "model": "sonnet",
                            "new_exit_code": 0,
                            "resume_text": "Your responsibilities include managing PF, ATM, and Transit systems.",
                            "resume_exit_code": 0,
                            "keywords": ["PF", "ATM", "Transit"],
                        }
                    ]
                }
            ]
        }
    )


class TestVerifyResultItem(BaseModel):
    """Verification result for a single model's test run."""

    provider: ProviderName = Field(description="Provider that was tested.")
    model: str = Field(description="Model that was tested.")
    new_status: str = Field(description="'OK' if new chat succeeded (exit code 0), otherwise 'FAIL'.")
    resume_status: str = Field(description="'OK' if resume chat succeeded (exit code 0), otherwise 'FAIL'.")
    keyword_results: dict[str, bool] = Field(description="Map of each keyword to whether it was found in the resume response (case-insensitive).")
    grade: str = Field(description="'PASS' if new and resume both OK and all keywords found, otherwise 'FAIL'.")

    model_config = ConfigDict(
        json_schema_extra={
            "examples": [
                {
                    "provider": "claude",
                    "model": "sonnet",
                    "new_status": "OK",
                    "resume_status": "OK",
                    "keyword_results": {"PF": True, "ATM": True, "Transit": True},
                    "grade": "PASS",
                }
            ]
        }
    )


class TestVerifyResponse(BaseModel):
    """Response containing verification results for all tested models."""

    results: list[TestVerifyResultItem] = Field(description="Per-model verification results.")


class TestGenerateRequest(BaseModel):
    """Request body for AI-generating test scenario content."""

    field: str = Field(
        description="Which field(s) to generate: 'story', 'questions', 'expected', or 'all' for all three.",
    )
    workspace_path: str = Field(
        min_length=1,
        description="Absolute path to the workspace directory (passed to the underlying CLI).",
    )

    model_config = ConfigDict(
        json_schema_extra={
            "examples": [
                {"field": "all", "workspace_path": "C:\\Github\\ai-cli-api"},
            ]
        }
    )


class TestQAPair(BaseModel):
    """A single question + expected keywords pair for the Test Lab."""

    question: str = Field(description="Follow-up question to send as a RESUME prompt.")
    expected: str = Field(description="Comma-separated keywords expected in the response.")


class TestGenerateResponse(BaseModel):
    """Response containing AI-generated test scenario content."""

    story: str | None = Field(default=None, description="Generated initial prompt (the 'story') for the NEW chat step.")
    questions: str | None = Field(default=None, description="Deprecated. Use qa_pairs instead.")
    expected: str | None = Field(default=None, description="Deprecated. Use qa_pairs instead.")
    qa_pairs: list[TestQAPair] = Field(default_factory=list, description="List of question/expected-keywords pairs for RESUME steps.")

    model_config = ConfigDict(
        json_schema_extra={
            "examples": [
                {
                    "story": "Hello my name is Alice and I am a backend engineer working on authentication and payments. I drive a red car.",
                    "qa_pairs": [
                        {"question": "What systems am I responsible for?", "expected": "authentication, payments"},
                        {"question": "What color is my car?", "expected": "red"},
                        {"question": "What is my role?", "expected": "backend engineer"},
                    ],
                }
            ]
        }
    )


# ---------------------------------------------------------------------------
# Provider / Worker / Health models
# ---------------------------------------------------------------------------

class ProviderCapability(BaseModel):
    """Capability metadata for a registered AI CLI provider."""

    provider: ProviderName = Field(description="Provider identifier.")
    executable: str | None = Field(description="Resolved path to the provider CLI executable, or null if not found.")
    enabled: bool = Field(description="Whether this provider is enabled in the configuration.")
    models: list[str] = Field(description="List of configured model identifiers for this provider.")
    supports_resume: bool = Field(description="Whether the provider supports resuming previous sessions.")
    supports_streaming: bool = Field(description="Whether the provider supports streaming output.")
    supports_model_override: bool = Field(description="Whether a custom model can be specified per request.")
    session_reference_format: str = Field(description="Format of the session reference (e.g. 'uuid').")

    model_config = ConfigDict(
        json_schema_extra={
            "examples": [
                {
                    "provider": "claude",
                    "executable": "/usr/local/bin/claude",
                    "enabled": True,
                    "models": ["opus", "sonnet", "haiku"],
                    "supports_resume": True,
                    "supports_streaming": True,
                    "supports_model_override": True,
                    "session_reference_format": "uuid",
                }
            ]
        }
    )


class ModelDetail(BaseModel):
    """Detailed information about a single available model, including how to call it."""

    provider: ProviderName = Field(description="Provider that serves this model.")
    model: str = Field(description="Model identifier to use in chat requests.")
    ready: bool = Field(description="Whether the warm worker for this model is ready to accept requests.")
    busy: bool = Field(description="Whether the worker is currently processing a request.")
    supports_resume: bool = Field(description="Whether this model supports session resume.")
    chat_request_example: dict[str, Any] = Field(
        description="Example POST /v1/chat request body for this model.",
    )

    model_config = ConfigDict(
        json_schema_extra={
            "examples": [
                {
                    "provider": "copilot",
                    "model": "claude-sonnet-4.6",
                    "ready": True,
                    "busy": False,
                    "supports_resume": True,
                    "chat_request_example": {
                        "provider": "copilot",
                        "model": "claude-sonnet-4.6",
                        "workspace_path": "/path/to/project",
                        "mode": "new",
                        "prompt": "Explain this codebase.",
                        "stream": True,
                    },
                }
            ]
        }
    )


class WorkerInfo(BaseModel):
    """Runtime status of a warm worker process."""

    provider: ProviderName = Field(description="Provider this worker serves.")
    model: str = Field(description="Model this worker is configured for.")
    shell_backend: str = Field(description="Path to the shell executable backing this worker.")
    ready: bool = Field(description="True if the worker shell has started and is accepting requests.")
    busy: bool = Field(description="True if the worker is currently processing a request.")
    queue_length: int = Field(description="Number of requests waiting in the worker's queue.")
    last_error: str | None = Field(default=None, description="Most recent error message, or null if healthy.")

    model_config = ConfigDict(
        json_schema_extra={
            "examples": [
                {
                    "provider": "claude",
                    "model": "sonnet",
                    "shell_backend": "/usr/bin/bash",
                    "ready": True,
                    "busy": False,
                    "queue_length": 0,
                    "last_error": None,
                }
            ]
        }
    )


class HealthResponse(BaseModel):
    """System health check result. Returns ``ok`` when all workers are
    healthy, or ``degraded`` when one or more workers report errors.
    """

    status: Literal["ok", "degraded"] = Field(description="Overall health status.")
    config_path: str = Field(description="Filesystem path to the loaded configuration file.")
    shell_path: str | None = Field(description="Resolved shell executable path, or null if auto-detection failed.")
    bash_version: str | None = Field(default=None, description="Git Bash / bash version string, or null if not yet detected.")
    workers_booted: bool = Field(description="True if all configured workers have started successfully.")
    worker_count: int = Field(description="Total number of configured workers.")
    details: list[str] = Field(default_factory=list, description="Error messages from unhealthy workers. Empty when status is 'ok'.")

    model_config = ConfigDict(
        json_schema_extra={
            "examples": [
                {
                    "status": "ok",
                    "config_path": "/home/user/ai-cli-api/config.toml",
                    "shell_path": "/usr/bin/bash",
                    "bash_version": "GNU bash, version 5.2.26(1)-release (x86_64-pc-msys)",
                    "workers_booted": True,
                    "worker_count": 7,
                    "details": [],
                }
            ]
        }
    )


# ---------------------------------------------------------------------------
# CLI version / update status
# ---------------------------------------------------------------------------

class CLIVersionStatus(BaseModel):
    """Version and update status for a CLI provider executable."""

    provider: ProviderName = Field(description="Provider this status applies to.")
    executable: str | None = Field(description="Resolved CLI executable path, or null if not found.")
    current_version: str | None = Field(description="Currently installed version, or null if detection failed.")
    latest_version: str | None = Field(description="Latest available version from the package registry, or null if lookup failed.")
    needs_update: bool = Field(description="True when the installed version is older than the latest available version.")
    last_checked: str | None = Field(default=None, description="ISO-8601 timestamp of the most recent version check.")
    next_check_at: str | None = Field(default=None, description="ISO-8601 timestamp of the next scheduled version check.")
    auto_update: bool = Field(default=True, description="Whether auto-update is enabled for this check cycle.")
    last_updated: str | None = Field(default=None, description="ISO-8601 timestamp of the most recent successful update, or null if never updated.")
    update_skipped_reason: str | None = Field(default=None, description="Reason the update was skipped (e.g. 'workers busy'), or null if not applicable.")

    model_config = ConfigDict(
        json_schema_extra={
            "examples": [
                {
                    "provider": "claude",
                    "executable": "claude",
                    "current_version": "1.0.16",
                    "latest_version": "1.0.17",
                    "needs_update": True,
                    "last_checked": "2026-03-21T12:00:00Z",
                    "next_check_at": "2026-03-21T16:00:00Z",
                    "auto_update": True,
                    "last_updated": None,
                    "update_skipped_reason": "workers busy",
                }
            ]
        }
    )


# ---------------------------------------------------------------------------
# Error model (for OpenAPI error response documentation)
# ---------------------------------------------------------------------------

class ErrorDetail(BaseModel):
    """Standard error response body returned by the API."""

    detail: str = Field(description="Human-readable error message.")


# ---------------------------------------------------------------------------
# SSE event models (documentation-only, for OpenAPI schema generation)
# ---------------------------------------------------------------------------

class SSERunStarted(BaseModel):
    """SSE event emitted when the CLI process is launched."""

    provider: ProviderName = Field(description="Provider handling the request.")
    model: str = Field(description="Model being used.")

    model_config = ConfigDict(
        json_schema_extra={
            "examples": [{"provider": "claude", "model": "sonnet"}]
        }
    )


class SSEProviderSession(BaseModel):
    """SSE event emitted when a session reference is assigned or known."""

    provider_session_ref: str = Field(description="Session reference for resuming this conversation later.")

    model_config = ConfigDict(
        json_schema_extra={
            "examples": [{"provider_session_ref": "a1b2c3d4-e5f6-7890-abcd-ef1234567890"}]
        }
    )


class SSEOutputDelta(BaseModel):
    """SSE event emitted for each incremental chunk of output text."""

    text: str = Field(description="Incremental output text from the AI provider.")

    model_config = ConfigDict(
        json_schema_extra={
            "examples": [{"text": "Here is the refactored function:\n```python\n"}]
        }
    )


class SSECompleted(BaseModel):
    """SSE event emitted when the CLI process finishes successfully."""

    provider: ProviderName = Field(description="Provider that handled the request.")
    model: str = Field(description="Model that was used.")
    provider_session_ref: str | None = Field(description="Session reference for resuming later.")
    final_text: str = Field(description="Complete accumulated output text.")
    exit_code: int = Field(description="CLI exit code (0 = success).")
    warnings: list[str] = Field(default_factory=list, description="Non-fatal warnings.")


class SSEFailed(BaseModel):
    """SSE event emitted when the CLI process exits with an error."""

    provider: ProviderName = Field(description="Provider that handled the request.")
    model: str = Field(description="Model that was used.")
    provider_session_ref: str | None = Field(description="Session reference, if one was assigned.")
    exit_code: int = Field(description="CLI exit code (non-zero).")
    warnings: list[str] = Field(default_factory=list, description="Non-fatal warnings.")
    error: str = Field(description="Human-readable error message describing the failure.")
