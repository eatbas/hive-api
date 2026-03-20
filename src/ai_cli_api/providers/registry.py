from __future__ import annotations

from .base import ProviderAdapter
from .claude import ClaudeAdapter
from .codex import CodexAdapter
from .gemini import GeminiAdapter
from .kimi import KimiAdapter
from ..models import ProviderName


def build_provider_registry() -> dict[ProviderName, ProviderAdapter]:
    adapters: list[ProviderAdapter] = [
        GeminiAdapter(),
        CodexAdapter(),
        ClaudeAdapter(),
        KimiAdapter(),
    ]
    return {adapter.name: adapter for adapter in adapters}
