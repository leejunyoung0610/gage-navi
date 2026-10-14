"""GET /api/v1/address/search (docs/30 §2). 주소·필지·승인키는 모두 가상 예시다."""

import logging
import re
from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient

from app.address import router as address_router
from app.address.juso import (
    JusoItem,
    JusoKeywordError,
    JusoPage,
    JusoUnavailableError,
    RelatedLot,
)
from app.core import db
from app.core.ratelimit import LOOKUP_LIMIT_PER_MINUTE, lookup_limiter
from app.main import app

client = TestClient(app)

URL = "/api/v1/address/search"
QUERY = "가상로 12"
WITH_HISTORY = "1121510700100470001"
WITHOUT_HISTORY = "1121510700100480000"
PAGE = JusoPage(
    items=(
        JusoItem("가상시 가상구 가상로 12", "가상시 가상구 가상동 47-1", "가상빌딩", WITH_HISTORY),
        JusoItem("가상시 가상구 가상로 14", "가상시 가상구 가상동 48", None, WITHOUT_HISTORY),
        JusoItem("가상시 가상구 가상로 16", "가상시 가상구 가상동", None, None),
    ),
    page=1,
    total=3,
)

# 가상 예시: 법정동 이름 → 코드
DONG_ROWS = [
    ("1121510700", "가상시 가상구 가상동", False),
    ("1121510800", "가상시 가상구 다른동", False),
    ("1121510900", "가상시 가상구 옛동", True),
]


class FakeJuso:
    def __init__(self, result: JusoPage | Exception = PAGE) -> None:
        self.result = result
        self.calls: list[tuple[str, int]] = []

    async def search(self, keyword: str, page: int) -> JusoPage:
        self.calls.append((keyword, page))
        if isinstance(self.result, Exception):
            raise self.result
        return self.result


@pytest.fixture
def juso(monkeypatch: pytest.MonkeyPatch) -> Iterator[FakeJuso]:
    fake = FakeJuso()

    async def existing(pnus: list[str]) -> set[str]:
        return {WITH_HISTORY} & set(pnus)

    async def dong_rows(names: list[str]) -> list[tuple[str, str, bool]]:
        return [row for row in DONG_ROWS if row[1] in names]

    monkeypatch.setattr(db, "existing_parcels", existing)
    monkeypatch.setattr(db, "legal_dong_rows", dong_rows)
    app.dependency_overrides[address_router.get_juso_client] = lambda: fake
    address_router.search_cache.clear()
    lookup_limiter.reset()
    yield fake
    app.dependency_overrides.clear()
    address_router.search_cache.clear()
    lookup_limiter.reset()


def test_search_returns_items_with_history_flag(juso: FakeJuso) -> None:
    response = client.get(URL, params={"q": QUERY})
    assert response.status_code == 200
    body = response.json()
    assert body["data"] == {
        "items": [
            {
                "road_addr": "가상시 가상구 가상로 12",
                "jibun_addr": "가상시 가상구 가상동 47-1",
                "building_name": "가상빌딩",
                "pnu": WITH_HISTORY,
                "has_history": True,
                "related_pnus": [],
            },
            {
                "road_addr": "가상시 가상구 가상로 14",
                "jibun_addr": "가상시 가상구 가상동 48",
                "building_name": None,
                "pnu": WITHOUT_HISTORY,
                "has_history": False,
                "related_pnus": [],
            },
            {
                "road_addr": "가상시 가상구 가상로 16",
                "jibun_addr": "가상시 가상구 가상동",
                "building_name": None,
                "pnu": None,
                "has_history": None,  # 필지를 모르면 이력 여부도 모른다
                "related_pnus": [],
            },
        ],
        "page": 1,
        "total": 3,
    }
    assert re.fullmatch(r"[0-9A-HJKMNP-TV-Z]{26}", body["meta"]["request_id"])
    assert juso.calls == [(QUERY, 1)]


def test_same_query_hits_upstream_once(juso: FakeJuso) -> None:
    for q in (QUERY, f"  {QUERY} ", "가상로   12"):
        assert client.get(URL, params={"q": q}).status_code == 200
    assert juso.calls == [(QUERY, 1)]
    assert client.get(URL, params={"q": QUERY, "page": 2}).status_code == 200
    assert juso.calls == [(QUERY, 1), (QUERY, 2)]


def test_has_history_is_not_cached(juso: FakeJuso, monkeypatch: pytest.MonkeyPatch) -> None:
    client.get(URL, params={"q": QUERY})

    async def none_exist(pnus: list[str]) -> set[str]:
        return set()

    monkeypatch.setattr(db, "existing_parcels", none_exist)
    items = client.get(URL, params={"q": QUERY}).json()["data"]["items"]
    assert [item["has_history"] for item in items] == [False, False, None]


@pytest.mark.parametrize("q", ["가", " 가 ", "%=", "or", ""])
def test_short_keyword_is_422_without_upstream_call(juso: FakeJuso, q: str) -> None:
    response = client.get(URL, params={"q": q})
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "VALIDATION_ERROR"
    assert response.json()["error"]["details"] == {"fields": {"q": "too_short"}}
    assert juso.calls == []


def test_page_below_one_is_422(juso: FakeJuso) -> None:
    response = client.get(URL, params={"q": QUERY, "page": 0})
    assert response.status_code == 422
    assert response.json()["error"]["details"] == {"fields": {"page": "must_be_positive"}}
    assert juso.calls == []


