from ai_cli_api.models import ChatMode
from ai_cli_api.providers.base import ParseState
from ai_cli_api.providers.claude import ClaudeAdapter


def test_claude_new_command_assigns_session_id():
    adapter = ClaudeAdapter()
    command = adapter.build_command(
        executable="claude",
        mode=ChatMode.NEW,
        prompt="hello",
        model="opus",
        session_ref=None,
        provider_options={},
    )
    assert "--session-id" in command.argv
    assert "--model" in command.argv
    assert command.preset_session_ref


def test_claude_new_command_omits_model_for_default():
    adapter = ClaudeAdapter()
    command = adapter.build_command(
        executable="claude",
        mode=ChatMode.NEW,
        prompt="hello",
        model="default",
        session_ref=None,
        provider_options={},
    )
    assert "--model" not in command.argv


def test_claude_resume_command_uses_resume_flag():
    adapter = ClaudeAdapter()
    command = adapter.build_command(
        executable="claude",
        mode=ChatMode.RESUME,
        prompt="hello",
        model="default",
        session_ref="abc-123",
        provider_options={},
    )
    assert "--resume" in command.argv
    assert "abc-123" in command.argv
    assert "--session-id" not in command.argv


def test_claude_parse_extracts_session_id():
    adapter = ClaudeAdapter()
    state = ParseState()
    events = adapter.parse_output_line('{"type":"system","subtype":"init","session_id":"sess-456"}', state)
    assert state.session_ref == "sess-456"
    assert any(e["type"] == "provider_session" for e in events)


def test_claude_parse_detects_error_result():
    adapter = ClaudeAdapter()
    state = ParseState()
    adapter.parse_output_line('{"type":"result","subtype":"error","result":"something went wrong"}', state)
    assert state.error_message is not None
