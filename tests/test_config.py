from ai_cli_api.config import load_config
from ai_cli_api.models import ProviderName


def test_load_config_expands_provider_models(config_path):
    config = load_config(config_path)
    assert config.providers[ProviderName.GEMINI].models == ["gemini-2.5-flash", "gemini-2.5-pro"]
    assert config.providers[ProviderName.CODEX].enabled is True
    assert config.providers[ProviderName.CODEX].models == ["codex-5.3", "gpt-5.4-mini"]
