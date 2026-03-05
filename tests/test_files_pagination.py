from fastapi.testclient import TestClient

import app.main as main_module
from app.main import app


def test_files_pagination_uses_limit_and_offset(monkeypatch):
    captured = {}

    def _fake_list_ingested_files(collection: str, limit: int, offset: int):
        captured["collection"] = collection
        captured["limit"] = limit
        captured["offset"] = offset
        return {
            "collection": collection,
            "items": [{"source_file": "a.pdf", "original_name": "orig.pdf", "page": 0}],
            "limit": limit,
            "offset": offset,
        }

    monkeypatch.setattr(main_module, "list_ingested_files", _fake_list_ingested_files)
    client = TestClient(app)

    response = client.get("/files", params={"collection": "default", "limit": 10, "offset": 5})
    assert response.status_code == 200
    body = response.json()

    assert body["ok"] is True
    assert "request_id" in body
    assert body["limit"] == 10
    assert body["offset"] == 5
    assert body["items"] == [{"source_file": "a.pdf", "original_name": "orig.pdf", "page": 0}]
    assert body["files"] == body["items"]
    assert captured == {"collection": "default", "limit": 10, "offset": 5}


def test_files_limit_is_capped_to_max(monkeypatch):
    monkeypatch.setattr(main_module.settings, "files_max_limit", 25)

    captured = {}

    def _fake_list_ingested_files(collection: str, limit: int, offset: int):
        captured["limit"] = limit
        captured["offset"] = offset
        return {"collection": collection, "items": [], "limit": limit, "offset": offset}

    monkeypatch.setattr(main_module, "list_ingested_files", _fake_list_ingested_files)
    client = TestClient(app)

    response = client.get("/files", params={"limit": 999, "offset": 0})
    assert response.status_code == 200
    body = response.json()
    assert body["limit"] == 25
    assert captured["limit"] == 25
    assert captured["offset"] == 0
