# AI CLI API

Local FastAPI wrapper around warm `bash` workers for `gemini`, `codex`, `claude`, and `kimi`.

## What it does

- starts one warm background bash worker per configured `provider + model`
- accepts API calls over HTTP
- runs the matching CLI inside the already-open bash worker
- streams output back over Server-Sent Events or returns JSON
- keeps no persistent conversation state in the bridge

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

## Config

`config.toml` prewarms workers for the configured provider-model pairs.

- `models = ["default"]` means route requests under the label `default` and omit the provider `--model` flag.
- Any other model string is passed through to the provider CLI unchanged, except for provider-specific legacy aliases such as Codex `codex-5.3`, which is normalized to `gpt-5.3-codex`.
- `default_options.extra_args` is an allowlisted escape hatch for provider-specific flags.

## API

### `GET /health`
Returns health, shell availability, and worker boot state.

### `GET /v1/providers`
Returns provider capabilities and executable discovery results.

### `GET /v1/workers`
Returns the warm worker inventory, status, and queue depth.

### `POST /v1/chat`
Example JSON body:

```json
{
  "provider": "claude",
  "model": "default",
  "workspace_path": "C:\\Github\\ai-cli-api",
  "mode": "new",
  "prompt": "say hello in one word",
  "stream": true
}
```

Resume example:

```json
{
  "provider": "gemini",
  "model": "default",
  "workspace_path": "C:\\Github\\ai-cli-api",
  "mode": "resume",
  "prompt": "say hi in one word",
  "provider_session_ref": "e3c7d445-d2f3-4e61-931f-62d7182902e6",
  "stream": false
}
```
