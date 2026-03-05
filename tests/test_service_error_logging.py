import logging

from fastapi.testclient import TestClient

import app.main as main_module
from app.main import app


def test_service_error_log_includes_structured_fields(monkeypatch, caplog):
    monkeypatch.setattr(main_module, "_ensure_openai_configured", lambda: None)
    monkeypatch.setattr(main_module, "retrieve_context", lambda **_kwargs: ([], ""))

    client = TestClient(app)
    payload = {
        "collection": "default",
        "query": "test",
        "mode": "triage",
        "top_k": 2,
        "file_filter": None,
        "budget_modules": 1,
    }

    with caplog.at_level(logging.WARNING, logger="app"):
        response = client.post("/analyze", json=payload)

    assert response.status_code == 404
    service_logs = [r for r in caplog.records if r.getMessage() == "service_error"]
    assert service_logs, "expected service_error log record"
    record = service_logs[0]
    assert getattr(record, "request_id", None)
    assert getattr(record, "latency_ms", None) is not None
    assert record.error_code == "COLLECTION_EMPTY"
    assert record.retryable is False
    assert record.error_message == "No context found in collection"
    assert record.error_class == "CollectionEmptyError"
