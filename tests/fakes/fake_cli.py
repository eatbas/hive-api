import os
import sys
from pathlib import Path

provider = sys.argv[1]
args = sys.argv[2:]


def read_flag(flag: str):
    if flag in args:
        index = args.index(flag)
        return args[index + 1]
    return None


def has_flag(flag: str) -> bool:
    return flag in args


def last_non_flag(arguments):
    value = None
    skip_next = False
    flags_with_values = {
        "-p", "--prompt", "-m", "--model", "--resume", "--session-id", "--session",
        "--output-format", "--permission-mode", "-o",
    }
    for arg in arguments:
        if skip_next:
            skip_next = False
            continue
        if arg in flags_with_values:
            skip_next = True
            continue
        if arg.startswith("-"):
            continue
        value = arg
    return value or ""


def emit(line: str):
    sys.stdout.write(line + "\n")
    sys.stdout.flush()


# Gemini and kimi pass the prompt via a flag; claude and codex use a positional arg.
if provider in ("gemini",):
    prompt = read_flag("-p") or last_non_flag(args)
elif provider in ("kimi",):
    prompt = read_flag("--prompt") or last_non_flag(args)
else:
    prompt = last_non_flag(args)

model = read_flag("-m") or read_flag("--model") or "default"
if provider == "gemini":
    if has_flag("--list-sessions"):
        emit("Available sessions for this project (2):")
        emit("  1. first session (1 hour ago) [gemini-session-new]")
        emit("  2. second session (2 hours ago) [gemini-session-old]")
        sys.exit(0)
    resume_index = read_flag("--resume")
    if resume_index:
        index_to_uuid = {"1": "gemini-session-new", "2": "gemini-session-old"}
        session_id = index_to_uuid.get(resume_index, f"gemini-resumed-{resume_index}")
    else:
        session_id = "gemini-session-new"
    emit(f'{{"type":"init","session_id":"{session_id}","model":"{model}"}}')
    emit(f'{{"type":"message","role":"assistant","content":"gemini:{prompt}","delta":true}}')
    emit('{"type":"result","status":"success"}')
elif provider == "claude":
    session_id = read_flag("--resume") or read_flag("--session-id") or "claude-session-new"
    emit(f'{{"type":"system","subtype":"init","session_id":"{session_id}","model":"{model}"}}')
    emit(
        '{"type":"assistant","message":{"content":[{"type":"text","text":"claude:'
        + prompt.replace('"', '\\"')
        + '"}]},"session_id":"'
        + session_id
        + '"}'
    )
    emit(f'{{"type":"result","subtype":"success","session_id":"{session_id}","result":"claude:{prompt}"}}')
elif provider == "kimi":
    session_id = read_flag("--session") or "kimi-session-new"
    emit('{"role":"assistant","content":[{"type":"text","text":"kimi:' + prompt.replace('"', '\\"') + '"}]}')
elif provider == "codex":
    if len(args) >= 2 and args[0] == "exec" and args[1] == "resume":
        non_flags = [arg for arg in args[2:] if not arg.startswith("-")]
        thread_id = non_flags[0]
        prompt = non_flags[-1]
    else:
        thread_id = "codex-thread-new"
    emit(f'{{"type":"thread.started","thread_id":"{thread_id}"}}')
    emit('{"type":"item.completed","item":{"type":"agent_message","text":"codex:' + prompt.replace('"', '\\"') + '"}}')
    emit('{"type":"turn.completed","usage":{"output_tokens":1}}')
else:
    emit('{"error":"unknown provider"}')
    sys.exit(1)

if "fail" in prompt:
    sys.exit(3)
