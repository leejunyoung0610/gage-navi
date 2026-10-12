"""GET /api/v1/health: DB 정상 200, DB 장애 503 SERVICE_UNAVAILABLE (docs/30 §1·2)."""

import asyncio
import re

import pytest
from fastapi.testclient import TestClient

from app.core import db
from app.main import app

client = TestClient(app)


def test_health_ok(monkeypatch: pytest.MonkeyPatch) -> None:
    async def ok() -> None:
        return None

    monkeypatch.setattr(db, "ping_db", ok)
    response = client.get("/api/v1/health")
    assert response.status_code == 200
    assert response.json() == {
        "status": "ok",
        "db": "ok",
        "location_snapshot": None,
        "approved_rules": None,
    }


@pytest.mark.parametrize(
    "error", [ConnectionRefusedError("refused"), TimeoutError(), RuntimeError("boom")]
)
def test_health_db_down(monkeypatch: pytest.MonkeyPatch, error: Exception) -> None:
    async def down() -> None:
        raise error

    monkeypatch.setattr(db, "ping_db", down)
    response = client.get("/api/v1/health")
    assert response.status_code == 503
    body = response.json()
    assert body["error"]["code"] == "SERVICE_UNAVAILABLE"
    assert body["error"]["details"] == {"db": "error"}
    assert re.fullmatch(r"[0-9A-HJKMNP-TV-Z]{26}", body["meta"]["request_id"])
    assert "refused" not in response.text and "boom" not in response.text


def test_health_without_database_url(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("DATABASE_URL", raising=False)
    db.get_engine.cache_clear()
    response = client.get("/api/v1/health")
    db.get_engine.cache_clear()
    assert response.status_code == 503
    assert response.json()["error"]["code"] == "SERVICE_UNAVAILABLE"


def test_ping_db_times_out(monkeypatch: pytest.MonkeyPatch) -> None:
    class HangingEngine:
        def connect(self) -> "HangingEngine":
            return self

        async def __aenter__(self) -> None:
            await asyncio.sleep(60)

        async def __aexit__(self, *args: object) -> None:
            return None

    monkeypatch.setattr(db, "PING_TIMEOUT_SECONDS", 0.05)
    monkeypatch.setattr(db, "get_engine", lambda: HangingEngine())
    with pytest.raises(TimeoutError):
        asyncio.run(db.ping_db())
