from symphony.config import load_config
from symphony.models import InstrumentName


def test_load_config_expands_provider_models(config_path):
    config = load_config(config_path)
    assert config.providers[InstrumentName.GEMINI].models == ["gemini-3-flash-preview"]
    assert config.providers[InstrumentName.CODEX].enabled is True
    assert config.providers[InstrumentName.CODEX].models == ["codex-5.3", "gpt-5.4-mini"]
