"""GET /api/v1/address/reverse (docs/30 §2). 좌표·주소·필지는 모두 가상 예시다.

카카오는 녹화하지 않는다(AGENTS.md §3) — 클라이언트를 가짜로 바꾸고, 응답 해석은 test_kakao.py가
가상 픽스처로 본다.
"""

import logging
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
from app.address.kakao import KakaoLot, KakaoSpot, KakaoUnavailableError
from app.core import db
from app.core.ratelimit import LOOKUP_LIMIT_PER_MINUTE, lookup_limiter
from app.main import app

client = TestClient(app)

URL = "/api/v1/address/reverse"
SEARCH_URL = "/api/v1/address/search"
LAT, LNG = 37.123456, 127.654321  # 가상 예시 좌표
POINT = {"lat": str(LAT), "lng": str(LNG)}
CODE = "1121510700"  # 가상 예시 법정동코드
PNU = "1121510700100470001"  # CODE + 일반 + 47-1
OTHER_PNU = "1121510700100480000"

SPOT = KakaoSpot(
    legal_dong_code=CODE,
    lot=KakaoLot(is_san=False, main=47, sub=1),
    jibun_addr="가상 가상구 가상동 47-1",  # 카카오는 시도를 줄여 쓸 수 있다(가상 예시)
    road_addr="가상 가상구 가상로 12",
    building_name="가상빌딩",
)
LOTS = (
    RelatedLot("가상시 가상구 가상동", False, 4, 3),
    RelatedLot("가상시 가상구 다른동", True, 12, 0),
)
SAME = JusoItem("가상시 가상구 가상로 12", "가상시 가상구 가상동 47-1", "가상빌딩", PNU, LOTS)
SAME_ANNEX = JusoItem("가상시 가상구 가상로 12-1", "가상시 가상구 가상동 47-1", "가상별관", PNU)
OTHER = JusoItem("가상시 가상구 가상로 14", "가상시 가상구 가상동 48", None, OTHER_PNU, LOTS)
DONG_ROWS = [
    ("1121510700", "가상시 가상구 가상동", False),
    ("1121510800", "가상시 가상구 다른동", False),
]


class FakeKakao:
    def __init__(self, result: KakaoSpot | Exception = SPOT) -> None:
        self.result = result
        self.calls: list[tuple[float, float]] = []

    async def locate(self, lat: float, lng: float) -> KakaoSpot:
        self.calls.append((lat, lng))
        if isinstance(self.result, Exception):
            raise self.result
        return self.result


class FakeJuso:
    def __init__(self, result: JusoPage | Exception) -> None:
        self.result = result
        self.calls: list[tuple[str, int]] = []

    async def search(self, keyword: str, page: int) -> JusoPage:
        self.calls.append((keyword, page))
        if isinstance(self.result, Exception):
            raise self.result
        return self.result


def page(*items: JusoItem) -> JusoPage:
    return JusoPage(items=items, page=1, total=len(items))


@pytest.fixture
def kakao(monkeypatch: pytest.MonkeyPatch) -> Iterator[FakeKakao]:
    fake = FakeKakao()

    async def existing(pnus: list[str]) -> set[str]:
        return {PNU} & set(pnus)

    async def dong_rows(names: list[str]) -> list[tuple[str, str, bool]]:
        return [row for row in DONG_ROWS if row[1] in names]

    monkeypatch.setattr(db, "existing_parcels", existing)
    monkeypatch.setattr(db, "legal_dong_rows", dong_rows)
    app.dependency_overrides[address_router.get_kakao_client] = lambda: fake
    use_juso(page(SAME, OTHER))
    address_router.search_cache.clear()
    lookup_limiter.reset()
    yield fake
    app.dependency_overrides.clear()
    address_router.search_cache.clear()
    lookup_limiter.reset()


def use_juso(result: JusoPage | Exception | None) -> FakeJuso | None:
    fake = None if result is None else FakeJuso(result)
    app.dependency_overrides[address_router.get_reverse_juso_client] = lambda: fake
    app.dependency_overrides[address_router.get_juso_client] = lambda: fake
    return fake


