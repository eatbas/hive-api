import pytest

from ai_cli_api.models import ChatMode
from ai_cli_api.providers.base import ParseState
from ai_cli_api.providers.claude import ClaudeAdapter
from ai_cli_api.providers.codex import CodexAdapter
from ai_cli_api.providers.gemini import GeminiAdapter
from ai_cli_api.providers.kimi import KimiAdapter


# ---------------------------------------------------------------------------
# Command generation: new
# ---------------------------------------------------------------------------

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


def test_codex_new_command_includes_full_auto():
    adapter = CodexAdapter()
    command = adapter.build_command(
        executable="codex",
        mode=ChatMode.NEW,
        prompt="hello",
        model="default",
        session_ref=None,
        provider_options={},
    )
    assert "--full-auto" in command.argv
    assert "--json" in command.argv


def test_codex_new_command_includes_model_when_not_default():
    adapter = CodexAdapter()
    command = adapter.build_command(
        executable="codex",
        mode=ChatMode.NEW,
        prompt="hello",
        model="o3",
        session_ref=None,
        provider_options={},
    )
    assert "-m" in command.argv
    assert "o3" in command.argv


def test_codex_new_command_maps_legacy_model_alias():
    adapter = CodexAdapter()
    command = adapter.build_command(
        executable="codex",
        mode=ChatMode.NEW,
        prompt="hello",
        model="codex-5.3",
        session_ref=None,
        provider_options={},
    )
    assert "-m" in command.argv
    assert "codex-5.3" not in command.argv
    assert "gpt-5.3-codex" in command.argv


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


# ---------------------------------------------------------------------------
# Command generation: resume
# ---------------------------------------------------------------------------

def test_codex_resume_command_uses_json_and_full_auto():
    adapter = CodexAdapter()
    command = adapter.build_command(
        executable="codex",
        mode=ChatMode.RESUME,
        prompt="hello",
        model="default",
        session_ref="thread-1",
        provider_options={},
    )
    assert command.argv[:4] == ["codex", "exec", "resume", "--json"]
    assert "--full-auto" in command.argv


def test_codex_resume_command_maps_legacy_model_alias():
    adapter = CodexAdapter()
    command = adapter.build_command(
        executable="codex",
        mode=ChatMode.RESUME,
        prompt="hello",
        model="codex-5.3",
        session_ref="thread-1",
        provider_options={},
    )
    assert "-m" in command.argv
    assert "codex-5.3" not in command.argv
    assert "gpt-5.3-codex" in command.argv


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


# ---------------------------------------------------------------------------
# Output parsing: session reference extraction
# ---------------------------------------------------------------------------

def test_gemini_parse_extracts_session_id():
    adapter = GeminiAdapter()
    state = ParseState()
    events = adapter.parse_output_line('{"type":"init","session_id":"uuid-123","model":"flash"}', state)
    assert state.session_ref == "uuid-123"
    assert any(e["type"] == "provider_session" for e in events)


def test_claude_parse_extracts_session_id():
    adapter = ClaudeAdapter()
    state = ParseState()
    events = adapter.parse_output_line('{"type":"system","subtype":"init","session_id":"sess-456"}', state)
    assert state.session_ref == "sess-456"
    assert any(e["type"] == "provider_session" for e in events)


def test_codex_parse_extracts_thread_id():
    adapter = CodexAdapter()
    state = ParseState()
    events = adapter.parse_output_line('{"type":"thread.started","thread_id":"t-789"}', state)
    assert state.session_ref == "t-789"
    assert any(e["type"] == "provider_session" for e in events)


def test_kimi_parse_emits_output_delta():
    adapter = KimiAdapter()
    state = ParseState()
    events = adapter.parse_output_line('{"role":"assistant","content":[{"type":"text","text":"hello world"}]}', state)
    assert any(e["type"] == "output_delta" for e in events)
    assert "hello world" in state.output_chunks


# ---------------------------------------------------------------------------
# Output parsing: error handling
# ---------------------------------------------------------------------------

def test_claude_parse_detects_error_result():
    adapter = ClaudeAdapter()
    state = ParseState()
    adapter.parse_output_line('{"type":"result","subtype":"error","result":"something went wrong"}', state)
    assert state.error_message is not None


def test_gemini_parse_detects_error_result():
    adapter = GeminiAdapter()
    state = ParseState()
    adapter.parse_output_line('{"type":"result","status":"error"}', state)
    assert state.error_message is not None


def test_codex_parse_captures_error_item_as_warning():
    adapter = CodexAdapter()
    state = ParseState()
    adapter.parse_output_line('{"type":"item.completed","item":{"type":"error","message":"oops"}}', state)
    assert len(state.warnings) == 1
    assert "oops" in state.warnings[0]


def test_non_json_line_added_to_warnings():
    adapter = GeminiAdapter()
    state = ParseState()
    events = adapter.parse_output_line("this is not json", state)
    assert len(state.warnings) == 1
    assert events == []


# ---------------------------------------------------------------------------
# Extra args pass-through
# ---------------------------------------------------------------------------

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
