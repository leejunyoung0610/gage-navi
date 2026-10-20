"""접속 로그에 쿼리스트링(검색어)과 클라이언트 IP를 남기지 않는다 (docs/01 §6, docs/60 §5)."""

import logging
from collections.abc import AsyncIterator, Iterator
from contextlib import asynccontextmanager
from datetime import date
from typing import Any

import pytest
from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient

from app.core import db
from app.core.errors import register_error_handlers
from app.core.logging import (
    ACCESS_LOGGER,
    HideClientFilter,
    StripQueryFilter,
    configure_logging,
)
from app.core.ratelimit import EVENT_LIMIT_PER_MINUTE, event_limiter, limit_event, lookup_limiter
from app.main import app
from app.measure import router as measure_router
from app.measure import store

CLIENT_IP = "203.0.113.77"  # 문서용 IP 대역(RFC 5737), 가상 예시
CLIENT = (CLIENT_IP, 50123)
UA_MARKER = "VirtualBrowserMarker/9.9"  # 가상 예시


def access_record(path: str) -> logging.LogRecord:
    # uvicorn 접속 로그와 같은 형식·인자
    return logging.LogRecord(
        ACCESS_LOGGER, logging.INFO, __file__, 1,
        '%s - "%s %s HTTP/%s" %d', ("127.0.0.1:5000", "GET", path, "1.1", 200), None,
    )  # fmt: skip


def test_query_string_is_stripped() -> None:
    record = access_record("/api/v1/address/search?q=%EA%B0%80%EC%83%81%EB%A1%9C&page=1")
    assert StripQueryFilter().filter(record)
    assert record.getMessage() == '127.0.0.1:5000 - "GET /api/v1/address/search HTTP/1.1" 200'


def test_path_without_query_is_unchanged() -> None:
    record = access_record("/api/v1/health")
    StripQueryFilter().filter(record)
    assert record.getMessage() == '127.0.0.1:5000 - "GET /api/v1/health HTTP/1.1" 200'


def test_filters_are_installed_once_on_access_logger() -> None:
    configure_logging()
    configure_logging()
    filters = logging.getLogger(ACCESS_LOGGER).filters
    assert len([f for f in filters if isinstance(f, StripQueryFilter)]) == 1
    assert len([f for f in filters if isinstance(f, HideClientFilter)]) == 1


@pytest.mark.parametrize("status", [200, 204, 404, 422, 429, 500, 503])
def test_uvicorn_access_log_has_no_client_ip(status: int) -> None:
    # uvicorn 접속 로그와 같은 인자를 접속 로거의 필터에 통과시킨다
    configure_logging()
    record = logging.LogRecord(
        ACCESS_LOGGER, logging.INFO, __file__, 1, '%s - "%s %s HTTP/%s" %d',
        (f"{CLIENT_IP}:50123", "POST", "/api/v1/measure/events?x=1", "1.1", status), None,
    )  # fmt: skip
    assert logging.getLogger(ACCESS_LOGGER).filter(record)
    assert record.getMessage() == f'- - "POST /api/v1/measure/events HTTP/1.1" {status}'


class FakeEngine:
    fail = False

    @asynccontextmanager
    async def begin(self) -> AsyncIterator[object]:
        if self.fail:
            raise RuntimeError(f"가상 DB 오류 {CLIENT_IP}")
        yield object()


@pytest.fixture
def fake_engine(monkeypatch: pytest.MonkeyPatch) -> Iterator[FakeEngine]:
    engine = FakeEngine()

    async def increment(_: Any, day: date, event: str) -> None:
        return None

    monkeypatch.setattr(db, "get_engine", lambda: engine)
    monkeypatch.setattr(store, "increment", increment)
    app.dependency_overrides[measure_router.today_kst] = lambda: date(2026, 11, 10)
    event_limiter.reset()
    lookup_limiter.reset()
    yield engine
    app.dependency_overrides.clear()
    event_limiter.reset()
    lookup_limiter.reset()


def _boom_app() -> FastAPI:
    boom = FastAPI()
    register_error_handlers(boom)

    @boom.get("/boom", dependencies=[Depends(limit_event)])
    async def fail() -> None:
        raise RuntimeError(f"가상 실패 {CLIENT_IP}")

    @boom.get("/ok", dependencies=[Depends(limit_event)])
    async def ok() -> dict[str, str]:
        logging.getLogger("app.test").info("가상 처리")
        return {"status": "ok"}

    return boom


def _assert_no_ip(caplog: pytest.LogCaptureFixture) -> None:
    assert caplog.records  # 로그는 남는다 (접속 로그 등)
    for record in caplog.records:
        text = f"{record.getMessage()} {record.args!r} {record.__dict__!r}"
        assert CLIENT_IP not in text, record.name
        assert UA_MARKER not in text, record.name


def test_no_log_has_client_ip_for_any_status(
    caplog: pytest.LogCaptureFixture, fake_engine: FakeEngine
) -> None:
    configure_logging()
    headers = {"User-Agent": UA_MARKER}
    client = TestClient(app, client=CLIENT, raise_server_exceptions=False)
    boom = TestClient(_boom_app(), client=CLIENT, raise_server_exceptions=False)
    url = "/api/v1/measure/events"
    ok = {"event": "first_visit", "date": "2026-11-10"}
    with caplog.at_level(logging.DEBUG):
        statuses = [
            client.get("/api/v1/places/12345", headers=headers).status_code,  # 422 (형식)
            client.post(url, json=ok, headers=headers).status_code,  # 204
            client.post(url, json={"event": "x"}, headers=headers).status_code,  # 422
        ]
        for _ in range(EVENT_LIMIT_PER_MINUTE):
            client.post(url, json=ok, headers=headers)
        statuses.append(client.post(url, json=ok, headers=headers).status_code)  # 429
        event_limiter.reset()
        fake_engine.fail = True
        statuses.append(client.post(url, json=ok, headers=headers).status_code)  # 503
        event_limiter.reset()
        statuses.append(boom.get("/boom", headers=headers).status_code)  # 500
        statuses.append(boom.get("/ok", headers=headers).status_code)  # 200
    assert statuses == [422, 204, 422, 429, 503, 500, 200]
    _assert_no_ip(caplog)
