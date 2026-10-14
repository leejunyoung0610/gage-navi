"""요청 ID (docs/30 §1): 요청마다 한 번 만들어 응답 본문·`X-Request-ID`·로그에 같은 값을 쓴다."""

import logging

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.core.errors import ApiError, ErrorCode, register_error_handlers
from app.core.logging import configure_logging
from app.core.request_id import ACCESS_LOGGER, HEADER, current_request_id, log_request_id

configure_logging()


def _app() -> FastAPI:
    app = FastAPI()
    register_error_handlers(app)

    @app.get("/ok")
    async def ok() -> dict[str, dict[str, str]]:
        logging.getLogger("app.test").warning("가상 경고")
        return {"meta": {"request_id": current_request_id()}}

    @app.get("/missing")
    async def missing() -> None:
        raise ApiError(ErrorCode.NOT_FOUND, "가상 없음")

    @app.get("/boom")
    async def boom() -> None:
        raise RuntimeError("가상 실패")

    @app.get("/invalid")
    async def invalid(page: int) -> None:
        return None

    return app


client = TestClient(_app(), raise_server_exceptions=False)


def _records(caplog: pytest.LogCaptureFixture, name: str) -> list[logging.LogRecord]:
    return [r for r in caplog.records if r.name == name]


@pytest.mark.parametrize(
    ("path", "status"),
    [("/ok", 200), ("/missing", 404), ("/boom", 500), ("/invalid?page=x", 422)],
)
def test_same_id_in_body_header_and_logs(
    caplog: pytest.LogCaptureFixture, path: str, status: int
) -> None:
    with caplog.at_level(logging.INFO, logger="app"):
        response = client.get(path)
    assert response.status_code == status
    request_id = response.json()["meta"]["request_id"]
    assert len(request_id) == 26
    assert response.headers[HEADER] == request_id
    access = _records(caplog, ACCESS_LOGGER)
    assert len(access) == 1
    assert access[0].request_id == request_id  # type: ignore[attr-defined]
    message = access[0].getMessage()
    assert f"status={status}" in message and "latency_ms=" in message
    assert "?" not in message and "page=x" not in message  # 쿼리스트링은 남기지 않는다
    # 그 요청에서 남긴 다른 로그(경고·500)도 같은 ID
    others = [r for r in caplog.records if r.name.startswith("app") and r.name != ACCESS_LOGGER]
    assert all(r.request_id == request_id for r in others)  # type: ignore[attr-defined]
    if status in (200, 500):
        assert others


def test_each_request_gets_new_id_and_client_header_is_ignored() -> None:
    first = client.get("/ok", headers={HEADER: "client-chosen-id"})
    second = client.get("/ok")
    ids = {first.headers[HEADER], second.headers[HEADER]}
    assert len(ids) == 2 and "client-chosen-id" not in ids
    assert first.json()["meta"]["request_id"] == first.headers[HEADER]


def test_outside_request_logs_dash() -> None:
    assert log_request_id() == "-"
    assert len(current_request_id()) == 26
