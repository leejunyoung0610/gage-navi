"""방법론 페이지 데이터: 저장(`render_search_match --save`)과 조회(`/stats/model-card`).

T-034.

카드·측정 값은 모두 가상 예시다. 고르는 행과 덮어쓰기만 본다.
"""

import asyncio
import json
from collections.abc import Iterator
from datetime import date
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.pool import NullPool

from app.address.search_match import MATCH, NO_RESULT, Outcome, summarize
from app.location.stats import router as stats_router
from app.location.stats.card import compute
from app.main import app
from jobs.render_search_match import save
from tests.unit.test_search_match import RECORD
from tests.unit.test_stats_model import AS_OF, SIGUNGU, synthetic

URL = "/api/v1/stats/model-card"


def _card(snapshot_label: str) -> str:
    card = compute(synthetic(seed=5, effect=0.10, floors=300), AS_OF, SIGUNGU).card
    payload = card.model_dump(mode="json", by_alias=True)
    payload["data"]["snapshot_label"] = snapshot_label
    return json.dumps(payload)


def _match(seed: int, measured_on: date, matches: int) -> Any:
    outcomes = [Outcome(RECORD, MATCH)] * matches + [Outcome(RECORD, NO_RESULT)]
    return summarize(outcomes, measured_on=measured_on, seed=seed, remeasure=False, population=9)


def _execute(url: str, statements: list[tuple[str, dict[str, Any]]]) -> None:
    async def go() -> None:
        engine = create_async_engine(url, poolclass=NullPool)
        try:
            async with engine.begin() as conn:
                for statement, params in statements:
                    await conn.execute(text(statement), params)
        finally:
            await engine.dispose()

    asyncio.run(go())


def _save(url: str, payload: Any) -> None:
    async def go() -> None:
        engine = create_async_engine(url, poolclass=NullPool)
        try:
            await save(engine, payload)
        finally:
            await engine.dispose()

    asyncio.run(go())


@pytest.fixture
def client(migrated_db_url: str, monkeypatch: pytest.MonkeyPatch) -> Iterator[TestClient]:
    engine = create_async_engine(migrated_db_url, poolclass=NullPool)
    monkeypatch.setattr(stats_router, "get_engine", lambda: engine)
    with TestClient(app) as test_client:
        yield test_client


def test_empty_tables_give_nulls(migrated_db_url: str, client: TestClient) -> None:
    _execute(migrated_db_url, [("TRUNCATE model_card, search_match_result", {})])
    data = client.get(URL).json()["data"]
    assert data == {"method_version": None, "model_card": None, "search_match": None}


def test_latest_non_w0_card_and_latest_search_match(
    migrated_db_url: str, client: TestClient
) -> None:
    insert = (
        "INSERT INTO model_card (snapshot_label, method_version, payload) "
        "VALUES (:label, :method, CAST(:payload AS JSONB))"
    )
    _execute(
        migrated_db_url,
        [
            ("TRUNCATE model_card, search_match_result", {}),
            (insert, {"label": "2026-09", "method": "2026.10.1", "payload": _card("2026-09")}),
            (insert, {"label": "2026-10", "method": "2026.10.1", "payload": _card("2026-10")}),
            # W0 재현 카드는 더 최근이어도 쓰지 않는다
            (insert, {"label": "2026-10", "method": "w0", "payload": "{}"}),
        ],
    )
    _save(migrated_db_url, _match(20261013, date(2026, 10, 14), matches=3))
    _save(migrated_db_url, _match(20261014, date(2026, 10, 20), matches=1))

    data = client.get(URL).json()["data"]
    assert data["method_version"] == "2026.10.1"
    assert data["model_card"]["data"]["snapshot_label"] == "2026-10"
    assert data["search_match"]["seed"] == 20261014
    assert data["search_match"]["judged"]["rate"] == "0.5000"


def test_save_overwrites_same_seed(migrated_db_url: str) -> None:
    _execute(migrated_db_url, [("TRUNCATE search_match_result", {})])
    _save(migrated_db_url, _match(20261013, date(2026, 10, 13), matches=1))
    _save(migrated_db_url, _match(20261013, date(2026, 10, 14), matches=3))

    async def rows() -> list[Any]:
        engine = create_async_engine(migrated_db_url, poolclass=NullPool)
        try:
            async with engine.connect() as conn:
                query = (
                    "SELECT seed, measured_on, payload -> 'judged' ->> 'rate' "
                    "FROM search_match_result"
                )
                return list((await conn.execute(text(query))).all())
        finally:
            await engine.dispose()

    assert asyncio.run(rows()) == [(20261013, date(2026, 10, 14), "0.7500")]