def test_same_parcel_keeps_only_matching_pnu_with_related_pnus(kakao: FakeKakao) -> None:
    juso = use_juso(page(OTHER, SAME))
    response = client.get(URL, params=POINT)
    assert response.status_code == 200
    body = response.json()
    assert body["data"] == {
        "pnu": PNU,
        "items": [
            {
                "road_addr": "가상시 가상구 가상로 12",
                "jibun_addr": "가상시 가상구 가상동 47-1",
                "building_name": "가상빌딩",
                "pnu": PNU,
                "has_history": True,
                "related_pnus": ["1121510700100040003", "1121510800200120000"],
            }
        ],
    }
    assert set(body["meta"]) == {"request_id"}
    assert kakao.calls == [(LAT, LNG)]
    assert juso is not None and juso.calls == [("가상 가상구 가상로 12", 1)]


def test_several_buildings_on_one_parcel_are_all_returned(kakao: FakeKakao) -> None:
    use_juso(page(SAME, OTHER, SAME_ANNEX))
    items = client.get(URL, params=POINT).json()["data"]["items"]
    assert [item["building_name"] for item in items] == ["가상빌딩", "가상별관"]
    assert {item["pnu"] for item in items} == {PNU}
    assert items[1]["related_pnus"] == []  # 확인했고 없음


@pytest.mark.parametrize(
    "juso_result",
    [
        page(OTHER),  # 같은 PNU가 없다
        page(),
        JusoKeywordError("E0006"),
        JusoUnavailableError("ConnectTimeout"),
        None,  # 도로명주소 승인키 없음
    ],
)
def test_no_matching_search_result_gives_kakao_item_with_unknown_related(
    kakao: FakeKakao, juso_result: JusoPage | Exception | None
) -> None:
    use_juso(juso_result)
    response = client.get(URL, params=POINT)
    assert response.status_code == 200
    assert response.json()["data"] == {
        "pnu": PNU,
        "items": [
            {
                "road_addr": "가상 가상구 가상로 12",
                "jibun_addr": "가상 가상구 가상동 47-1",
                "building_name": "가상빌딩",
                "pnu": PNU,
                "has_history": True,
                "related_pnus": None,  # 확인 못 함 — 빈 목록이 아니다
            }
        ],
    }


def test_no_road_address_searches_by_jibun_and_keeps_road_null(kakao: FakeKakao) -> None:
    kakao.result = KakaoSpot(CODE, KakaoLot(True, 56, 0), "가상 가상구 가상동 산 56", None, None)
    juso = use_juso(page(OTHER))
    item = client.get(URL, params=POINT).json()["data"]["items"][0]
    assert juso is not None and juso.calls == [("가상 가상구 가상동 산 56", 1)]
    assert item["road_addr"] is None and item["building_name"] is None
    assert item["pnu"] == "1121510700200560000" and item["has_history"] is False
    assert item["related_pnus"] is None


@pytest.mark.parametrize(
    "spot",
    [
        KakaoSpot(None, KakaoLot(False, 47, 1), "가상 가상구 가상동 47-1", None, None),  # 법정동
        KakaoSpot(CODE, None, None, None, None),  # 지번 없음 (도로·하천)
        KakaoSpot(None, None, None, None, None),
    ],
)
def test_missing_code_or_lot_is_unknown(kakao: FakeKakao, spot: KakaoSpot) -> None:
    kakao.result = spot
    juso = use_juso(page(SAME))
    response = client.get(URL, params=POINT)
    assert response.status_code == 200
    assert response.json()["data"] == {"pnu": None, "items": []}
    assert juso is not None and juso.calls == []  # 추측해서 검색하지 않는다


def test_search_and_map_paths_give_same_pnu_and_related_pnus(kakao: FakeKakao) -> None:
    """같은 필지(가상 예시)에 대해 주소 검색 경로와 지도 경로의 결과가 같다 (T-032 수용 기준)."""
    use_juso(page(SAME, OTHER))
    searched = client.get(SEARCH_URL, params={"q": "가상로 12"}).json()["data"]["items"][0]
    picked = client.get(URL, params=POINT).json()["data"]["items"][0]
    assert searched["pnu"] == picked["pnu"] == PNU
    assert (
        searched["related_pnus"]
        == picked["related_pnus"]
        == [
            "1121510700100040003",
            "1121510800200120000",
        ]
    )
    assert searched == picked


def test_reverse_does_not_use_or_fill_search_cache(kakao: FakeKakao) -> None:
    juso = use_juso(page(SAME))
    for _ in range(2):
        assert client.get(URL, params=POINT).status_code == 200
    assert juso is not None and len(juso.calls) == 2  # 매번 부른다
    assert kakao.calls == [(LAT, LNG), (LAT, LNG)]
    assert address_router.search_cache.get("가상 가상구 가상로 12", 1) is None


