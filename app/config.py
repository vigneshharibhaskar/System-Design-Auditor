from functools import lru_cache
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    openai_api_key: str | None = Field(default=None, alias="OPENAI_API_KEY")
    model_name: str = Field(default="gpt-4o-mini", alias="MODEL_NAME")
    embedding_model: str = Field(default="text-embedding-3-small", alias="EMBEDDING_MODEL")

    app_env: str = Field(default="development", alias="APP_ENV")
    log_level: str = Field(default="INFO", alias="LOG_LEVEL")
    ingest_token: str | None = Field(default=None, alias="INGEST_TOKEN")

    uploads_dir: Path = Field(default=Path("data/uploads"), alias="UPLOADS_DIR")
    chroma_dir: Path = Field(default=Path("data/chroma"), alias="CHROMA_DIR")

    max_chunk_chars: int = Field(default=220, alias="MAX_CHUNK_CHARS")
    max_context_chars: int = Field(default=6000, alias="MAX_CONTEXT_CHARS")
    default_top_k: int = Field(default=6, alias="DEFAULT_TOP_K")
    default_budget_modules: int = Field(default=3, alias="DEFAULT_BUDGET_MODULES")
    llm_timeout_seconds: float = Field(default=30.0, alias="LLM_TIMEOUT_SECONDS")
    llm_max_retries: int = Field(default=2, alias="LLM_MAX_RETRIES")
    llm_retry_base_backoff_seconds: float = Field(default=0.35, alias="LLM_RETRY_BASE_BACKOFF_SECONDS")
    retrieval_timeout_seconds: float = Field(default=15.0, alias="RETRIEVAL_TIMEOUT_SECONDS")
    retrieval_concurrency: int = Field(default=4, alias="RETRIEVAL_CONCURRENCY")
    files_default_limit: int = Field(default=50, alias="FILES_DEFAULT_LIMIT")
    files_max_limit: int = Field(default=200, alias="FILES_MAX_LIMIT")
    max_upload_bytes: int = Field(default=20 * 1024 * 1024, alias="MAX_UPLOAD_BYTES")
    allowed_upload_content_types: str = Field(
        default="application/pdf,application/octet-stream", alias="ALLOWED_UPLOAD_CONTENT_TYPES"
    )

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        protected_namespaces=("settings_",),
    )


@lru_cache
def get_settings() -> Settings:
    settings = Settings()
    settings.uploads_dir.mkdir(parents=True, exist_ok=True)
    settings.chroma_dir.mkdir(parents=True, exist_ok=True)
    return settings
