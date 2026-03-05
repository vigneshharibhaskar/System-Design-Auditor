from __future__ import annotations

import logging
import asyncio
import time
import uuid
from pathlib import Path

from fastapi import FastAPI, File, Header, Query, Request, UploadFile
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from app.config import get_settings
from app.errors import (
    CollectionEmptyError,
    DomainError,
    FileFilterNoMatchError,
    IngestAuthError,
    PayloadValidationError,
    UpstreamTimeoutError,
)
from app.ingest import ingest_pdf, list_ingested_files
from app.logging_setup import RequestContextMiddleware, configure_logging
from app.models import AnalyzeRequest, AnalyzeResponse, HealthResponse
from app.prompts import DEEP_MODULES, MODULES
from app.retrieval import retrieve_context
from app.reviewers import run_module_review, run_triage
from app.scoring import compute_overall

settings = get_settings()
configure_logging(settings.log_level)
logger = logging.getLogger("app")
RETRIEVAL_SEMAPHORE = asyncio.Semaphore(settings.retrieval_concurrency)

app = FastAPI(title="System Design Reviewer", version="1.0.0")
app.add_middleware(RequestContextMiddleware)
STATIC_DIR = Path(__file__).parent / "static"
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


@app.middleware("http")
async def add_request_id(request: Request, call_next):
    request.state.request_id = str(uuid.uuid4())
    request.state.request_start_perf = time.perf_counter()
    return await call_next(request)


def _request_latency_ms(request: Request) -> float:
    start = getattr(request.state, "request_start_perf", None)
    if start is None:
        return 0.0
    return round((time.perf_counter() - start) * 1000, 2)


@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception):
    logger.exception(
        "unhandled_error",
        extra={
            "request_id": getattr(request.state, "request_id", "unknown"),
            "latency_ms": _request_latency_ms(request),
            "error_class": exc.__class__.__name__,
            "error_code": "INTERNAL_ERROR",
            "retryable": False,
            "error_message": "Internal server error",
        },
    )
    request_id = getattr(request.state, "request_id", "unknown")
    return JSONResponse(
        status_code=500,
        content={
            "ok": False,
            "request_id": request_id,
            "error": {
                "code": "INTERNAL_ERROR",
                "message": "Internal server error",
                "retryable": False,
            },
        },
    )


@app.exception_handler(DomainError)
async def service_error_handler(request: Request, exc: DomainError):
    request_id = getattr(request.state, "request_id", "unknown")
    logger.warning(
        "service_error",
        extra={
            "request_id": request_id,
            "latency_ms": _request_latency_ms(request),
            "status_code": exc.http_status,
            "error_code": exc.code,
            "retryable": exc.retryable,
            "error_message": exc.message,
            "error_class": exc.__class__.__name__,
        },
    )
    return JSONResponse(status_code=exc.http_status, content=exc.to_error_payload(request_id=request_id))


@app.exception_handler(RequestValidationError)
async def request_validation_error_handler(request: Request, exc: RequestValidationError):
    request_id = getattr(request.state, "request_id", str(uuid.uuid4()))
    return JSONResponse(
        status_code=422,
        content={
            "ok": False,
            "request_id": request_id,
            "error": {
                "code": "REQUEST_VALIDATION_ERROR",
                "message": "Request validation failed",
                "retryable": False,
                "details": exc.errors(),
            },
        },
    )


def _ensure_openai_configured() -> None:
    if not settings.openai_api_key:
        raise PayloadValidationError("OPENAI_API_KEY is required for this operation")


def _ensure_ingest_token_configured() -> None:
    if not settings.ingest_token:
        raise PayloadValidationError("INGEST_TOKEN is not configured")


async def _retrieve_context_with_limit(
    *,
    collection: str,
    query: str,
    top_k: int,
    file_filter: str | None,
    timeout_seconds: float,
) -> tuple[list[dict], str]:
    await RETRIEVAL_SEMAPHORE.acquire()
    task = asyncio.create_task(
        asyncio.to_thread(
            retrieve_context,
            collection=collection,
            query=query,
            top_k=top_k,
            file_filter=file_filter,
        )
    )
    release_state = {"released": False}

    def _release_once() -> None:
        if not release_state["released"]:
            RETRIEVAL_SEMAPHORE.release()
            release_state["released"] = True

    try:
        result = await asyncio.wait_for(task, timeout=timeout_seconds)
        _release_once()
        return result
    except asyncio.TimeoutError:
        # If timeout happens, the thread may still run. Release only when it actually completes.
        task.add_done_callback(lambda _fut: _release_once())
        raise
    except Exception:
        _release_once()
        raise


