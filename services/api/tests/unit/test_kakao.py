"""카카오 로컬 API 클라이언트 (docs/30 §2 `address/reverse`, docs/03 D5).

응답은 모두 가상 예시다(`tests/fixtures/http/kakao/`, REST 키 `TEST-KEY-fake-example`도 가상 값).
카카오 실제 응답은 이용 조건상 녹화해 저장소에 넣지 않는다(AGENTS.md §3, data/README.md).
"""

import asyncio
import json
from pathlib import Path
from typing import Any

import httpx2
import pytest

from app.address.kakao import (
    KAKAO_ADDRESS_URL,
    KAKAO_REGION_URL,
    KakaoClient,
    KakaoLot,
    KakaoSpot,
    KakaoUnavailableError,
    parse_address,
    parse_region,
)

FIXTURE_DIR = Path(__file__).parents[1] / "fixtures" / "http" / "kakao"
FAKE_KEY = "TEST-KEY-fake-example"  # 가상 예시 (헤더 값은 ASCII만 가능)
LAT, LNG = 37.123456, 127.654321  # 가상 예시 좌표


def load(name: str) -> Any:
    return json.loads((FIXTURE_DIR / f"{name}.json").read_text(encoding="utf-8"))


def test_every_fixture_is_marked_virtual() -> None:
    paths = sorted(FIXTURE_DIR.glob("*.json"))
    assert paths
    for path in paths:
        assert load(path.stem)["_comment"].startswith("가상 예시"), path.name


def test_region_picks_legal_dong_code_not_admin_dong() -> None:
    assert parse_region(load("region_legal_dong")) == "1121510700"


@pytest.mark.parametrize(
    "documents",
    [
        [],
        [{"region_type": "H", "code": "1121599999"}],
        [{"region_type": "B", "code": "11215107"}],  # 10자리가 아니면 모름
        [{"region_type": "B", "code": None}],
    ],
)
def test_region_without_usable_legal_dong_is_none(documents: list[Any]) -> None:
    assert parse_region({"meta": {}, "documents": documents}) is None


@pytest.mark.parametrize("payload", [None, [], {"meta": {}}, {"documents": "x"}])
def test_unexpected_format_is_unavailable(payload: Any) -> None:
    with pytest.raises(KakaoUnavailableError):
        parse_region(payload)
    with pytest.raises(KakaoUnavailableError):
        parse_address(payload, "1121510700")


def test_address_with_building() -> None:
    spot = parse_address(load("address_building"), "1121510700")
    assert spot == KakaoSpot(
        legal_dong_code="1121510700",
        lot=KakaoLot(is_san=False, main=47, sub=1),
        jibun_addr="가상시 가상구 가상동 47-1",
        road_addr="가상시 가상구 가상로 12",
        building_name="가상빌딩",
    )
    assert spot.pnu == "1121510700100470001"


def test_mountain_lot_without_road_address() -> None:
    spot = parse_address(load("address_mountain_no_road"), "1121510700")
    assert spot.road_addr is None and spot.building_name is None
    assert spot.lot == KakaoLot(is_san=True, main=56, sub=0)  # 부번 빈 문자열 → 0
    assert spot.pnu == "1121510700200560000"


def test_no_address_is_unknown() -> None:
    spot = parse_address(load("address_empty"), "1121510700")
    assert spot.lot is None and spot.jibun_addr is None and spot.pnu is None


def test_missing_legal_dong_code_is_unknown_pnu() -> None:
    assert parse_address(load("address_building"), None).pnu is None


@pytest.mark.parametrize(
    "overrides",
    [
        {"mountain_yn": "X"},
        {"main_address_no": ""},  # 본번은 빈 값이면 모름 (0으로 채우지 않는다)
        {"main_address_no": "12345"},
        {"sub_address_no": "가"},
        {"mountain_yn": None},
    ],
)
def test_unreadable_lot_is_unknown(overrides: dict[str, Any]) -> None:
    payload = load("address_building")
    payload["documents"][0]["address"].update(overrides)
    spot = parse_address(payload, "1121510700")
    assert spot.lot is None and spot.pnu is None


def _client(handler: Any) -> KakaoClient:
    return KakaoClient(FAKE_KEY, httpx2.AsyncClient(transport=httpx2.MockTransport(handler)))


def test_locate_calls_region_then_address_with_header_key() -> None:
    seen: list[httpx2.Request] = []

    def handler(request: httpx2.Request) -> httpx2.Response:
        seen.append(request)
        url = str(request.url).split("?", 1)[0]
        name = "region_legal_dong" if url == KAKAO_REGION_URL else "address_building"
        return httpx2.Response(200, json=load(name))

    spot = asyncio.run(_client(handler).locate(LAT, LNG))
    assert spot.pnu == "1121510700100470001"
    assert [str(r.url).split("?", 1)[0] for r in seen] == [KAKAO_REGION_URL, KAKAO_ADDRESS_URL]
    for request in seen:
        assert request.method == "GET"
        assert request.headers["Authorization"] == f"KakaoAK {FAKE_KEY}"
        assert FAKE_KEY not in str(request.url)  # 키는 헤더로만
        assert request.url.params["x"] == str(LNG) and request.url.params["y"] == str(LAT)


@pytest.mark.parametrize(
    ("response", "reason"),
    [
        (httpx2.Response(401, json={"errorType": "AccessDeniedError"}), "http_401"),
        (httpx2.Response(429, json={}), "http_429"),
        (httpx2.Response(200, content=b"not json"), "invalid_json"),
    ],
)
def test_http_failures_are_unavailable(response: httpx2.Response, reason: str) -> None:
    with pytest.raises(KakaoUnavailableError) as caught:
        asyncio.run(_client(lambda request: response).locate(LAT, LNG))
    assert caught.value.reason == reason


def test_transport_error_message_has_no_coordinates_or_key() -> None:
    def handler(request: httpx2.Request) -> httpx2.Response:
        raise httpx2.ConnectTimeout("timeout", request=request)

    with pytest.raises(KakaoUnavailableError) as caught:
        asyncio.run(_client(handler).locate(LAT, LNG))
    message = str(caught.value)
    assert caught.value.reason == "ConnectTimeout"
    assert "37.12" not in message and "127.65" not in message and FAKE_KEY not in message
