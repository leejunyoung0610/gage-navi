"""측정 이벤트 저장 (T-104, docs/04 `measure_daily_count`, docs/30 `POST /measure/events`).

- 마이그레이션 0009 왕복, 저장 형태에 식별자·IP·User-Agent·시각 열이 없다
- 이벤트는 (날짜, 이벤트) 합계로만 쌓이고, `jobs.measure_demand`가 그 합계로 측정값을 낸다
날짜는 가상 예시다.
"""

import asyncio
from collections.abc import Callable, Iterator
from datetime import date
from typing import Any

import pytest
from alembic.config import Config
from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.pool import NullPool

from alembic import command
from app.core import db
from app.core.ratelimit import event_limiter
from app.main import app
from app.measure import router as measure_router
from app.measure import store
from jobs.measure_demand import build

TODAY = date(2026, 11, 10)  # 가상 예시
COLUMNS = """
    SELECT column_name FROM information_schema.columns
    WHERE table_schema = 'public' AND table_name = 'measure_daily_count'
    ORDER BY ordinal_position
"""


def _fetch(url: str, statement: str) -> list[Any]:
    async def run() -> list[Any]:
        engine = create_async_engine(url, poolclass=NullPool)
        try:
            async with engine.connect() as conn:
                return list((await conn.execute(text(statement))).all())
        finally:
            await engine.dispose()

    return asyncio.run(run())


def test_migration_roundtrip_and_columns(
    empty_db_url: str, make_alembic_config: Callable[[str], Config]
) -> None:
    config = make_alembic_config(empty_db_url)
    command.upgrade(config, "head")
    columns = [row[0] for row in _fetch(empty_db_url, COLUMNS)]
    assert columns == ["day", "event", "count"]
    command.downgrade(config, "0008_search_match")
    assert _fetch(empty_db_url, COLUMNS) == []
    command.upgrade(config, "head")
    assert len(_fetch(empty_db_url, COLUMNS)) == 3


@pytest.fixture
def client(migrated_db_url: str, monkeypatch: pytest.MonkeyPatch) -> Iterator[TestClient]:
    engine = create_async_engine(migrated_db_url, poolclass=NullPool)
    monkeypatch.setattr(db, "get_engine", lambda: engine)
    asyncio.run(_execute(migrated_db_url, "TRUNCATE measure_daily_count"))
    app.dependency_overrides[measure_router.today_kst] = lambda: TODAY
    event_limiter.reset()
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()
    event_limiter.reset()


async def _execute(url: str, statement: str) -> None:
    engine = create_async_engine(url, poolclass=NullPool)
    try:
        async with engine.begin() as conn:
            await conn.execute(text(statement))
    finally:
        await engine.dispose()


def test_events_accumulate_as_daily_counts(client: TestClient, migrated_db_url: str) -> None:
    sent = [
        ("first_visit", "2026-11-10"),
        ("first_visit", "2026-11-10"),
        ("first_visit", "2026-11-09"),
        ("revisit_7d", "2026-11-03"),
        ("helpful_yes", "2026-11-10"),
        ("helpful_no", "2026-11-10"),
        ("helpful_yes", "2026-11-10"),
    ]
    for event, day in sent:
        response = client.post("/api/v1/measure/events", json={"event": event, "date": day})
        assert response.status_code == 204, response.text
    rows = _fetch(
        migrated_db_url, "SELECT day, event, count FROM measure_daily_count ORDER BY 1, 2"
    )
    assert rows == [
        (date(2026, 11, 3), "revisit_7d", 1),
        (date(2026, 11, 9), "first_visit", 1),
        (date(2026, 11, 10), "first_visit", 2),
        (date(2026, 11, 10), "helpful_no", 1),
        (date(2026, 11, 10), "helpful_yes", 2),
    ]

    async def load() -> dict[tuple[date, str], int]:
        engine = create_async_engine(migrated_db_url, poolclass=NullPool)
        try:
            async with engine.connect() as conn:
                return await store.counts_between(conn, date(2026, 11, 1), date(2026, 11, 28))
        finally:
            await engine.dispose()

    report = build(asyncio.run(load()), date(2026, 11, 1), 28, None, daily_only=False)
    assert report["unique_visitors"] == 3
    assert report["revisit"] == {"numerator": 1, "denominator": 3, "rate": "0.3333"}
    assert (report["helpful_yes"], report["helpful_no"]) == (2, 1)
    daily = build(asyncio.run(load()), date(2026, 11, 9), 28, date(2026, 11, 10), daily_only=True)
    assert [row["first_visit"] for row in daily["daily"]] == [1, 2]
