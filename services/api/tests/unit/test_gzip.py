"""큰 응답만 gzip으로 압축한다 (T-022, docs/30 §1 "압축")."""

from fastapi.testclient import TestClient

from app.main import GZIP_MINIMUM_BYTES, app

client = TestClient(app)


def test_large_response_is_gzipped() -> None:
    response = client.get("/openapi.json", headers={"Accept-Encoding": "gzip"})
    assert response.status_code == 200
    assert response.headers["Content-Encoding"] == "gzip"
    assert len(response.content) >= GZIP_MINIMUM_BYTES  # 풀린 본문


def test_small_response_is_not_gzipped() -> None:
    response = client.get("/api/v1/places/123", headers={"Accept-Encoding": "gzip"})
    assert response.status_code == 422 and len(response.content) < GZIP_MINIMUM_BYTES
    assert "Content-Encoding" not in response.headers


def test_no_gzip_without_accept_encoding() -> None:
    response = client.get("/openapi.json", headers={"Accept-Encoding": "identity"})
    assert "Content-Encoding" not in response.headers
