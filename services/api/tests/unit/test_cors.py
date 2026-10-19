"""CORS — `CORS_ALLOWED_ORIGINS`의 출처만, GET만 (docs/30 §1, T-032). 출처는 가상 예시다."""

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.core.config import get_settings, parse_origins
from app.core.cors import add_cors

ALLOWED = "http://web.example.test"  # 가상 예시
OTHER = "http://other.example.test"


def make_client(origins: tuple[str, ...]) -> TestClient:
    app = FastAPI()

    @app.get("/api/v1/ping")
    def ping() -> dict[str, str]:
        return {"ok": "yes"}

    add_cors(app, origins)
    return TestClient(app)


def preflight(client: TestClient, origin: str, method: str = "GET") -> dict[str, str]:
    response = client.options(
        "/api/v1/ping",
        headers={"Origin": origin, "Access-Control-Request-Method": method},
    )
    return dict(response.headers)


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        (None, ()),
        ("", ()),
        (" , ", ()),
        (ALLOWED, (ALLOWED,)),
        (f" {ALLOWED} , {OTHER}/ ", (ALLOWED, OTHER)),  # 공백·끝의 / 정리
    ],
)
def test_parse_origins(raw: str | None, expected: tuple[str, ...]) -> None:
    assert parse_origins(raw) == expected


def test_settings_reads_origins(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CORS_ALLOWED_ORIGINS", f"{ALLOWED},{OTHER}")
    assert get_settings().cors_allowed_origins == (ALLOWED, OTHER)
    monkeypatch.delenv("CORS_ALLOWED_ORIGINS")
    assert get_settings().cors_allowed_origins == ()


def test_allowed_origin_gets_header() -> None:
    client = make_client((ALLOWED,))
    response = client.get("/api/v1/ping", headers={"Origin": ALLOWED})
    assert response.headers["access-control-allow-origin"] == ALLOWED
    assert "access-control-allow-credentials" not in response.headers
    assert preflight(client, ALLOWED)["access-control-allow-origin"] == ALLOWED


def test_other_origin_gets_no_header() -> None:
    client = make_client((ALLOWED,))
    response = client.get("/api/v1/ping", headers={"Origin": OTHER})
    assert "access-control-allow-origin" not in response.headers
    assert "access-control-allow-origin" not in preflight(client, OTHER)


def test_no_origins_allows_nothing() -> None:
    client = make_client(())
    response = client.get("/api/v1/ping", headers={"Origin": ALLOWED})
    assert "access-control-allow-origin" not in response.headers
    assert "access-control-allow-origin" not in preflight(client, ALLOWED)


def test_only_get_is_allowed() -> None:
    client = make_client((ALLOWED,))
    response = client.options(
        "/api/v1/ping",
        headers={"Origin": ALLOWED, "Access-Control-Request-Method": "POST"},
    )
    assert response.status_code == 400  # 사전 요청 거절 — 브라우저가 POST를 보내지 않는다
    assert response.headers["access-control-allow-methods"] == "GET"
