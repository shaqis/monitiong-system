from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi.testclient import TestClient

from app.main import app


def test_app_serves_openapi_document(monkeypatch, test_settings) -> None:
    seeded = []

    @asynccontextmanager
    async def fake_session() -> AsyncIterator[object]:
        yield object()

    async def fake_seed(session, settings) -> None:
        seeded.append(True)

    monkeypatch.setattr("app.main.SessionLocal", fake_session)
    monkeypatch.setattr("app.main.seed_first_admin", fake_seed)
    monkeypatch.setattr("app.main.get_settings", lambda: test_settings)

    with TestClient(app) as client:
        response = client.get("/openapi.json")

    assert response.status_code == 200
    assert seeded == [True]