def test_keyword_rejected_by_upstream_is_422(juso: FakeJuso) -> None:
    juso.result = JusoKeywordError("E0006")
    response = client.get(URL, params={"q": "가상특별시"})
    assert response.status_code == 422
    assert response.json()["error"]["details"] == {"fields": {"q": "E0006"}}


def test_upstream_failure_is_502_and_not_cached(juso: FakeJuso) -> None:
    juso.result = JusoUnavailableError("ConnectTimeout")
    response = client.get(URL, params={"q": QUERY})
    assert response.status_code == 502
    assert response.json()["error"]["code"] == "UPSTREAM_UNAVAILABLE"
    assert "ConnectTimeout" not in response.text
    juso.result = PAGE
    assert client.get(URL, params={"q": QUERY}).status_code == 200
    assert len(juso.calls) == 2


def test_parcel_lookup_failure_is_503(juso: FakeJuso, monkeypatch: pytest.MonkeyPatch) -> None:
    async def broken(pnus: list[str]) -> set[str]:
        raise ConnectionRefusedError("refused")

    monkeypatch.setattr(db, "existing_parcels", broken)
    response = client.get(URL, params={"q": QUERY})
    assert response.status_code == 503
    assert response.json()["error"]["code"] == "SERVICE_UNAVAILABLE"
    assert "refused" not in response.text


def test_missing_key_is_502(juso: FakeJuso, monkeypatch: pytest.MonkeyPatch) -> None:
    app.dependency_overrides.clear()
    monkeypatch.delenv("JUSO_CONFM_KEY", raising=False)
    response = client.get(URL, params={"q": QUERY})
    assert response.status_code == 502
    assert response.json()["error"]["code"] == "UPSTREAM_UNAVAILABLE"


def test_rate_limit_429_with_retry_after(juso: FakeJuso) -> None:
    for _ in range(LOOKUP_LIMIT_PER_MINUTE):
        assert client.get(URL, params={"q": QUERY}).status_code == 200
    response = client.get(URL, params={"q": QUERY})
    assert response.status_code == 429
    assert response.json()["error"]["code"] == "RATE_LIMITED"
    assert 1 <= int(response.headers["Retry-After"]) <= 60


@pytest.mark.parametrize(
    "result",
    [PAGE, JusoKeywordError("E0006"), JusoUnavailableError("ConnectTimeout")],
)
def test_search_keyword_is_not_logged(
    juso: FakeJuso,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
    result: JusoPage | Exception,
) -> None:
    juso.result = result
    marker = "검색어표식7391"
    with caplog.at_level(logging.DEBUG):
        client.get(URL, params={"q": f"{marker} 가상로 12"})

        async def broken(pnus: list[str]) -> set[str]:
            raise RuntimeError("boom")

        monkeypatch.setattr(db, "existing_parcels", broken)
        client.get(URL, params={"q": f"{marker} 가상로 14"})
    # `httpx2` 로거의 기록은 테스트 클라이언트가 찍은 자기 요청 URL이라 뺀다(서버 로그가 아니다).
    # 서버가 도로명주소 API로 보내는 요청 URL에 검색어가 없다는 것은 test_juso.py가 본다.
    logged = "\n".join(
        f"{record.getMessage()} {record.args!r} {record.__dict__!r}"
        for record in caplog.records
        if not record.name.startswith("httpx2")
    )
    assert marker not in logged and "7391" not in logged


def test_settings_repr_hides_key(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.core.config import get_settings

    monkeypatch.setenv("JUSO_CONFM_KEY", "TEST-KEY-가상")
    settings = get_settings()
    assert settings.juso_confm_key == "TEST-KEY-가상"
    assert "TEST-KEY" not in repr(settings)


def test_related_lots_become_pnus(juso: FakeJuso) -> None:
    lots = (
        RelatedLot("가상시 가상구 가상동", False, 47, 1),  # 대표 지번과 같다 → 뺀다
        RelatedLot("가상시 가상구 가상동", False, 4, 3),
        RelatedLot("가상시 가상구 모르는동", False, 9, 0),  # 법정동을 찾지 못함 → 뺀다
        RelatedLot("가상시 가상구 다른동", True, 12, 0),
        RelatedLot("가상시 가상구 가상동", False, 4, 3),  # 중복 → 뺀다
        RelatedLot("가상시 가상구 옛동", False, 1, 0),  # 폐지 코드 하나뿐 → 그 코드
    )
    juso.result = JusoPage(
        items=(
            JusoItem("가상로 12", "가상동 47-1", None, WITH_HISTORY, lots),
            JusoItem("가상로 16", "가상동", None, None, lots[1:2]),
        ),
        page=1,
        total=2,
    )
    items = client.get(URL, params={"q": QUERY}).json()["data"]["items"]
    assert items[0]["related_pnus"] == [
        "1121510700100040003",
        "1121510800200120000",
        "1121510900100010000",
    ]
    assert items[1]["pnu"] is None and items[1]["related_pnus"] == ["1121510700100040003"]


def test_legal_dong_lookup_failure_is_503(juso: FakeJuso, monkeypatch: pytest.MonkeyPatch) -> None:
    async def broken(names: list[str]) -> list[tuple[str, str, bool]]:
        raise ConnectionRefusedError("refused")

    monkeypatch.setattr(db, "legal_dong_rows", broken)
    juso.result = JusoPage(
        items=(JusoItem("가상로 12", "가상동 47-1", None, WITH_HISTORY, PAGE_LOT),),
        page=1,
        total=1,
    )
    response = client.get(URL, params={"q": QUERY})
    assert response.status_code == 503
    assert "refused" not in response.text


PAGE_LOT = (RelatedLot("가상시 가상구 가상동", False, 4, 3),)
