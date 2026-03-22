import os
from fastapi.testclient import TestClient

from ai_cli_api.service import create_app


def test_health_and_provider_endpoints(config_path):
    app = create_app()
    with TestClient(app) as client:
        index = client.get("/")
        assert index.status_code == 200
        assert "Warm Worker Console" in index.text

        health = client.get("/health")
        assert health.status_code == 200
        payload = health.json()
        assert payload["worker_count"] == 9

        providers = client.get("/v1/providers")
        assert providers.status_code == 200
        assert len(providers.json()) == 6

        workers = client.get("/v1/workers")
        assert workers.status_code == 200
        assert len(workers.json()) == 9


def test_chat_json_and_streaming(config_path, tmp_path):
    app = create_app()
    with TestClient(app) as client:
        body = {
            "provider": "claude",
            "model": "sonnet",
            "workspace_path": str(tmp_path.resolve()),
            "mode": "new",
            "prompt": "hello",
            "stream": False,
        }
        response = client.post("/v1/chat", json=body)
        assert response.status_code == 200
        payload = response.json()
        assert payload["final_text"] == "claude:hello"
        assert payload["provider_session_ref"]

        stream_body = {
            "provider": "codex",
            "model": "codex-5.3",
            "workspace_path": str(tmp_path.resolve()),
            "mode": "new",
            "prompt": "hello",
            "stream": True,
        }
        with client.stream("POST", "/v1/chat", json=stream_body) as stream_response:
            assert stream_response.status_code == 200
            text = "".join(stream_response.iter_text())
        assert "event: run_started" in text
        assert "event: provider_session" in text
        assert "event: completed" in text
        assert "codex:hello" in text

        assert not list(tmp_path.rglob("*.sqlite"))


def test_chat_copilot_json(config_path, tmp_path):
    app = create_app()
    with TestClient(app) as client:
        body = {
            "provider": "copilot",
            "model": "claude-sonnet-4.6",
            "workspace_path": str(tmp_path.resolve()),
            "mode": "new",
            "prompt": "hello",
            "stream": False,
        }
        response = client.post("/v1/chat", json=body)
        assert response.status_code == 200
        payload = response.json()
        assert payload["final_text"] == "copilot:hello"
        assert payload["provider_session_ref"]


def test_chat_opencode_json(config_path, tmp_path):
    app = create_app()
    with TestClient(app) as client:
        body = {
            "provider": "opencode",
            "model": "glm-4.7-flash",
            "workspace_path": str(tmp_path.resolve()),
            "mode": "new",
            "prompt": "hello",
            "stream": False,
        }
        response = client.post("/v1/chat", json=body)
        assert response.status_code == 200
        payload = response.json()
        assert payload["final_text"] == "opencode:hello"
        assert payload["provider_session_ref"]


def test_chat_returns_404_for_unknown_worker(config_path, tmp_path):
    app = create_app()
    with TestClient(app) as client:
        body = {
            "provider": "claude",
            "model": "nonexistent-model",
            "workspace_path": str(tmp_path.resolve()),
            "mode": "new",
            "prompt": "hello",
            "stream": False,
        }
        response = client.post("/v1/chat", json=body)
        assert response.status_code == 404


def test_chat_resume_requires_session_ref(config_path, tmp_path):
    app = create_app()
    with TestClient(app) as client:
        body = {
            "provider": "claude",
            "model": "sonnet",
            "workspace_path": str(tmp_path.resolve()),
            "mode": "resume",
            "prompt": "hello",
            "stream": False,
        }
        response = client.post("/v1/chat", json=body)
        assert response.status_code == 422


def test_chat_rejects_relative_workspace_path(config_path):
    app = create_app()
    with TestClient(app) as client:
        body = {
            "provider": "claude",
            "model": "sonnet",
            "workspace_path": "relative/path",
            "mode": "new",
            "prompt": "hello",
            "stream": False,
        }
        response = client.post("/v1/chat", json=body)
        assert response.status_code == 422


def test_workers_endpoint_reflects_worker_state(config_path, tmp_path):
    app = create_app()
    with TestClient(app) as client:
        workers = client.get("/v1/workers").json()
        providers_seen = {w["provider"] for w in workers}
        assert "claude" in providers_seen
        assert "gemini" in providers_seen
        assert "codex" in providers_seen
        assert "kimi" in providers_seen
        assert "copilot" in providers_seen
        assert "opencode" in providers_seen
        assert all(w["ready"] for w in workers)
        assert all(not w["busy"] for w in workers)


def test_providers_endpoint_shows_capabilities(config_path):
    app = create_app()
    with TestClient(app) as client:
        providers = client.get("/v1/providers").json()
        for p in providers:
            assert "supports_resume" in p
            assert "supports_streaming" in p
            assert "supports_model_override" in p
            assert "session_reference_format" in p
            assert "models" in p
            assert isinstance(p["models"], list)
            assert len(p["models"]) >= 1


def test_models_endpoint_returns_all_models(config_path):
    app = create_app()
    with TestClient(app) as client:
        models = client.get("/v1/models").json()
        assert len(models) == 9  # 2 gemini + 2 codex + 2 claude + 1 kimi + 1 copilot + 1 opencode
        providers_seen = {m["provider"] for m in models}
        assert "claude" in providers_seen
        assert "copilot" in providers_seen
        for m in models:
            assert "model" in m
            assert "ready" in m
            assert "busy" in m
            assert "supports_resume" in m
            assert "chat_request_example" in m
            example = m["chat_request_example"]
            assert example["provider"] == m["provider"]
            assert example["model"] == m["model"]
            assert example["mode"] == "new"
            assert "prompt" in example
            assert "workspace_path" in example


def test_cors_headers_present(config_path):
    app = create_app()
    with TestClient(app) as client:
        response = client.options(
            "/v1/chat",
            headers={
                "Origin": "http://localhost:3000",
                "Access-Control-Request-Method": "POST",
            },
        )
        assert response.headers.get("access-control-allow-origin") == "*"


def test_no_persistent_state_files_created(config_path, tmp_path):
    """The wrapper must not create any database or session files."""
    app = create_app()
    with TestClient(app) as client:
        body = {
            "provider": "kimi",
            "model": "default",
            "workspace_path": str(tmp_path.resolve()),
            "mode": "new",
            "prompt": "hello",
            "stream": False,
        }
        client.post("/v1/chat", json=body)

        for ext in ("*.sqlite", "*.db", "*.json"):
            assert not list(tmp_path.rglob(ext)), f"Found unexpected {ext} files"
