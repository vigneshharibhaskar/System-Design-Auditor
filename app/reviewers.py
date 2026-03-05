from __future__ import annotations

from langchain_openai import ChatOpenAI

from app.config import get_settings
from app.errors import PayloadValidationError
from app.llm_client import invoke_json_with_retries
from app.models import ModuleReviewOutput, TriageOutput
from app.prompts import MODULE_PROMPT_TEMPLATE, TRIAGE_PROMPT

def _build_llm() -> ChatOpenAI:
    settings = get_settings()
    if not settings.openai_api_key:
        raise PayloadValidationError("OPENAI_API_KEY is required for analysis operations")
    return ChatOpenAI(model=settings.model_name, api_key=settings.openai_api_key, temperature=0, max_retries=0)


async def run_triage(context_text: str, user_query: str) -> tuple[dict, int, bool]:
    llm = _build_llm()
    settings = get_settings()
    prompt = (
        f"{TRIAGE_PROMPT}\n\n"
        f"User query:\n{user_query}\n\n"
        f"Retrieved context:\n{context_text}\n"
    )
    return await invoke_json_with_retries(
        llm=llm,
        prompt=prompt,
        schema=TriageOutput,
        timeout_seconds=settings.llm_timeout_seconds,
        max_retries=settings.llm_max_retries,
        base_backoff_seconds=settings.llm_retry_base_backoff_seconds,
    )


async def run_module_review(module_name: str, context_text: str, user_query: str) -> tuple[dict, int, bool]:
    llm = _build_llm()
    settings = get_settings()
    module_prompt = MODULE_PROMPT_TEMPLATE.format(module_name=module_name)
    prompt = (
        f"{module_prompt}\n\n"
        f"User query:\n{user_query}\n\n"
        f"Retrieved context:\n{context_text}\n"
    )
    return await invoke_json_with_retries(
        llm=llm,
        prompt=prompt,
        schema=ModuleReviewOutput,
        timeout_seconds=settings.llm_timeout_seconds,
        max_retries=settings.llm_max_retries,
        base_backoff_seconds=settings.llm_retry_base_backoff_seconds,
    )
