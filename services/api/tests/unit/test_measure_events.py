"""측정 이벤트 API (docs/30 `POST /measure/events`, ADR-027): 입력 검증·날짜 범위·식별자 없음.

DB는 가짜로 바꾼다. 실제 저장은 tests/integration/test_measure_api.py. 날짜는 가상 예시다.
"""

import inspect
from collections.abc import AsyncIterator, Iterator
from contextlib import asynccontextmanager
from datetime import date
from typing import Any

import pytest
from fastapi.testclient import TestClient

from app.core import db
from app.core.ratelimit import EVENT_LIMIT_PER_MINUTE, event_limiter
from app.main import app
from app.measure import router as measure_router
from app.measure import store
from app.measure.events import EVENTS, date_in_range

TODAY = date(2026, 11, 10)  # 가상 예시
URL = "/api/v1/measure/events"


class FakeEngine:
    def __init__(self) -> None:
        self.calls: list[tuple[date, str]] = []
        self.fail = False

    @asynccontextmanager
    async def begin(self) -> AsyncIterator[object]:
        if self.fail:
            raise RuntimeError("가상 DB 오류 2026-11-10")
        yield object()


@pytest.fixture
def engine(monkeypatch: pytest.MonkeyPatch) -> Iterator[FakeEngine]:
    fake = FakeEngine()

    async def increment(_: Any, day: date, event: str) -> None:
        fake.calls.append((day, event))

    monkeypatch.setattr(db, "get_engine", lambda: fake)
    monkeypatch.setattr(store, "increment", increment)
    app.dependency_overrides[measure_router.today_kst] = lambda: TODAY
    event_limiter.reset()
    yield fake
    app.dependency_overrides.clear()
    event_limiter.reset()


client = TestClient(app)


def test_event_names_match_docs() -> None:
    assert EVENTS == ("first_visit", "revisit_7d", "helpful_yes", "helpful_no")
    assert EVENT_LIMIT_PER_MINUTE == 120


@pytest.mark.parametrize(
    ("event", "day", "ok"),
    [
        ("first_visit", date(2026, 11, 9), True),
        ("first_visit", date(2026, 11, 11), True),
        ("first_visit", date(2026, 11, 8), False),
        ("first_visit", date(2026, 11, 12), False),
        ("helpful_no", date(2026, 11, 10), True),
        ("helpful_yes", date(2026, 11, 8), False),
        ("revisit_7d", date(2026, 11, 2), True),  # T−8
        ("revisit_7d", date(2026, 11, 1), False),  # T−9
        ("revisit_7d", date(2026, 11, 10), True),  # 시계 오차 여유
        ("revisit_7d", date(2026, 11, 11), False),
    ],
)
def test_date_range(event: Any, day: date, ok: bool) -> None:
    assert date_in_range(event, day, TODAY) is ok


def test_records_one_count_and_returns_204(engine: FakeEngine) -> None:
    response = client.post(URL, json={"event": "first_visit", "date": "2026-11-10"})
    assert response.status_code == 204
    assert response.content == b""
    assert response.headers["Cache-Control"] == "no-store"
    assert engine.calls == [(date(2026, 11, 10), "first_visit")]


@pytest.mark.parametrize(
    ("body", "fields"),
    [
        ({"event": "page_view", "date": "2026-11-10"}, {"event": "literal_error"}),
        ({"event": "first_visit"}, {"date": "missing"}),
        ({"event": "first_visit", "date": "11/10"}, {"date": "date_from_datetime_parsing"}),
        (
            {"event": "first_visit", "date": "2026-11-10", "visitor_id": "가상-ID-9182"},
            {"visitor_id": "extra_forbidden"},
        ),
        ({"event": "helpful_yes", "date": "2026-11-10", "pnu": "1"}, {"pnu": "extra_forbidden"}),
        ({"event": "first_visit", "date": "2026-10-01"}, {"date": "out_of_range"}),
    ],
)
def test_invalid_body_is_422_without_echo(
    engine: FakeEngine, body: dict[str, str], fields: dict[str, str]
) -> None:
    response = client.post(URL, json=body)
    assert response.status_code == 422
    assert response.json()["error"]["details"] == {"fields": fields}
    assert "9182" not in response.text
    assert engine.calls == []


def test_db_failure_is_503(engine: FakeEngine) -> None:
    engine.fail = True
    response = client.post(URL, json={"event": "helpful_no", "date": "2026-11-10"})
    assert response.status_code == 503
    assert response.json()["error"]["code"] == "SERVICE_UNAVAILABLE"


def test_rate_limited_after_120_per_minute(engine: FakeEngine) -> None:
    body = {"event": "helpful_yes", "date": "2026-11-10"}
    statuses = {client.post(URL, json=body).status_code for _ in range(EVENT_LIMIT_PER_MINUTE)}
    assert statuses == {204}
    response = client.post(URL, json=body)
    assert response.status_code == 429
    assert "Retry-After" in response.headers


def test_handler_does_not_read_request_or_headers() -> None:
    # User-Agent·IP를 읽을 길이 없다: 핸들러가 Request·헤더를 받지 않는다 (ADR-027 개정 2026-10-19)
    params = inspect.signature(measure_router.record_event).parameters
    assert set(params) == {"body", "response", "today"}
    source = inspect.getsource(measure_router)
    assert "request.headers" not in source and "Request" not in source.split("from fastapi")[1]
