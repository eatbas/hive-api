import json
import re
from contextlib import asynccontextmanager
from pathlib import Path
from typing import AsyncIterator

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, JSONResponse, StreamingResponse

from .config import load_config
from .models import (
    ChatMode,
    ChatRequest,
    ChatResponse,
    CLIVersionStatus,
    ErrorDetail,
    HealthResponse,
    ModelDetail,
    ProviderCapability,
    ProviderName,
    TestGenerateRequest,
    TestGenerateResponse,
    TestQAPair,
    TestVerifyRequest,
    TestVerifyResponse,
    TestVerifyResultItem,
    WorkerInfo,
)
from .updater import CLIUpdater
from .worker import WorkerManager

UI_INDEX = Path(__file__).with_name("ui") / "index.html"

API_DESCRIPTION = """\
Warm-worker API wrapper for AI coding CLIs (Gemini, Codex, Claude, Kimi, Copilot, OpenCode).

The API maintains **persistent warm worker processes** for each configured
provider/model pair, enabling low-latency prompt execution without cold-start
overhead.

## Key Concepts

- **Providers** — Supported AI CLIs: `gemini`, `codex`, `claude`, `kimi`, `copilot`, `opencode`.
- **Models** — Each provider exposes one or more models (e.g. `copilot` offers
  `claude-sonnet-4.6`, `gpt-5.4`, `gemini-3-flash-preview`, etc.).
  Use `GET /v1/models` to discover all available models with ready-to-use chat examples.
- **Workers** — Long-lived bash processes, one per provider/model pair,
  ready to execute prompts immediately.
- **Sessions** — Some providers support resuming previous conversations via
  a `provider_session_ref` returned in the response.

## Response Modes

The `POST /v1/chat` endpoint supports two response modes:

| Mode | `stream` | Content-Type | Description |
|------|----------|--------------|-------------|
| **JSON** | `false` | `application/json` | Single `ChatResponse` after completion |
| **SSE** | `true` (default) | `text/event-stream` | Real-time Server-Sent Events |

## SSE Event Reference

When streaming, the following event types are emitted:

| Event | Description | Data Fields |
|-------|-------------|-------------|
| `run_started` | CLI process launched | `provider`, `model` |
| `provider_session` | Session reference assigned | `provider_session_ref` |
| `output_delta` | Incremental output chunk | `text` |
| `completed` | Finished successfully | `provider`, `model`, `provider_session_ref`, `final_text`, `exit_code`, `warnings` |
| `failed` | Exited with error | `provider`, `model`, `provider_session_ref`, `exit_code`, `warnings`, `error` |

See the **Schemas** section below for the full structure of each SSE event payload.

## Test Lab

The Test Lab endpoints enable automated multi-model testing:

1. **Verify** (`POST /v1/test/verify`) — Deterministic keyword matching against resume responses.
2. **Generate Scenario** (`POST /v1/test/generate-scenario`) — AI-powered test scenario generation using the cheapest available model.

The web console includes a Test Lab UI that orchestrates a 2-step test (NEW → RESUME) across
all selected models in parallel, then calls the verify endpoint to grade results.
"""

OPENAPI_TAGS = [
    {
        "name": "Health",
        "description": "System health and readiness checks.",
    },
    {
        "name": "Providers",
        "description": "Query registered AI CLI providers and their capabilities.",
    },
    {
        "name": "Models",
        "description": (
            "Discover all supported models across providers. Each model entry includes "
            "its provider, readiness state, and a ready-to-use `POST /v1/chat` example request."
        ),
    },
    {
        "name": "Workers",
        "description": "Inspect the runtime state of warm worker processes.",
    },
    {
        "name": "Chat",
        "description": "Submit prompts to AI providers. Supports streaming (SSE) and synchronous JSON responses.",
    },
    {
        "name": "Updates",
        "description": "CLI version checking and auto-update management.",
    },
    {
        "name": "Test Lab",
        "description": (
            "Multi-model test harness for comparing AI CLI behavior across providers. "
            "Run a 2-step test (NEW chat then RESUME chat) against all selected models "
            "in parallel, then verify that resume responses contain expected keywords."
        ),
    },
    {
        "name": "Console",
        "description": "Built-in browser UI for testing the API interactively.",
    },
]

# Priority list for cheapest/fastest models used by the magic generate button.
_CHEAPEST_MODELS = [
    (ProviderName.CLAUDE, "haiku"),
    (ProviderName.CODEX, "gpt-5.4-mini"),
]


