from __future__ import annotations

from langchain_chroma import Chroma
from langchain_openai import OpenAIEmbeddings

from app.config import get_settings


def get_embeddings() -> OpenAIEmbeddings:
    settings = get_settings()
    if not settings.openai_api_key:
        raise ValueError("OPENAI_API_KEY is required for embedding operations")
    return OpenAIEmbeddings(model=settings.embedding_model, api_key=settings.openai_api_key)


def get_vectorstore(collection: str, require_embeddings: bool = True) -> Chroma:
    settings = get_settings()
    embedding_fn = get_embeddings() if require_embeddings else None
    return Chroma(
        collection_name=collection,
        embedding_function=embedding_fn,
        persist_directory=str(settings.chroma_dir),
    )
