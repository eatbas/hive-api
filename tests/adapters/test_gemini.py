import pytest

from symphony.models import ChatMode
from symphony.providers.base import ParseState
from symphony.providers.gemini import GeminiAdapter


def test_gemini_command_omits_model_for_default():
    adapter = GeminiAdapter()
    command = adapter.build_command(
        executable="gemini",
        mode=ChatMode.NEW,
        prompt="hello",
        model="default",
        session_ref=None,
        provider_options={},
    )
    assert "-m" not in command.argv


def test_gemini_new_command_includes_model_when_not_default():
    adapter = GeminiAdapter()
    command = adapter.build_command(
        executable="gemini",
        mode=ChatMode.NEW,
        prompt="hello",
        model="flash",
        session_ref=None,
        provider_options={},
    )
    assert "-m" in command.argv
    assert "flash" in command.argv


def test_gemini_resume_uses_placeholder_for_index_lookup():
    adapter = GeminiAdapter()
    command = adapter.build_command(
        executable="gemini",
        mode=ChatMode.RESUME,
        prompt="hello",
        model="default",
        session_ref="some-uuid",
        provider_options={},
    )
    assert "__GEMINI_IDX__" in command.argv
    assert command.preset_session_ref == "some-uuid"


def test_gemini_resume_shell_script_includes_list_sessions_lookup():
    adapter = GeminiAdapter()
    command = adapter.build_command(
        executable="gemini",
        mode=ChatMode.RESUME,
        prompt="hello",
        model="default",
        session_ref="abc-uuid",
        provider_options={},
    )
    script = adapter.make_shell_script("/workspace", command)
    assert "--list-sessions" in script
    assert "abc-uuid" in script
    assert "__gemini_idx" in script


def test_gemini_parse_extracts_session_id():
    adapter = GeminiAdapter()
    state = ParseState()
    events = adapter.parse_output_line('{"type":"init","session_id":"uuid-123","model":"flash"}', state)
    assert state.session_ref == "uuid-123"
    assert any(e["type"] == "provider_session" for e in events)


def test_gemini_parse_detects_error_result():
    adapter = GeminiAdapter()
    state = ParseState()
    adapter.parse_output_line('{"type":"result","status":"error"}', state)
    assert state.error_message is not None


def test_non_json_line_added_to_warnings():
    adapter = GeminiAdapter()
    state = ParseState()
    events = adapter.parse_output_line("this is not json", state)
    assert len(state.warnings) == 1
    assert events == []


def test_extra_args_appended_to_command():
    adapter = GeminiAdapter()
    command = adapter.build_command(
        executable="gemini",
        mode=ChatMode.NEW,
        prompt="hello",
        model="default",
        session_ref=None,
        provider_options={"extra_args": ["--yolo"]},
    )
    assert "--yolo" in command.argv


def test_extra_args_rejects_non_list():
    adapter = GeminiAdapter()
    with pytest.raises(ValueError, match="extra_args must be a list"):
        adapter.build_command(
            executable="gemini",
            mode=ChatMode.NEW,
            prompt="hello",
            model="default",
            session_ref=None,
            provider_options={"extra_args": "--bad"},
        )
