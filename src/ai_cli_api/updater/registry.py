from __future__ import annotations

import re
from dataclasses import dataclass

from ..models import ProviderName

_VERSION_RE = re.compile(r"(\d+\.\d+\.\d+)")


@dataclass(slots=True)
class CLIPackageInfo:
    provider: ProviderName
    manager: str
    package: str


PACKAGE_REGISTRY: dict[str, CLIPackageInfo] = {
    "claude": CLIPackageInfo(ProviderName.CLAUDE, "npm", "@anthropic-ai/claude-code"),
    "codex": CLIPackageInfo(ProviderName.CODEX, "npm", "@openai/codex"),
    "gemini": CLIPackageInfo(ProviderName.GEMINI, "npm", "@google/gemini-cli"),
    "kimi": CLIPackageInfo(ProviderName.KIMI, "uv", "kimi-cli"),
    "copilot": CLIPackageInfo(ProviderName.COPILOT, "npm", "@github/copilot"),
    "opencode": CLIPackageInfo(ProviderName.OPENCODE, "npm", "opencode-ai"),
}


def _parse_version(text: str) -> str | None:
    match = _VERSION_RE.search(text)
    return match.group(1) if match else None


def _version_tuple(version: str) -> tuple[int, ...]:
    return tuple(int(part) for part in version.split("."))


def needs_update(current: str | None, latest: str | None) -> bool:
    """Return True when *current* is older than *latest* (semver comparison)."""
    if not current or not latest:
        return False
    try:
        return _version_tuple(current) < _version_tuple(latest)
    except (ValueError, TypeError):
        return current != latest
