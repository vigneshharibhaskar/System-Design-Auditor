from app.config import Settings


def test_ingest_token_defaults_to_none(monkeypatch):
    monkeypatch.delenv("INGEST_TOKEN", raising=False)
    settings = Settings()
    assert settings.ingest_token is None
