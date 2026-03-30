from symphony.models import ChatMode
from symphony.providers.base import ParseState
from symphony.providers.copilot import CopilotAdapter


def test_copilot_new_command_includes_required_flags():
    adapter = CopilotAdapter()
    command = adapter.build_command(
        executable="copilot",
        mode=ChatMode.NEW,
        prompt="hello",
        model="default",
        session_ref=None,
        provider_options={},
    )
    assert "-p" in command.argv
    assert "--output-format" in command.argv
    assert "json" in command.argv
    assert "--allow-all-tools" in command.argv
    assert "--no-ask-user" in command.argv
    assert "--no-auto-update" in command.argv


def test_copilot_new_command_includes_model_when_not_default():
    adapter = CopilotAdapter()
    command = adapter.build_command(
        executable="copilot",
        mode=ChatMode.NEW,
        prompt="hello",
        model="claude-opus-4.6",
        session_ref=None,
        provider_options={},
    )
    assert "--model" in command.argv
    assert "claude-opus-4.6" in command.argv


def test_copilot_new_command_omits_model_for_default():
    adapter = CopilotAdapter()
    command = adapter.build_command(
        executable="copilot",
        mode=ChatMode.NEW,
        prompt="hello",
        model="default",
        session_ref=None,
        provider_options={},
    )
    assert "--model" not in command.argv


def test_copilot_resume_command_uses_resume_flag():
    adapter = CopilotAdapter()
    command = adapter.build_command(
        executable="copilot",
        mode=ChatMode.RESUME,
        prompt="hello",
        model="default",
        session_ref="abc-def-123",
        provider_options={},
    )
    assert "--resume" in command.argv
    assert "abc-def-123" in command.argv
    assert command.preset_session_ref == "abc-def-123"


def test_copilot_extra_args_appended():
    adapter = CopilotAdapter()
    command = adapter.build_command(
        executable="copilot",
        mode=ChatMode.NEW,
        prompt="hello",
        model="default",
        session_ref=None,
        provider_options={"extra_args": ["--autopilot"]},
    )
    assert "--autopilot" in command.argv


def test_copilot_parse_extracts_session_id():
    adapter = CopilotAdapter()
    state = ParseState()
    events = adapter.parse_output_line('{"type":"result","sessionId":"cop-sess-789","exitCode":0}', state)
    assert state.session_ref == "cop-sess-789"
    assert any(e["type"] == "provider_session" for e in events)


def test_copilot_parse_extracts_assistant_text():
    adapter = CopilotAdapter()
    state = ParseState()
    events = adapter.parse_output_line('{"type":"assistant.message","data":{"content":"hello world","messageId":"m1"}}', state)
    assert any(e["type"] == "output_delta" for e in events)
    assert "hello world" in state.output_chunks


def test_copilot_parse_detects_error_result():
    adapter = CopilotAdapter()
    state = ParseState()
    adapter.parse_output_line('{"type":"result","sessionId":"s1","exitCode":1}', state)
    assert state.error_message is not None


def test_copilot_non_json_added_to_warnings():
    adapter = CopilotAdapter()
    state = ParseState()
    events = adapter.parse_output_line("not json at all", state)
    assert len(state.warnings) == 1
    assert events == []


def test_copilot_shell_script_includes_add_dir():
    adapter = CopilotAdapter()
    command = adapter.build_command(
        executable="copilot",
        mode=ChatMode.NEW,
        prompt="hello",
        model="default",
        session_ref=None,
        provider_options={},
    )
    script = adapter.make_shell_script("/workspace/project", command)
    assert "--add-dir" in script
    assert "/workspace/project" in script
