"""Smoke tests — verify imports and basic FastAPI wiring."""

from __future__ import annotations

from fastapi.testclient import TestClient

from wiki_genres import __version__
from wiki_genres.api.main import app


def test_version_is_set() -> None:
    assert __version__


def test_healthz() -> None:
    client = TestClient(app)
    response = client.get("/healthz")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["version"] == __version__
