from __future__ import annotations

import uuid
import re
from collections import Counter
from pathlib import Path

from fastapi import UploadFile
from langchain_community.document_loaders import PyPDFLoader
from langchain_core.documents import Document
from langchain_text_splitters import RecursiveCharacterTextSplitter

from app.config import get_settings
from app.errors import InvalidPDFError, PayloadValidationError, UploadTooLargeError
from app.store import get_vectorstore

CHUNK_SIZE_BYTES = 1024 * 1024
PDF_MAGIC = b"%PDF-"


def _stable_chunk_id(source_file: str, page: int, chunk_text: str) -> str:
    payload = f"{source_file}|{page}|{chunk_text.strip()}"
    return str(uuid.uuid5(uuid.NAMESPACE_URL, payload))


def _split_documents(docs: list[Document]) -> list[Document]:
    splitter = RecursiveCharacterTextSplitter(
        chunk_size=800,
        chunk_overlap=120,
        separators=["\n\n", "\n", " ", ""],
    )
    return splitter.split_documents(docs)


def _allowed_content_types(raw_value: str) -> set[str]:
    return {value.strip().lower() for value in raw_value.split(",") if value.strip()}


def _safe_filename(name: str) -> str:
    raw = Path(name).name
    sanitized = re.sub(r"[^A-Za-z0-9._-]+", "_", raw).strip("._")
    if not sanitized:
        sanitized = "upload.pdf"
    if "." not in sanitized:
        sanitized = f"{sanitized}.pdf"
    return sanitized[:160]


def _build_unique_paths(uploads_dir: Path, original_name: str) -> tuple[Path, Path]:
    uid = str(uuid.uuid4())
    safe_name = _safe_filename(original_name)
    final_path = uploads_dir / f"{uid}_{safe_name}"
    tmp_path = uploads_dir / f".{uid}.upload.tmp"
    return tmp_path, final_path


def _stream_upload_to_disk(upload_file: UploadFile, destination: Path, max_upload_bytes: int) -> bytes:
    total_bytes = 0
    header = bytearray()
    with destination.open("wb") as out_file:
        while True:
            chunk = upload_file.file.read(CHUNK_SIZE_BYTES)
            if not chunk:
                break
            total_bytes += len(chunk)
            if total_bytes > max_upload_bytes:
                raise UploadTooLargeError(f"Upload exceeds MAX_UPLOAD_BYTES ({max_upload_bytes} bytes)")
            if len(header) < len(PDF_MAGIC):
                remaining = len(PDF_MAGIC) - len(header)
                header.extend(chunk[:remaining])
            out_file.write(chunk)
    return bytes(header)


def ingest_pdf(upload_file: UploadFile, collection: str) -> dict:
    settings = get_settings()
    if not upload_file.filename:
        raise PayloadValidationError("Uploaded file must include a filename")
    original_name = Path(upload_file.filename).name

    content_type = (upload_file.content_type or "").lower()
    allowed_types = _allowed_content_types(settings.allowed_upload_content_types)
    if content_type not in allowed_types:
        raise PayloadValidationError(f"Unsupported content type: {content_type or 'missing'}")

    tmp_path, destination = _build_unique_paths(settings.uploads_dir, original_name)
    try:
        header = _stream_upload_to_disk(
            upload_file=upload_file,
            destination=tmp_path,
            max_upload_bytes=settings.max_upload_bytes,
        )
    except Exception:
        tmp_path.unlink(missing_ok=True)
        raise

    if not header.startswith(PDF_MAGIC):
        tmp_path.unlink(missing_ok=True)
        raise InvalidPDFError("Uploaded file is not a valid PDF (missing %PDF- header)")

    try:
        loader = PyPDFLoader(str(tmp_path))
        loaded_docs = loader.load()
    except Exception as exc:
        tmp_path.unlink(missing_ok=True)
        raise InvalidPDFError("Uploaded file is not a valid or readable PDF") from exc

    if not loaded_docs:
        tmp_path.unlink(missing_ok=True)
        raise InvalidPDFError("Uploaded PDF has no readable pages")

    try:
        # Atomic move into final location after validation succeeds.
        tmp_path.replace(destination)
    except Exception:
        tmp_path.unlink(missing_ok=True)
        destination.unlink(missing_ok=True)
        raise

    for doc in loaded_docs:
        doc.metadata = {
            **doc.metadata,
            "source_file": destination.name,
            "original_name": original_name,
            "page": int(doc.metadata.get("page", 0)),
        }

    split_docs = _split_documents(loaded_docs)

    ids: list[str] = []
    for doc in split_docs:
        source_file = doc.metadata.get("source_file", destination.name)
        page = int(doc.metadata.get("page", 0))
        ids.append(_stable_chunk_id(source_file, page, doc.page_content))

    vectorstore = get_vectorstore(collection, require_embeddings=True)
    vectorstore.add_documents(split_docs, ids=ids)

    chunk_count_by_file = Counter(doc.metadata.get("source_file", "unknown") for doc in split_docs)

    return {
        "collection": collection,
        "source_file": destination.name,
        "original_name": original_name,
        "pages": len(loaded_docs),
        "chunks": len(split_docs),
        "chunk_count_by_file": dict(chunk_count_by_file),
    }


def list_ingested_files(collection: str, limit: int, offset: int) -> dict:
    vectorstore = get_vectorstore(collection, require_embeddings=False)
    raw = vectorstore.get(include=["metadatas"], limit=limit, offset=offset)
    metadatas = raw.get("metadatas", []) or []

    items: list[dict] = []
    for metadata in metadatas:
        if not metadata:
            continue
        items.append(
            {
                "source_file": metadata.get("source_file", "unknown"),
                "original_name": metadata.get("original_name"),
                "page": int(metadata.get("page", 0)),
            }
        )

    return {"collection": collection, "items": items, "limit": limit, "offset": offset}
