from fastapi.testclient import TestClient

from app.errors import ModelOutputError, UpstreamModelError, UpstreamTimeoutError
from app.main import app
import app.main as main_module


def _payload():
    return {
        "collection": "default",
        "query": "test",
        "mode": "triage",
        "top_k": 2,
        "file_filter": None,
        "budget_modules": 1,
    }


def test_analyze_maps_upstream_timeout_to_504(monkeypatch):
    async def _raise_timeout(*_args, **_kwargs):
        raise UpstreamTimeoutError("Model request timed out")

    monkeypatch.setattr(main_module, "_ensure_openai_configured", lambda: None)
    monkeypatch.setattr(main_module, "retrieve_context", lambda **_kwargs: ([{"x": 1}], "ctx"))
    monkeypatch.setattr(main_module, "run_triage", _raise_timeout)

    client = TestClient(app)
    response = client.post("/analyze", json=_payload())

    assert response.status_code == 504
    body = response.json()
    assert body["ok"] is False
    assert body["error"]["code"] == "UPSTREAM_TIMEOUT"
    assert body["error"]["retryable"] is True
    assert "request_id" in body


def test_analyze_maps_model_output_invalid_to_502(monkeypatch):
    async def _raise_output_invalid(*_args, **_kwargs):
        raise ModelOutputError("The model returned invalid structured output after repair attempt")

    monkeypatch.setattr(main_module, "_ensure_openai_configured", lambda: None)
    monkeypatch.setattr(main_module, "retrieve_context", lambda **_kwargs: ([{"x": 1}], "ctx"))
    monkeypatch.setattr(main_module, "run_triage", _raise_output_invalid)

    client = TestClient(app)
    response = client.post("/analyze", json=_payload())

    assert response.status_code == 502
    body = response.json()
    assert body["ok"] is False
    assert body["error"]["code"] == "MODEL_OUTPUT_INVALID"
    assert body["error"]["retryable"] is True


def test_analyze_maps_upstream_model_error_to_502(monkeypatch):
    async def _raise_model_error(*_args, **_kwargs):
        raise UpstreamModelError("Model failed with non-retryable upstream error")

    monkeypatch.setattr(main_module, "_ensure_openai_configured", lambda: None)
    monkeypatch.setattr(main_module, "retrieve_context", lambda **_kwargs: ([{"x": 1}], "ctx"))
    monkeypatch.setattr(main_module, "run_triage", _raise_model_error)

    client = TestClient(app)
    response = client.post("/analyze", json=_payload())

    assert response.status_code == 502
    body = response.json()
    assert body["ok"] is False
    assert body["error"]["code"] == "UPSTREAM_MODEL_ERROR"


def test_analyze_empty_collection_maps_to_collection_empty(monkeypatch):
    monkeypatch.setattr(main_module, "_ensure_openai_configured", lambda: None)
    monkeypatch.setattr(main_module, "retrieve_context", lambda **_kwargs: ([], ""))

    client = TestClient(app)
    response = client.post("/analyze", json=_payload())

    assert response.status_code == 404
    body = response.json()
    assert body["error"]["code"] == "COLLECTION_EMPTY"
    assert body["error"]["retryable"] is False


def test_analyze_file_filter_mismatch_maps_to_404(monkeypatch):
    monkeypatch.setattr(main_module, "_ensure_openai_configured", lambda: None)
    monkeypatch.setattr(main_module, "retrieve_context", lambda **_kwargs: ([], ""))

    client = TestClient(app)
    payload = _payload()
    payload["file_filter"] = "missing.pdf"
    response = client.post("/analyze", json=payload)

    assert response.status_code == 404
    body = response.json()
    assert body["error"]["code"] == "FILE_FILTER_NO_MATCH"
