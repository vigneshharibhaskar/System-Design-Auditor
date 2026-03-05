from fastapi.testclient import TestClient

from app.main import app


def test_analyze_request_validation_error_envelope_for_wrong_type():
    client = TestClient(app)
    payload = {
        "collection": "default",
        "query": "review",
        "mode": "targeted",
        "top_k": "not-a-number",
        "budget_modules": 3,
        "file_filter": None,
    }
    response = client.post("/analyze", json=payload)

    assert response.status_code == 422
    body = response.json()
    assert body["ok"] is False
    assert "request_id" in body
    assert body["error"]["code"] == "REQUEST_VALIDATION_ERROR"
    assert body["error"]["retryable"] is False
    assert isinstance(body["error"]["details"], list)
    assert body["error"]["details"]


def test_analyze_request_validation_error_envelope_for_invalid_literal():
    client = TestClient(app)
    payload = {
        "collection": "default",
        "query": "review",
        "mode": "not-a-valid-mode",
        "top_k": 6,
        "budget_modules": 3,
        "file_filter": None,
    }
    response = client.post("/analyze", json=payload)

    assert response.status_code == 422
    body = response.json()
    assert body["ok"] is False
    assert "request_id" in body
    assert body["error"]["code"] == "REQUEST_VALIDATION_ERROR"
    assert body["error"]["message"] == "Request validation failed"
    assert isinstance(body["error"]["details"], list)