async def _stream_handle_events(handle) -> AsyncIterator[str]:
    while True:
        event = await handle.events.get()
        payload = dict(event)
        event_name = payload.pop("type")
        yield f"event: {event_name}\ndata: {json.dumps(payload)}\n\n"
        if event_name in {"completed", "failed"}:
            break


def create_app() -> FastAPI:
    config = load_config()
    manager = WorkerManager(config)
    updater = CLIUpdater(manager=manager, config=config.updater)

    @asynccontextmanager
    async def lifespan(_: FastAPI):
        await manager.start()
        updater.start()
        try:
            yield
        finally:
            await updater.stop()
            await manager.stop()

    app = FastAPI(
        title="AI CLI API",
        version="0.1.0",
        summary="Warm-worker API wrapper for AI coding CLIs",
        description=API_DESCRIPTION,
        openapi_tags=OPENAPI_TAGS,
        lifespan=lifespan,
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.state.config = config
    app.state.worker_manager = manager
    app.state.updater = updater

    # ------------------------------------------------------------------
    # Routes
    # ------------------------------------------------------------------

    @app.get(
        "/",
        response_class=HTMLResponse,
        tags=["Console"],
        summary="Web test console",
        description="Serves the built-in HTML console for interacting with workers in a browser. Returns HTML, not JSON.",
    )
    async def index() -> HTMLResponse:
        return HTMLResponse(UI_INDEX.read_text(encoding="utf-8"))

    @app.get(
        "/health",
        tags=["Health"],
        summary="System health check",
        description=(
            "Returns the overall health status of the API, including worker boot state, "
            "configuration path, and any degradation details. Status is `ok` when all "
            "workers are healthy, `degraded` when any worker reports an error."
        ),
        response_model=HealthResponse,
    )
    async def health() -> HealthResponse:
        details = manager.health_details()
        bash_version = await manager.get_bash_version()
        return HealthResponse(
            status="ok" if not details else "degraded",
            config_path=str(config.config_path),
            shell_path=manager.shell_path,
            bash_version=bash_version,
            workers_booted=all(worker.ready for worker in manager.workers.values()) if manager.workers else False,
            worker_count=len(manager.workers),
            details=details,
        )

    @app.get(
        "/v1/providers",
        tags=["Providers"],
        summary="List provider capabilities",
        description=(
            "Returns the capability matrix for all registered AI CLI providers, "
            "including whether each supports resume, streaming, and model override."
        ),
        response_model=list[ProviderCapability],
    )
    async def providers() -> list[ProviderCapability]:
        return manager.capabilities()

    @app.get(
        "/v1/models",
        tags=["Models"],
        summary="List all supported models with chat examples",
        description=(
            "Returns every configured model across all providers, along with its "
            "current readiness state and a ready-to-use example request body for "
            "`POST /v1/chat`.\n\n"
            "Use this endpoint to discover which models are available and how to "
            "call them. Copy the `chat_request_example` object, replace the "
            "`prompt` and `workspace_path` fields, and POST it to `/v1/chat`."
        ),
        response_model=list[ModelDetail],
    )
    async def models() -> list[ModelDetail]:
        return manager.model_details()

    @app.get(
        "/v1/workers",
        tags=["Workers"],
        summary="List active workers",
        description=(
            "Returns the runtime state of all warm worker processes, including "
            "readiness, busy state, queue depth, and last error."
        ),
        response_model=list[WorkerInfo],
    )
    async def workers() -> list[WorkerInfo]:
        return manager.worker_info()

    @app.post(
        "/v1/chat",
        tags=["Chat"],
        summary="Send a prompt to an AI provider",
        description="""\
Submit a prompt to a warm AI CLI worker.

### Response Modes

- **JSON** (`stream: false`): Returns a single `ChatResponse` JSON object after the CLI completes.
- **Streaming** (`stream: true`, default): Returns a `text/event-stream` (Server-Sent Events) response.

### SSE Event Types

| Event | Description | Data Fields |
|-------|-------------|-------------|
| `run_started` | CLI process launched | `provider`, `model` |
| `provider_session` | Session reference assigned | `provider_session_ref` |
| `output_delta` | Incremental output chunk | `text` |
| `completed` | CLI finished successfully | `provider`, `model`, `provider_session_ref`, `final_text`, `exit_code`, `warnings` |
| `failed` | CLI exited with error | `provider`, `model`, `provider_session_ref`, `exit_code`, `warnings`, `error` |

### Resuming Sessions

Set `mode` to `"resume"` and provide the `provider_session_ref` from a prior response.
Check `GET /v1/providers` for the `supports_resume` flag before attempting to resume.
""",
        response_model=ChatResponse,
        responses={
            200: {
                "description": "Chat completed successfully. Returns `ChatResponse` JSON when `stream: false`, or `text/event-stream` when `stream: true`.",
            },
            404: {
                "description": "No warm worker configured for the requested provider/model combination.",
                "model": ErrorDetail,
            },
            422: {
                "description": "Validation error. Common causes: relative workspace_path, missing provider_session_ref for resume mode, empty required fields.",
            },
            500: {
                "description": "The AI CLI process crashed or returned an unrecoverable error.",
                "model": ErrorDetail,
            },
        },
    )
    async def chat(request: ChatRequest):
        worker = manager.get_worker(request.provider, request.model)
        if worker is None:
            raise HTTPException(
                status_code=404,
                detail=f"No warm worker configured for provider={request.provider.value} model={request.model}",
            )

        handle = await worker.submit(request)
        if request.stream:
            return StreamingResponse(
                _stream_handle_events(handle),
                media_type="text/event-stream",
                headers={"Cache-Control": "no-cache", "Connection": "keep-alive"},
            )

        try:
            result = await handle.result_future
        except Exception as exc:
            raise HTTPException(status_code=500, detail=str(exc)) from exc
        return JSONResponse(content=result.model_dump())

    @app.get(
        "/v1/cli-versions",
        tags=["Updates"],
        summary="List CLI version statuses",
        description=(
            "Returns the cached version status for each enabled CLI provider from the "
            "most recent periodic check. Includes current version, latest available "
            "version, and whether an update is needed."
        ),
        response_model=list[CLIVersionStatus],
    )
    async def cli_versions() -> list[CLIVersionStatus]:
        return updater.last_results

    @app.post(
        "/v1/cli-versions/check",
        tags=["Updates"],
        summary="Trigger an immediate version check",
        description=(
            "Runs a full version check cycle now, comparing installed CLI versions "
            "against the latest published versions and auto-updating idle providers "
            "if auto_update is enabled. Returns the results."
        ),
        response_model=list[CLIVersionStatus],
    )
    async def cli_versions_check() -> list[CLIVersionStatus]:
        return await updater.check_and_update_all()

    @app.post(
        "/v1/cli-versions/{provider}/update",
        tags=["Updates"],
        summary="Force-update a single CLI provider",
        description=(
            "Triggers an immediate update for the specified provider CLI, "
            "regardless of the auto_update setting. The provider's workers "
            "must be idle; returns the updated version status."
        ),
        response_model=CLIVersionStatus,
        responses={
            404: {
                "description": "Unknown provider name.",
                "model": ErrorDetail,
            },
        },
    )
    async def cli_version_update(provider: ProviderName) -> CLIVersionStatus:
        return await updater.update_single_provider(provider)

    # ------------------------------------------------------------------
    # Test Lab routes
    # ------------------------------------------------------------------

    @app.post(
        "/v1/test/verify",
        tags=["Test Lab"],
        summary="Verify test results with keyword matching",
        description=(
            "Accepts per-model test results (exit codes and resume response text) and "
            "checks each against a list of expected keywords (case-insensitive). "
            "Returns a structured verdict for every model: new_status, resume_status, "
            "per-keyword match results, and an overall PASS/FAIL grade.\n\n"
            "A model receives **PASS** only when:\n"
            "1. The NEW chat exited with code 0\n"
            "2. The RESUME chat exited with code 0\n"
            "3. Every keyword appears (case-insensitive) in the resume response text"
        ),
        response_model=TestVerifyResponse,
    )
    async def test_verify(request: TestVerifyRequest) -> TestVerifyResponse:
        results: list[TestVerifyResultItem] = []
        for item in request.items:
            new_status = "OK" if item.new_exit_code == 0 else "FAIL"
            resume_status = "OK" if item.resume_exit_code == 0 else "FAIL"
            keyword_results = {
                kw.strip(): kw.strip().lower() in item.resume_text.lower()
                for kw in item.keywords
                if kw.strip()
            }
            all_keywords_found = all(keyword_results.values()) if keyword_results else True
            grade = (
                "PASS"
                if new_status == "OK" and resume_status == "OK" and all_keywords_found
                else "FAIL"
            )
            results.append(
                TestVerifyResultItem(
                    provider=item.provider,
                    model=item.model,
                    new_status=new_status,
                    resume_status=resume_status,
                    keyword_results=keyword_results,
                    grade=grade,
                )
            )
        return TestVerifyResponse(results=results)

    @app.post(
        "/v1/test/generate-scenario",
        tags=["Test Lab"],
        summary="AI-generate a test scenario",
        description=(
            "Uses the cheapest available model (Claude Haiku or GPT-5.4-mini) to "
            "generate test scenario content. Specify `field` as 'story', 'questions', "
            "'expected', or 'all' to generate one or all three fields.\n\n"
            "The response contains the generated text for each requested field. "
            "Fields not requested are returned as null."
        ),
        response_model=TestGenerateResponse,
        responses={
            503: {
                "description": "No cheap model worker is currently available.",
                "model": ErrorDetail,
            },
        },
    )
    async def test_generate_scenario(request: TestGenerateRequest) -> TestGenerateResponse:
        # Find cheapest ready worker
        worker = None
        for provider, model in _CHEAPEST_MODELS:
            w = manager.get_worker(provider, model)
            if w is not None and w.ready:
                worker = w
                break
        if worker is None:
            raise HTTPException(
                status_code=503,
                detail="No cheap model worker is currently available. Ensure haiku or gpt-5.4-mini workers are running.",
            )

        # Build prompt for generating a test scenario with multiple Q&A pairs
        prompt_text = (
            "Generate a test scenario for testing an AI assistant's memory. "
            "Return ONLY a JSON object (no markdown fencing, no explanation) with:\n"
            '- "story": A 2-3 sentence introduction about a person that includes specific facts like their name, '
            "job title, what they manage, a personal detail (car color, pet name, hobby, favorite food, etc). "
            'Example: "Hello my name is Sara and I am a marketing manager handling social media, SEO, and email campaigns. I have a blue bicycle."\n'
            '- "qa_pairs": An array of 3 objects, each with "question" and "expected" keys. '
            "Each question asks about a SPECIFIC FACT from the story. "
            'The "expected" field is a comma-separated list of SHORT keywords (1-2 words each) that must appear in the answer. '
            "Questions should test basic recall, not general knowledge.\n"
            "Example qa_pairs:\n"
            '[{"question":"What do I manage?","expected":"social media, SEO, email campaigns"},'
            '{"question":"What color is my bicycle?","expected":"blue"},'
            '{"question":"What is my job title?","expected":"marketing manager"}]\n'
            "Return ONLY the JSON object."
        )

        chat_req = ChatRequest(
            provider=worker.provider,
            model=worker.model,
            workspace_path=request.workspace_path,
            mode=ChatMode.NEW,
            prompt=prompt_text,
            stream=False,
        )
        handle = await worker.submit(chat_req)
        try:
            result = await handle.result_future
        except Exception as exc:
            raise HTTPException(status_code=500, detail=f"Generation failed: {exc}") from exc

        # Parse the AI response
        raw = result.final_text.strip()
        parsed = _parse_generate_response(raw, request.field)
        return parsed

    return app


def _parse_generate_response(raw: str, field: str) -> TestGenerateResponse:
    """Best-effort parse of AI-generated JSON from the model response."""

    def _build_response(data: dict) -> TestGenerateResponse:
        qa_pairs = []
        raw_pairs = data.get("qa_pairs", [])
        if isinstance(raw_pairs, list):
            for p in raw_pairs:
                if isinstance(p, dict) and "question" in p and "expected" in p:
                    qa_pairs.append(TestQAPair(question=p["question"], expected=p["expected"]))
        return TestGenerateResponse(
            story=data.get("story"),
            questions=data.get("questions"),
            expected=data.get("expected"),
            qa_pairs=qa_pairs,
        )

    # Try direct JSON parse
    try:
        data = json.loads(raw)
        if isinstance(data, dict):
            return _build_response(data)
    except json.JSONDecodeError:
        pass

    # Try extracting JSON from markdown fences
    fence_match = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", raw, re.DOTALL)
    if fence_match:
        try:
            data = json.loads(fence_match.group(1))
            if isinstance(data, dict):
                return _build_response(data)
        except json.JSONDecodeError:
            pass

    # Try finding a JSON object in the text (greedy to capture nested arrays)
    brace_match = re.search(r"\{.*\}", raw, re.DOTALL)
    if brace_match:
        try:
            data = json.loads(brace_match.group(0))
            if isinstance(data, dict):
                return _build_response(data)
        except json.JSONDecodeError:
            pass

    # Fallback: treat entire response as the story
    return TestGenerateResponse(story=raw)
