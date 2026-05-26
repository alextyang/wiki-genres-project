"""Smoke tests — verify imports and basic FastAPI wiring."""

from __future__ import annotations

from fastapi.testclient import TestClient

from wiki_genres import __version__
from wiki_genres.api.main import app
from wiki_genres.config import get_settings


def test_version_is_set() -> None:
    assert __version__


def test_healthz() -> None:
    client = TestClient(app)
    response = client.get("/healthz")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["version"] == __version__


def test_root_redirects_to_explorer() -> None:
    client = TestClient(app, follow_redirects=False)
    response = client.get("/")
    assert response.status_code == 307
    assert response.headers["location"] == "/explorer/"


def test_feedback_requires_webhook(monkeypatch) -> None:
    monkeypatch.delenv("FEEDBACK_WEBHOOK_URL", raising=False)
    get_settings.cache_clear()
    client = TestClient(app)
    response = client.post(
        "/v1/feedback",
        json={
            "report_type": "Relationship data",
            "genre_name": "Jazz",
            "page_url": "http://testserver/explorer/",
        },
    )
    assert response.status_code == 503
    get_settings.cache_clear()
