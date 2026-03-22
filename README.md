# AI CLI API

Local FastAPI wrapper around warm `bash` workers for **Gemini**, **Codex**, **Claude**, **Kimi**, **Copilot**, and **OpenCode**.

## What it does

- Starts one warm background bash worker per configured `provider + model`
- Accepts API calls over HTTP
- Runs the matching CLI inside the already-open bash worker
- Streams output back over Server-Sent Events or returns JSON
- Keeps no persistent conversation state in the bridge
- Periodically checks for CLI updates and can auto-update idle workers

The caller must send `provider`, `model`, `workspace_path`, and when resuming, the provider-native session reference.

## Quick start

```bash
python -m venv .venv
. .venv/Scripts/activate
pip install -e .[dev]
uvicorn ai_cli_api.main:app --reload
```

Default config is loaded from `config.toml`. Override with `AI_CLI_API_CONFIG=/path/to/config.toml`.

Open [http://127.0.0.1:8000/](http://127.0.0.1:8000/) to use the built-in web test console.

Interactive API docs are available at `/docs` (Swagger) and `/redoc` (ReDoc).

## Providers

| Provider     | CLI executable | Default models                           | Resume |
| ------------ | -------------- | ---------------------------------------- | ------ |
| **Gemini**   | `gemini`       | `gemini-3.1-pro-preview`, `gemini-3-flash-preview` | Yes |
| **Codex**    | `codex`        | `codex-5.3`, `gpt-5.4`, `gpt-5.4-mini`  | Yes    |
| **Claude**   | `claude`       | `opus`, `sonnet`, `haiku`                | Yes    |
| **Kimi**     | `kimi`         | `kimi-code/kimi-for-coding`              | Yes    |
| **Copilot**  | `copilot`      | `claude-sonnet-4.6`, `claude-haiku-4.5`, `claude-opus-4.6`, `gemini-3.1-pro-preview`, `gemini-3-flash-preview`, `gpt-5.4`, `gpt-5.3-codex`, `gpt-5.4-mini` | Yes |
| **OpenCode** | `opencode`     | `glm-5`, `glm-5-turbo`, `glm-4.7`       | Yes    |

## Config

`config.toml` prewarms workers for the configured provider-model pairs.

```toml
[server]
host = "127.0.0.1"
port = 8000

[shell]
path = ""  # Auto-detect on Windows

[providers.claude]
enabled = true
executable = ""            # auto-detect from PATH
models = ["opus", "sonnet", "haiku"]
default_options = { extra_args = [] }

[updater]
enabled = true
interval_hours = 4
auto_update = true
```

- `models` — Each string becomes a warm worker. The value is passed to the provider CLI `--model` flag.
- `executable` — Leave empty to auto-detect from PATH, or set an absolute path.
- `default_options.extra_args` — Allowlisted escape hatch for provider-specific flags.
- `updater` — Controls automatic CLI version checking and updates.

## API

### Health & System

#### `GET /health`
Returns health status, shell availability, and worker boot state.

#### `POST /v1/cli-versions/check`
Triggers a version check for all provider CLIs. Returns current and latest versions for each.

#### `GET /v1/cli-versions`
Returns cached CLI version statuses (current version, latest version, update availability).

#### `POST /v1/cli-versions/{provider}/update`
Force-updates a single provider CLI. The provider's workers are restarted after the update completes.

### Providers & Models

#### `GET /v1/providers`
Returns provider capabilities and executable discovery results.

#### `GET /v1/models`
Returns all available models across all providers with per-model status and chat examples.

#### `GET /v1/workers`
Returns the warm worker inventory, status, and queue depth.

### Chat

#### `POST /v1/chat`
Sends a prompt to a provider. Supports streaming (SSE) and JSON response modes.

**New chat:**
```json
{
  "provider": "claude",
  "model": "sonnet",
  "workspace_path": "C:\\Github\\ai-cli-api",
  "mode": "new",
  "prompt": "say hello in one word",
  "stream": true
}
```

**Resume chat:**
```json
{
  "provider": "gemini",
  "model": "gemini-3.1-pro-preview",
  "workspace_path": "C:\\Github\\ai-cli-api",
  "mode": "resume",
  "prompt": "say hi in one word",
  "provider_session_ref": "e3c7d445-d2f3-4e61-931f-62d7182902e6",
  "stream": false
}
```

**SSE events** (when `stream: true`):

| Event               | Description                          |
| ------------------- | ------------------------------------ |
| `run_started`       | Worker picked up the job             |
| `provider_session`  | Session ID from the provider CLI     |
| `output_delta`      | Incremental text chunk               |
| `completed`         | Final text and exit code             |
| `failed`            | Error message and exit code          |

### Test Lab

#### `POST /v1/test/verify`

Verifies test results across multiple models using keyword matching. A model receives **PASS** when: NEW chat exited 0, RESUME chat exited 0, and every keyword is found in the resume response (case-insensitive).

```json
{
  "items": [
    {
      "provider": "claude",
      "model": "sonnet",
      "new_exit_code": 0,
      "resume_text": "Your responsibilities include managing PF, ATM, and Transit.",
      "resume_exit_code": 0,
      "keywords": ["PF", "ATM", "Transit"]
    }
  ]
}
```

#### `POST /v1/test/generate-scenario`

Uses the cheapest available model (Claude Haiku or GPT-5.4-mini) to AI-generate test scenario content. Set `field` to `"story"`, `"questions"`, `"expected"`, or `"all"`.

```json
{
  "field": "all",
  "workspace_path": "C:\\Github\\ai-cli-api"
}
```

## Test Lab (Web Console)

The web console includes a **Test Lab** section that runs automated 2-step tests across all configured models in parallel:

1. **NEW** — Sends a "story" prompt to each selected model as a new chat session
2. **RESUME** — Sends a follow-up question to each model, resuming the session from step 1
3. **VERIFY** — Checks the resume response for expected keywords and grades each model PASS/FAIL

Features:
- Run all models in parallel with one click
- Magic buttons to AI-generate test scenarios
- Real-time results table with progressive status updates
- Keyword-based verification (case-insensitive)

## Adding a new provider

1. Create `src/ai_cli_api/providers/<name>.py` — subclass `ProviderAdapter`
2. Add `<NAME>` to the `ProviderName` enum in `models.py`
3. Register the adapter in `providers/registry.py`
4. Add a `[providers.<name>]` section to `config.toml`
5. Add the CLI package mapping in `updater.py` `PACKAGE_REGISTRY`
6. Add a fake CLI branch in `tests/fakes/fake_cli.py`
7. Add a config section in `tests/conftest.py`
8. Add a test in `tests/test_api.py`
9. Update `README.md` provider table
