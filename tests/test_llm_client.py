import asyncio

import pytest

from app.errors import ModelOutputError, UpstreamTimeoutError
from app.llm_client import _extract_json, invoke_json_with_retries
from app.models import TriageOutput


class _Resp:
    def __init__(self, content: str):
        self.content = content


class _LLM:
    def __init__(self, actions):
        self.actions = actions
        self.calls = 0

    async def ainvoke(self, _prompt: str):
        action = self.actions[self.calls]
        self.calls += 1
        if isinstance(action, BaseException):
            raise action
        if callable(action):
            return await action()
        return _Resp(action)


def test_extract_json_from_markdown_fence():
    text = """```json
{"high_risk_areas": ["auth"], "missing_info": [], "recommended_modules_to_run": ["security"], "top_questions_for_author": []}
```"""
    parsed = _extract_json(text)
    assert parsed["high_risk_areas"] == ["auth"]


def test_invoke_json_retries_transient_then_succeeds(monkeypatch):
    import app.llm_client as llm_client

    async def _no_sleep(_seconds):
        return None

    monkeypatch.setattr(llm_client, "_is_transient_error", lambda exc: isinstance(exc, RuntimeError))
    monkeypatch.setattr(asyncio, "sleep", _no_sleep)

    llm = _LLM(
        [
            RuntimeError("temporary"),
            '{"high_risk_areas": [], "missing_info": [], "recommended_modules_to_run": ["security"], "top_questions_for_author": []}',
        ]
    )

    parsed, retry_count, repaired = asyncio.run(
        invoke_json_with_retries(
            llm=llm,
            prompt="prompt",
            schema=TriageOutput,
            timeout_seconds=1.0,
            max_retries=2,
            base_backoff_seconds=0.0,
        )
    )
    assert parsed["recommended_modules_to_run"] == ["security"]
    assert retry_count == 1
    assert repaired is False


def test_invoke_json_timeout_maps_to_upstream_timeout():
    async def _slow():
        await asyncio.sleep(0.05)
        return _Resp("{}")

    llm = _LLM([_slow])

    with pytest.raises(UpstreamTimeoutError):
        asyncio.run(
            invoke_json_with_retries(
                llm=llm,
                prompt="prompt",
                schema=TriageOutput,
                timeout_seconds=0.01,
                max_retries=0,
                base_backoff_seconds=0.0,
            )
        )


def test_invalid_structured_output_raises_structured_output_error():
    llm = _LLM(["not-json", "still-not-json"])
    with pytest.raises(ModelOutputError):
        asyncio.run(
            invoke_json_with_retries(
                llm=llm,
                prompt="prompt",
                schema=TriageOutput,
                timeout_seconds=1.0,
                max_retries=0,
                base_backoff_seconds=0.0,
            )
        )


def test_cancelled_error_propagates_without_upstream_mapping(monkeypatch):
    import app.llm_client as llm_client

    def _should_not_map(_exc):
        raise AssertionError("Cancellation must not be mapped to upstream errors")

    monkeypatch.setattr(llm_client, "_map_upstream_error", _should_not_map)

    llm = _LLM([asyncio.CancelledError()])
    with pytest.raises(asyncio.CancelledError):
        asyncio.run(
            invoke_json_with_retries(
                llm=llm,
                prompt="prompt",
                schema=TriageOutput,
                timeout_seconds=1.0,
                max_retries=2,
                base_backoff_seconds=0.0,
            )
        )
