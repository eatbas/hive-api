from __future__ import annotations

from enum import StrEnum


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