@pytest.mark.parametrize(
    ("params", "field"),
    [
        ({"lng": "127.1"}, "lat"),
        ({"lat": "37.1"}, "lng"),
        ({"lat": "abc", "lng": "127.1"}, "lat"),
        ({"lat": "90.5", "lng": "127.1"}, "lat"),
        ({"lat": "37.1", "lng": "-180.1"}, "lng"),
        ({"lat": "nan", "lng": "127.1"}, "lat"),
    ],
)
def test_bad_coordinates_are_422_without_upstream_call(
    kakao: FakeKakao, params: dict[str, str], field: str
) -> None:
    response = client.get(URL, params=params)
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "VALIDATION_ERROR"
    assert field in response.json()["error"]["details"]["fields"]
    assert kakao.calls == []


def test_kakao_failure_is_502(kakao: FakeKakao) -> None:
    kakao.result = KakaoUnavailableError("http_401")
    response = client.get(URL, params=POINT)
    assert response.status_code == 502
    assert response.json()["error"]["code"] == "UPSTREAM_UNAVAILABLE"
    assert "http_401" not in response.text


def test_missing_kakao_key_is_502(kakao: FakeKakao, monkeypatch: pytest.MonkeyPatch) -> None:
    del app.dependency_overrides[address_router.get_kakao_client]
    monkeypatch.delenv("KAKAO_REST_API_KEY", raising=False)
    response = client.get(URL, params=POINT)
    assert response.status_code == 502
    assert response.json()["error"]["code"] == "UPSTREAM_UNAVAILABLE"


def test_parcel_lookup_failure_is_503(kakao: FakeKakao, monkeypatch: pytest.MonkeyPatch) -> None:
    async def broken(pnus: list[str]) -> set[str]:
        raise ConnectionRefusedError("refused")

    monkeypatch.setattr(db, "existing_parcels", broken)
    response = client.get(URL, params=POINT)
    assert response.status_code == 503
    assert response.json()["error"]["code"] == "SERVICE_UNAVAILABLE"
    assert "refused" not in response.text


def test_rate_limit_is_shared_with_lookup_api(kakao: FakeKakao) -> None:
    for _ in range(LOOKUP_LIMIT_PER_MINUTE):
        assert client.get(URL, params=POINT).status_code == 200
    response = client.get(URL, params=POINT)
    assert response.status_code == 429
    assert response.json()["error"]["code"] == "RATE_LIMITED"


def test_settings_repr_hides_kakao_key(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.core.config import get_settings

    monkeypatch.setenv("KAKAO_REST_API_KEY", "TEST-KEY-fake-example")  # 가상 예시
    settings = get_settings()
    assert settings.kakao_rest_api_key == "TEST-KEY-fake-example"
    assert "TEST-KEY" not in repr(settings)


@pytest.mark.parametrize(
    "result",
    [SPOT, KakaoUnavailableError("ConnectTimeout"), JusoUnavailableError("ConnectTimeout")],
)
def test_coordinates_and_kakao_values_are_not_logged(
    kakao: FakeKakao,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
    result: KakaoSpot | Exception,
) -> None:
    """좌표(ADR-014)와 카카오 응답에서 나온 값은 로그에 남지 않는다 (data/README.md)."""
    if isinstance(result, JusoUnavailableError):
        use_juso(result)
    else:
        kakao.result = result
    with caplog.at_level(logging.DEBUG):
        client.get(URL, params={"lat": "37.987654", "lng": "126.876543"})

        async def broken(pnus: list[str]) -> set[str]:
            raise RuntimeError("boom")

        monkeypatch.setattr(db, "existing_parcels", broken)
        client.get(URL, params={"lat": "37.987654", "lng": "126.876543"})
    # `httpx2` 로거의 기록은 테스트 클라이언트가 찍은 자기 요청 URL이라 뺀다(서버 로그가 아니다)
    logged = "\n".join(
        f"{record.getMessage()} {record.args!r} {record.__dict__!r}"
        for record in caplog.records
        if not record.name.startswith("httpx2")
    )
    for value in ("37.98", "126.87", PNU, "가상로", "가상동", "가상빌딩"):
        assert value not in logged