@app.get("/health", response_model=HealthResponse)
def health() -> HealthResponse:
    return HealthResponse(status="ok")


@app.get("/")
def frontend() -> FileResponse:
    return FileResponse(STATIC_DIR / "index.html")


@app.post("/ingest")
def ingest(
    request: Request,
    file: UploadFile = File(...),
    collection: str = Query(default="default"),
    x_ingest_token: str | None = Header(default=None),
):
    _ensure_ingest_token_configured()
    if x_ingest_token != settings.ingest_token:
        raise IngestAuthError("Invalid ingest token")
    _ensure_openai_configured()

    start = time.perf_counter()
    result = ingest_pdf(file, collection)
    logger.info(
        "ingest_complete",
        extra={
            "request_id": request.state.request_id,
            "latency_ms": round((time.perf_counter() - start) * 1000, 2),
        },
    )
    return result


@app.get("/files")
def files(
    request: Request,
    collection: str = Query(default="default"),
    limit: int = Query(default=settings.files_default_limit, ge=1),
    offset: int = Query(default=0, ge=0),
):
    bounded_limit = min(limit, settings.files_max_limit)
    result = list_ingested_files(collection=collection, limit=bounded_limit, offset=offset)
    return {
        "ok": True,
        "request_id": request.state.request_id,
        "items": result["items"],
        # Backward-compat alias for existing UIs.
        "files": result["items"],
        "limit": bounded_limit,
        "offset": offset,
    }


@app.post("/analyze", response_model=AnalyzeResponse)
async def analyze(request: Request, payload: AnalyzeRequest):
    _ensure_openai_configured()
    start = time.perf_counter()
    total_retry_count = 0
    json_repair_used = False

    top_k = payload.top_k or settings.default_top_k
    budget = payload.budget_modules or settings.default_budget_modules
    request.state.collection = payload.collection
    request.state.mode = payload.mode
    request.state.top_k = top_k
    request.state.budget_modules = budget
    request.state.selected_modules = []
    request.state.context_chars_used = 0
    request.state.retry_count = 0
    try:
        context_items, context_text = await _retrieve_context_with_limit(
            collection=payload.collection,
            query=payload.query,
            top_k=top_k,
            file_filter=payload.file_filter,
            timeout_seconds=settings.retrieval_timeout_seconds,
        )
    except asyncio.TimeoutError as exc:
        raise UpstreamTimeoutError("Retrieval/embedding request timed out") from exc

    if not context_items:
        if payload.file_filter:
            raise FileFilterNoMatchError("No context found for provided file_filter")
        raise CollectionEmptyError("No context found in collection")

    request.state.context_chars_used = len(context_text)
    triage, triage_retries, triage_repaired = await run_triage(context_text=context_text, user_query=payload.query)
    total_retry_count += triage_retries
    json_repair_used = json_repair_used or triage_repaired
    modules: dict = {}
    selected_modules: list[str] = []

    if payload.mode == "triage":
        modules = {}
    elif payload.mode == "targeted":
        recommended = triage.get("recommended_modules_to_run", [])
        selected_modules = [m for m in recommended if m in MODULES][:budget]
        for module in selected_modules:
            module_result, module_retries, module_repaired = await run_module_review(
                module_name=module, context_text=context_text, user_query=payload.query
            )
            total_retry_count += module_retries
            json_repair_used = json_repair_used or module_repaired
            modules[module] = module_result
    else:
        selected_modules = DEEP_MODULES[:6]
        for module in selected_modules:
            module_result, module_retries, module_repaired = await run_module_review(
                module_name=module, context_text=context_text, user_query=payload.query
            )
            total_retry_count += module_retries
            json_repair_used = json_repair_used or module_repaired
            modules[module] = module_result

    request.state.selected_modules = selected_modules
    request.state.retry_count = total_retry_count
    overall = compute_overall(modules)
    latency_ms = round((time.perf_counter() - start) * 1000, 2)
    logger.info(
        "analysis_complete",
        extra={
            "request_id": request.state.request_id,
            "latency_ms": latency_ms,
            "collection": payload.collection,
            "mode": payload.mode,
            "top_k": top_k,
            "budget_modules": budget,
            "selected_modules": selected_modules,
            "context_chars_used": len(context_text),
            "retry_count": total_retry_count,
            "retrieval_concurrency": settings.retrieval_concurrency,
        },
    )

    return AnalyzeResponse(
        overall=overall,
        triage=triage,
        modules=modules,
        meta={
            "request_id": request.state.request_id,
            "retry_count": total_retry_count,
            "json_repaired": json_repair_used,
            "context_chars_used": len(context_text),
            "latency_ms": latency_ms,
        },
    )
