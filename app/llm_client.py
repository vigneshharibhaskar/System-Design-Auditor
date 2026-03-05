from __future__ import annotations

import asyncio
import json
import random
from typing import TypeVar

from langchain_openai import ChatOpenAI
from openai import APIConnectionError, APIStatusError, APITimeoutError, RateLimitError
from pydantic import BaseModel, ValidationError

from app.errors import ModelOutputError, UpstreamModelError, UpstreamTimeoutError

SchemaModel = TypeVar("SchemaModel", bound=BaseModel)


def _extract_json(text: str) -> dict:
    cleaned = text.strip()
    if cleaned.startswith("```"):
        cleaned = cleaned.strip("`").strip()
    if cleaned.lower().startswith("json"):
        cleaned = cleaned[4:].strip()

    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        start = cleaned.find("{")
        end = cleaned.rfind("}")
        if start == -1 or end == -1 or end <= start:
            raise
        return json.loads(cleaned[start : end + 1])


def _is_transient_error(exc: Exception) -> bool:
    if isinstance(exc, (asyncio.TimeoutError, APITimeoutError, APIConnectionError, RateLimitError)):
        return True
    if isinstance(exc, APIStatusError):
        return exc.status_code in {429, 500, 502, 503, 504}
    return False


def _map_upstream_error(exc: Exception) -> Exception:
    if isinstance(exc, (asyncio.TimeoutError, APITimeoutError)):
        return UpstreamTimeoutError("Model request timed out")
    if isinstance(exc, (APIConnectionError, RateLimitError)):
        return UpstreamModelError("Model service is temporarily unavailable")
    if isinstance(exc, APIStatusError):
        if exc.status_code in {429, 500, 502, 503, 504}:
            return UpstreamModelError("Model service is temporarily unavailable")
        error = UpstreamModelError("Model request failed with a non-retryable upstream error")
        error.retryable = False
        return error
    return UpstreamModelError("Model request failed unexpectedly")


async def _invoke_with_retry(
    llm: ChatOpenAI,
    prompt: str,
    timeout_seconds: float,
    max_retries: int,
    base_backoff_seconds: float,
) -> tuple[str, int]:
    retries_used = 0
    last_exc: Exception | None = None

    for attempt in range(max_retries + 1):
        try:
            response = await asyncio.wait_for(llm.ainvoke(prompt), timeout=timeout_seconds)
            content = response.content if isinstance(response.content, str) else str(response.content)
            return content, retries_used
        except asyncio.CancelledError:
            # Preserve cooperative cancellation and never convert it to upstream errors.
            raise
        except Exception as exc:
            last_exc = exc
            if not _is_transient_error(exc) or attempt == max_retries:
                raise _map_upstream_error(exc) from exc
            retries_used += 1
            delay = (base_backoff_seconds * (2**attempt)) + random.uniform(0, base_backoff_seconds)
            await asyncio.sleep(delay)

    # Defensive fallback; loop always returns or raises.
    raise _map_upstream_error(last_exc or Exception("unknown upstream error"))


async def invoke_json_with_retries(
    llm: ChatOpenAI,
    prompt: str,
    schema: type[SchemaModel],
    timeout_seconds: float,
    max_retries: int,
    base_backoff_seconds: float,
) -> tuple[dict, int, bool]:
    total_retry_count = 0

    content, retries = await _invoke_with_retry(llm, prompt, timeout_seconds, max_retries, base_backoff_seconds)
    total_retry_count += retries
    try:
        parsed = _extract_json(content)
        validated = schema.model_validate(parsed).model_dump()
        return validated, total_retry_count, False
    except (json.JSONDecodeError, ValidationError):
        repair_prompt = prompt + "\n\nReturn JSON only, no markdown."
        repaired_content, repair_retries = await _invoke_with_retry(
            llm, repair_prompt, timeout_seconds, max_retries, base_backoff_seconds
        )
        total_retry_count += repair_retries
        try:
            repaired_parsed = _extract_json(repaired_content)
            validated = schema.model_validate(repaired_parsed).model_dump()
            return validated, total_retry_count, True
        except (json.JSONDecodeError, ValidationError) as exc:
            raise ModelOutputError("The model returned invalid structured output after repair attempt") from exc
