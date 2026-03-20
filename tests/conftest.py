from __future__ import annotations

import os
from pathlib import Path

import pytest

from ai_cli_api.config import load_config
from ai_cli_api.models import ProviderName


def make_wrapper(tmp_path: Path, provider: str) -> str:
    wrapper = tmp_path / f"{provider}.sh"
    fake_cli = Path(__file__).parent / "fakes" / "fake_cli.py"
    wrapper.write_text(
        "#!/usr/bin/env bash\n"
        f'python "{fake_cli.as_posix()}" {provider} "$@"\n',
        encoding="utf-8",
    )
    os.chmod(wrapper, 0o755)
    return str(wrapper)


def make_config(tmp_path: Path) -> Path:
    providers = {provider.value: make_wrapper(tmp_path, provider.value) for provider in ProviderName}
    config_path = tmp_path / "config.toml"
    config_path.write_text(
        f"""
[server]
host = "127.0.0.1"
port = 8000

[shell]
path = ""

[providers.gemini]
enabled = true
executable = "{providers['gemini'].replace('\\', '\\\\')}"
models = ["gemini-2.5-flash", "gemini-2.5-pro"]
default_options = {{ extra_args = [] }}

[providers.codex]
enabled = true
executable = "{providers['codex'].replace('\\', '\\\\')}"
models = ["codex-5.3", "gpt-5.4-mini"]
default_options = {{ extra_args = [] }}

[providers.claude]
enabled = true
executable = "{providers['claude'].replace('\\', '\\\\')}"
models = ["sonnet", "opus"]
default_options = {{ extra_args = [] }}

[providers.kimi]
enabled = true
executable = "{providers['kimi'].replace('\\', '\\\\')}"
models = ["default"]
default_options = {{ extra_args = [] }}
""".strip(),
        encoding="utf-8",
    )
    return config_path


@pytest.fixture()
def config_path(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    path = make_config(tmp_path)
    monkeypatch.setenv("AI_CLI_API_CONFIG", str(path))
    return path


@pytest.fixture()
def loaded_config(config_path: Path):
    return load_config(config_path)
