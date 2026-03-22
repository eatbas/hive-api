from ai_cli_api.models import ChatMode
from ai_cli_api.providers.base import ParseState
from ai_cli_api.providers.kimi import KimiAdapter


def test_kimi_new_command_assigns_session():
    adapter = KimiAdapter()
    command = adapter.build_command(
        executable="kimi",
        mode=ChatMode.NEW,
        prompt="hello",
        model="default",
        session_ref=None,
        provider_options={},
    )
    assert "--session" in command.argv
    assert "--print" in command.argv
    assert "--output-format" in command.argv
    assert command.preset_session_ref


def test_kimi_new_command_includes_model_when_not_default():
    adapter = KimiAdapter()
    command = adapter.build_command(
        executable="kimi",
        mode=ChatMode.NEW,
        prompt="hello",
        model="k2",
        session_ref=None,
        provider_options={},
    )
    assert "--model" in command.argv
    assert "k2" in command.argv


def test_kimi_resume_command_uses_session_flag():
    adapter = KimiAdapter()
    command = adapter.build_command(
        executable="kimi",
        mode=ChatMode.RESUME,
        prompt="hello",
        model="default",
        session_ref="kimi-sess-1",
        provider_options={},
    )
    assert "--session" in command.argv
    assert "kimi-sess-1" in command.argv


def test_kimi_parse_emits_output_delta():
    adapter = KimiAdapter()
    state = ParseState()
    events = adapter.parse_output_line('{"role":"assistant","content":[{"type":"text","text":"hello world"}]}', state)
    assert any(e["type"] == "output_delta" for e in events)
    assert "hello world" in state.output_chunks
