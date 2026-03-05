import json
import logging
import time
from typing import Any

from fastapi import Request
from starlette.middleware.base import BaseHTTPMiddleware


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "timestamp": int(time.time()),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        for key in (
            "request_id",
            "method",
            "path",
            "status_code",
            "latency_ms",
            "error_class",
            "collection",
            "mode",
            "top_k",
            "budget_modules",
            "selected_modules",
            "context_chars_used",
            "retry_count",
            "retrieval_concurrency",
            "error_code",
            "retryable",
            "error_message",
        ):
            if hasattr(record, key):
                payload[key] = getattr(record, key)
        return json.dumps(payload)


def configure_logging(level: str = "INFO") -> None:
    root = logging.getLogger()
    root.setLevel(level.upper())
    root.handlers.clear()

    handler = logging.StreamHandler()
    handler.setFormatter(JsonFormatter())
    root.addHandler(handler)


class RequestContextMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        start = time.perf_counter()
        request_id = getattr(request.state, "request_id", "unknown")
        response = None
        status_code: int | str = "error"
        error_class: str | None = None

        try:
            response = await call_next(request)
            status_code = response.status_code
        except Exception as exc:
            error_class = exc.__class__.__name__
            logging.getLogger("app.request").warning(
                "request_failed",
                extra={
                    "request_id": request_id,
                    "method": request.method,
                    "path": request.url.path,
                    "status_code": "error",
                    "latency_ms": round((time.perf_counter() - start) * 1000, 2),
                    "error_class": error_class,
                    "collection": getattr(request.state, "collection", None),
                    "mode": getattr(request.state, "mode", None),
                    "top_k": getattr(request.state, "top_k", None),
                    "budget_modules": getattr(request.state, "budget_modules", None),
                    "selected_modules": getattr(request.state, "selected_modules", None),
                    "context_chars_used": getattr(request.state, "context_chars_used", None),
                    "retry_count": getattr(request.state, "retry_count", None),
                },
            )
            raise
        finally:
            latency_ms = round((time.perf_counter() - start) * 1000, 2)
            logging.getLogger("app.request").info(
                "request_complete",
                extra={
                    "request_id": request_id,
                    "method": request.method,
                    "path": request.url.path,
                    "status_code": status_code,
                    "latency_ms": latency_ms,
                    "error_class": error_class,
                    "collection": getattr(request.state, "collection", None),
                    "mode": getattr(request.state, "mode", None),
                    "top_k": getattr(request.state, "top_k", None),
                    "budget_modules": getattr(request.state, "budget_modules", None),
                    "selected_modules": getattr(request.state, "selected_modules", None),
                    "context_chars_used": getattr(request.state, "context_chars_used", None),
                    "retry_count": getattr(request.state, "retry_count", None),
                },
            )
            if response is not None:
                response.headers["x-request-id"] = request_id

        return response
