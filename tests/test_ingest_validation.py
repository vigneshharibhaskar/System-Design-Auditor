from types import SimpleNamespace
from io import BytesIO

from fastapi.testclient import TestClient
from fastapi import UploadFile
from langchain_core.documents import Document

import app.ingest as ingest_module
import app.main as main_module
from app.main import app


def _build_client(monkeypatch, tmp_path):
    monkeypatch.setattr(main_module, "_ensure_openai_configured", lambda: None)
    monkeypatch.setattr(main_module.settings, "ingest_token", "token")
    monkeypatch.setattr(
        ingest_module,
        "get_settings",
        lambda: SimpleNamespace(
            uploads_dir=tmp_path,
            max_upload_bytes=1024,
            allowed_upload_content_types="application/pdf,application/octet-stream",
        ),
    )
    return TestClient(app)


def test_ingest_wrong_token_returns_401(monkeypatch, tmp_path):
    client = _build_client(monkeypatch, tmp_path)
    response = client.post(
        "/ingest?collection=default",
        headers={"x-ingest-token": "wrong"},
        files={"file": ("design.pdf", b"%PDF-1.4\\n", "application/pdf")},
    )
    assert response.status_code == 401
    body = response.json()
    assert body["error"]["code"] == "INGEST_AUTH_INVALID"


def test_ingest_non_pdf_returns_422(monkeypatch, tmp_path):
    client = _build_client(monkeypatch, tmp_path)
    response = client.post(
        "/ingest?collection=default",
        headers={"x-ingest-token": "token"},
        files={"file": ("not_pdf.pdf", b"hello world", "application/pdf")},
    )
    assert response.status_code == 422
    body = response.json()
    assert body["error"]["code"] == "INVALID_PDF"


def test_ingest_too_large_returns_413(monkeypatch, tmp_path):
    client = _build_client(monkeypatch, tmp_path)
    payload = b"%PDF-1.4\\n" + (b"a" * 2000)
    response = client.post(
        "/ingest?collection=default",
        headers={"x-ingest-token": "token"},
        files={"file": ("large.pdf", payload, "application/pdf")},
    )
    assert response.status_code == 413
    body = response.json()
    assert body["error"]["code"] == "UPLOAD_TOO_LARGE"


def test_ingest_same_filename_creates_unique_stored_paths(monkeypatch, tmp_path):
    stored_metadatas = []

    class _FakeLoader:
        def __init__(self, _path: str):
            self.path = _path

        def load(self):
            return [Document(page_content="A sample page", metadata={"page": 0})]

    class _FakeStore:
        def add_documents(self, docs, ids):
            _ = ids
            stored_metadatas.extend([doc.metadata for doc in docs])

    monkeypatch.setattr(
        ingest_module,
        "get_settings",
        lambda: SimpleNamespace(
            uploads_dir=tmp_path,
            max_upload_bytes=5 * 1024 * 1024,
            allowed_upload_content_types="application/pdf,application/octet-stream",
        ),
    )
    monkeypatch.setattr(ingest_module, "PyPDFLoader", _FakeLoader)
    monkeypatch.setattr(ingest_module, "get_vectorstore", lambda *_args, **_kwargs: _FakeStore())

    file_a = UploadFile(filename="design.pdf", file=BytesIO(b"%PDF-1.4\\nfirst"), headers={"content-type": "application/pdf"})
    file_b = UploadFile(filename="design.pdf", file=BytesIO(b"%PDF-1.4\\nsecond"), headers={"content-type": "application/pdf"})

    result_a = ingest_module.ingest_pdf(file_a, "default")
    result_b = ingest_module.ingest_pdf(file_b, "default")

    assert result_a["source_file"] != result_b["source_file"]
    assert result_a["original_name"] == "design.pdf"
    assert result_b["original_name"] == "design.pdf"
    assert (tmp_path / result_a["source_file"]).exists()
    assert (tmp_path / result_b["source_file"]).exists()
    assert all(meta.get("original_name") == "design.pdf" for meta in stored_metadatas)
