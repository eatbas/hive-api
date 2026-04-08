from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

from symphony.discovery.discoverer import discover_provider
from symphony.models import InstrumentName


SAMPLE_CONFIG = """\
[server]
host = "127.0.0.1"
port = 8000

[providers.claude]
enabled = true
models = ["opus", "haiku"]

[providers.gemini]
enabled = true
models = ["gemini-3-flash-preview"]
"""


class TestDiscoverProvider:
    def test_updates_config_when_models_change(self, tmp_path: Path) -> None:
        config = tmp_path / "config.toml"
        config.write_text(SAMPLE_CONFIG, encoding="utf-8")

        with patch(
            "symphony.discovery.discoverer.DISCOVERERS",
            {InstrumentName.CLAUDE: lambda: ["haiku", "opus", "sonnet"]},
        ):
            changed = discover_provider(InstrumentName.CLAUDE, config)

        assert changed is True
        text = config.read_text(encoding="utf-8")
        assert '"sonnet"' in text
        # Gemini section must be untouched.
        assert '"gemini-3-flash-preview"' in text

    def test_returns_false_when_models_unchanged(self, tmp_path: Path) -> None:
        config = tmp_path / "config.toml"
        config.write_text(SAMPLE_CONFIG, encoding="utf-8")

        with patch(
            "symphony.discovery.discoverer.DISCOVERERS",
            {InstrumentName.CLAUDE: lambda: ["opus", "haiku"]},
        ):
            changed = discover_provider(InstrumentName.CLAUDE, config)

        assert changed is False

    def test_returns_false_when_discovery_returns_none(self, tmp_path: Path) -> None:
        config = tmp_path / "config.toml"
        config.write_text(SAMPLE_CONFIG, encoding="utf-8")

        with patch(
            "symphony.discovery.discoverer.DISCOVERERS",
            {InstrumentName.CLAUDE: lambda: None},
        ):
            changed = discover_provider(InstrumentName.CLAUDE, config)

        assert changed is False
        assert config.read_text(encoding="utf-8") == SAMPLE_CONFIG

    def test_returns_false_for_unknown_provider(self, tmp_path: Path) -> None:
        config = tmp_path / "config.toml"
        config.write_text(SAMPLE_CONFIG, encoding="utf-8")

        with patch("symphony.discovery.discoverer.DISCOVERERS", {}):
            changed = discover_provider(InstrumentName.CLAUDE, config)

        assert changed is False

    def test_returns_false_when_discovery_raises(self, tmp_path: Path) -> None:
        config = tmp_path / "config.toml"
        config.write_text(SAMPLE_CONFIG, encoding="utf-8")

        def _explode() -> list[str]:
            raise RuntimeError("boom")

        with patch(
            "symphony.discovery.discoverer.DISCOVERERS",
            {InstrumentName.CLAUDE: _explode},
        ):
            changed = discover_provider(InstrumentName.CLAUDE, config)

        assert changed is False
        assert config.read_text(encoding="utf-8") == SAMPLE_CONFIG
