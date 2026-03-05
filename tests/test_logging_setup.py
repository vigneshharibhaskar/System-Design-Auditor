import asyncio
import logging

import pytest
from fastapi import Request
from fastapi.responses import JSONResponse

from app.logging_setup import RequestContextMiddleware


def _build_request(method: str = "GET", path: str = "/test") -> Request:
    scope = {
        "type": "http",
        "http_version": "1.1",
        "method": method,
        "path": path,
        "headers": [],
        "query_string": b"",
        "client": ("127.0.0.1", 12345),
        "server": ("testserver", 80),
        "scheme": "http",
    }

    async def receive():
        return {"type": "http.request", "body": b"", "more_body": False}

    return Request(scope, receive)


def test_request_complete_logs_even_when_call_next_raises(caplog):
    middleware = RequestContextMiddleware(app=lambda *_args, **_kwargs: None)
    request = _build_request(path="/boom")
    request.state.request_id = "req-test-1"

    async def _call_next(_request):
        raise RuntimeError("boom")

    with caplog.at_level(logging.INFO, logger="app.request"):
        with pytest.raises(RuntimeError):
            asyncio.run(middleware.dispatch(request, _call_next))

    failed = [r for r in caplog.records if r.getMessage() == "request_failed"]
    complete = [r for r in caplog.records if r.getMessage() == "request_complete"]

    assert failed, "expected request_failed log"
    assert complete, "expected request_complete log even on exception"
    assert failed[0].request_id == "req-test-1"
    assert failed[0].status_code == "error"
    assert failed[0].error_class == "RuntimeError"
    assert complete[0].request_id == "req-test-1"
    assert complete[0].status_code == "error"
    assert complete[0].error_class == "RuntimeError"


def test_request_complete_includes_analyze_context_from_state(caplog):
    middleware = RequestContextMiddleware(app=lambda *_args, **_kwargs: None)
    request = _build_request(method="POST", path="/analyze")
    request.state.request_id = "req-test-2"
    request.state.collection = "default"
    request.state.mode = "targeted"
    request.state.top_k = 6
    request.state.budget_modules = 3
    request.state.selected_modules = ["security", "reliability"]
    request.state.context_chars_used = 4800
    request.state.retry_count = 1

    async def _call_next(_request):
        return JSONResponse({"ok": True}, status_code=200)

    with caplog.at_level(logging.INFO, logger="app.request"):
        response = asyncio.run(middleware.dispatch(request, _call_next))

    complete = [r for r in caplog.records if r.getMessage() == "request_complete"]
    assert complete, "expected request_complete log"
    record = complete[0]
    assert record.request_id == "req-test-2"
    assert record.status_code == 200
    assert record.collection == "default"
    assert record.mode == "targeted"
    assert record.top_k == 6
    assert record.budget_modules == 3
    assert record.selected_modules == ["security", "reliability"]
    assert record.context_chars_used == 4800
    assert record.retry_count == 1
    assert response.headers.get("x-request-id") == "req-test-2"
