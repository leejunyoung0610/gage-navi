"""GET /api/v1/stats/model-card 응답 형식 (T-034, docs/30). DB는 부르지 않는다.

값은 모두 가상 예시다.
"""

from datetime import date
from typing import Any

import pytest
from fastapi.testclient import TestClient

from app.address.search_match import MATCH, NO_RESULT, SEED, Outcome, summarize
from app.location.stats import router as stats_router
from app.location.stats.card import compute
from app.main import app
from tests.unit.test_search_match import RECORD
from tests.unit.test_stats_model import AS_OF, SIGUNGU, synthetic

URL = "/api/v1/stats/model-card"


@pytest.fixture(scope="module")
def card_payload() -> dict[str, Any]:
    card = compute(synthetic(seed=3, effect=0.10, floors=400), AS_OF, SIGUNGU).card
    return card.model_dump(mode="json", by_alias=True)


@pytest.fixture(scope="module")
def match_payload() -> dict[str, Any]:
    outcomes = [Outcome(RECORD, MATCH)] * 3 + [Outcome(RECORD, NO_RESULT)]
    payload = summarize(
        outcomes, measured_on=date(2026, 10, 14), seed=SEED, remeasure=False, population=4
    )
    return payload.model_dump(mode="json")


def _client(monkeypatch: pytest.MonkeyPatch, card: Any, match: Any) -> TestClient:
    async def read() -> tuple[Any, Any]:
        return card, match

    monkeypatch.setattr(stats_router, "_read", read)
    return TestClient(app)


def test_returns_card_and_search_match(
    monkeypatch: pytest.MonkeyPatch, card_payload: dict[str, Any], match_payload: dict[str, Any]
) -> None:
    client = _client(monkeypatch, ("2026.10.1", card_payload), match_payload)
    response = client.get(URL)
    assert response.status_code == 200
    assert response.headers["cache-control"] == "public, max-age=300"
    body = response.json()
    assert set(body) == {"data", "meta"} and body["meta"]["request_id"]
    data = body["data"]
    assert data["method_version"] == "2026.10.1"
    assert data["model_card"] == card_payload  # 저장된 payload 그대로 (docs/10 §7.3)
    assert "or" in data["model_card"]["by_sigungu"][0]  # 별칭 그대로
    assert data["model_card"]["out_of_time"]["auc_with_prior"] > 0
    assert data["search_match"] == match_payload
    assert data["search_match"]["judged"] == {
        "matched": 3,
        "rate": "0.7500",
        "ci": data["search_match"]["judged"]["ci"],
    }


def test_nulls_when_nothing_computed(monkeypatch: pytest.MonkeyPatch) -> None:
    response = _client(monkeypatch, None, None).get(URL)
    assert response.status_code == 200
    assert response.json()["data"] == {
        "method_version": None,
        "model_card": None,
        "search_match": None,
    }


def test_invalid_stored_payload_is_503(
    monkeypatch: pytest.MonkeyPatch, match_payload: dict[str, Any]
) -> None:
    response = _client(monkeypatch, ("2026.10.1", {"data": {}}), match_payload).get(URL)
    assert response.status_code == 503
    assert response.json()["error"]["code"] == "SERVICE_UNAVAILABLE"


def test_db_error_is_503(monkeypatch: pytest.MonkeyPatch) -> None:
    async def broken() -> tuple[Any, Any]:
        raise OSError("가상 연결 오류")

    monkeypatch.setattr(stats_router, "_read", broken)
    response = TestClient(app).get(URL)
    assert response.status_code == 503
