"""도로명주소 API 클라이언트 (docs/10 §2.2, docs/03 D4).

여기의 응답은 공식 가이드 예시 형식을 따라 만든 가상 예시다(승인키 `TEST-KEY-가상`도 가상 값).
실제 응답을 녹화한 픽스처 테스트는 `test_juso_contract.py`.
"""

import asyncio
from typing import Any

import httpx2
import pytest

from app.address.juso import (
    COUNT_PER_PAGE,
    JUSO_SEARCH_URL,
    JusoClient,
    JusoItem,
    JusoKeywordError,
    JusoUnavailableError,
    clean_keyword,
    parse_response,
    pnu_from_juso,
)

FAKE_KEY = "TEST-KEY-가상"
KEYWORD = "가상시 가상구 가상로 12"


def row(**overrides: Any) -> dict[str, Any]:
    base = {
        "roadAddr": "가상시 가상구 가상로 12 (가상동)",
        "jibunAddr": "가상시 가상구 가상동 47-1 가상빌딩",
        "admCd": "1121510700",
        "mtYn": "0",
        "lnbrMnnm": "47",
        "lnbrSlno": "1",
        "bdMgtSn": "1121510700100470001000001",
        "bdNm": "가상빌딩",
    }
    return base | overrides


def payload(rows: list[dict[str, Any]], code: str = "0", total: str | None = None) -> Any:
    common = {
        "errorCode": code,
        "errorMessage": "가상",
        "totalCount": total if total is not None else str(len(rows)),
        "currentPage": "1",
        "countPerPage": "10",
    }
    return {"results": {"common": common, "juso": rows}}


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("  능동로   120 ", "능동로 120"),
        ("능동로 120%", "능동로 120"),
        ("a=b<c>d[e]", "a b c d e"),
        ("능동로' or '1'='1", "능동로 1 1"),
        ("능동로 UNION SELECT 1", "능동로 1"),
        ("World Tower", "World Tower"),  # 낱말 안의 or는 지우지 않는다
        ("Selection 빌딩", "Selection 빌딩"),
        ("or", ""),
    ],
)
def test_clean_keyword(raw: str, expected: str) -> None:
    assert clean_keyword(raw) == expected


@pytest.mark.parametrize(
    ("args", "expected"),
    [
        (("1121510700", "0", "47", "1"), "1121510700100470001"),
        (("1121510700", "1", "56", "0"), "1121510700200560000"),  # 산
        (("1121510700", "0", 47, 1), "1121510700100470001"),  # 숫자형으로 와도 같다
        (("1121510700", "0", "1595", "0"), "1121510700115950000"),
    ],
)
def test_pnu_from_juso(args: tuple[Any, Any, Any, Any], expected: str) -> None:
    assert pnu_from_juso(*args) == expected


@pytest.mark.parametrize(
    "args",
    [
        ("11215107", "0", "47", "1"),  # 코드가 10자리가 아님
        ("1121510700", "", "47", "1"),  # 산 여부를 모름 — 일반 필지로 채우지 않는다
        ("1121510700", None, "47", "1"),
        ("1121510700", "0", "", "1"),
        ("1121510700", "0", "47", None),
        ("1121510700", "0", "10000", "1"),
        ("1121510700", "0", "47", "-1"),
        (None, "0", "47", "1"),
    ],
)
def test_pnu_from_juso_unknown(args: tuple[Any, Any, Any, Any]) -> None:
    assert pnu_from_juso(*args) is None


def test_parse_response() -> None:
    page = parse_response(payload([row(), row(bdNm="", mtYn="")], total="37"), page=2)
    assert page.page == 2 and page.total == 37
    assert page.items[0] == JusoItem(
        road_addr="가상시 가상구 가상로 12 (가상동)",
        jibun_addr="가상시 가상구 가상동 47-1 가상빌딩",
        building_name="가상빌딩",
        pnu="1121510700100470001",
    )
    assert page.items[1].building_name is None and page.items[1].pnu is None


def test_parse_response_no_result() -> None:
    assert parse_response(payload([]), page=1).items == ()
    body = payload([])
    body["results"]["juso"] = None
    assert parse_response(body, page=1).total == 0


@pytest.mark.parametrize("code", ["E0005", "E0006", "E0008", "E0013", "E0015"])
def test_parse_response_keyword_error(code: str) -> None:
    with pytest.raises(JusoKeywordError) as caught:
        parse_response(payload([], code=code), page=1)
    assert caught.value.code == code


@pytest.mark.parametrize("code", ["E0001", "E0014", "-999", "E9999"])
def test_parse_response_service_error(code: str) -> None:
    with pytest.raises(JusoUnavailableError):
        parse_response(payload([], code=code), page=1)


@pytest.mark.parametrize(
    "body",
    [None, [], {}, {"results": {}}, {"results": {"common": {"errorCode": "0"}, "juso": []}},
     payload([{"jibunAddr": "가상"}]), payload([row()], total="많음"), payload(["가상"])],
)  # fmt: skip
def test_parse_response_unexpected_format(body: Any) -> None:
    with pytest.raises(JusoUnavailableError):
        parse_response(body, page=1)


def run_search(handler: Any, keyword: str = KEYWORD, page: int = 1) -> Any:
    async def go() -> Any:
        async with httpx2.AsyncClient(transport=httpx2.MockTransport(handler)) as http:
            return await JusoClient(FAKE_KEY, http).search(keyword, page)

    return asyncio.run(go())


def test_client_sends_key_and_keyword_in_body_only() -> None:
    seen: list[httpx2.Request] = []

    def handler(request: httpx2.Request) -> httpx2.Response:
        seen.append(request)
        return httpx2.Response(200, json=payload([row()]))

    result = run_search(handler, page=3)
    assert result.page == 3
    (request,) = seen
    assert request.method == "POST"
    assert str(request.url) == JUSO_SEARCH_URL
    assert request.url.query == b""
    form = dict(httpx2.QueryParams(request.content.decode()))
    assert form == {
        "confmKey": FAKE_KEY,
        "currentPage": "3",
        "countPerPage": str(COUNT_PER_PAGE),
        "keyword": KEYWORD,
        "resultType": "json",
    }


def _raises_timeout(request: httpx2.Request) -> httpx2.Response:
    raise httpx2.ConnectTimeout("가상 시간 초과", request=request)


@pytest.mark.parametrize(
    "handler",
    [
        _raises_timeout,
        lambda request: httpx2.Response(500, text=f"boom {FAKE_KEY}"),
        lambda request: httpx2.Response(200, text="<html>점검 중</html>"),
        lambda request: httpx2.Response(200, json=payload([], code="E0001")),
        lambda request: httpx2.Response(200, json=payload([], code="E0006")),
    ],
)
def test_client_errors_do_not_carry_key_or_keyword(handler: Any) -> None:
    with pytest.raises((JusoUnavailableError, JusoKeywordError)) as caught:
        run_search(handler)
    exc = caught.value
    text = f"{exc!s} {exc!r} {exc.__cause__!r} {exc.__context__!r}"
    assert exc.__context__ is None or exc.__suppress_context__
    assert FAKE_KEY not in str(exc) and FAKE_KEY not in repr(exc)
    assert KEYWORD not in text and "가상로" not in str(exc)


def test_transport_error_reason_is_marked_connection() -> None:
    with pytest.raises(JusoUnavailableError) as caught:
        run_search(_raises_timeout)
    assert caught.value.reason == "connection_ConnectTimeout"


def test_client_timeout_is_passed_to_request() -> None:
    seen: list[Any] = []

    def handler(request: httpx2.Request) -> httpx2.Response:
        seen.append(request.extensions["timeout"])
        return httpx2.Response(200, json=payload([row()]))

    async def go() -> None:
        async with httpx2.AsyncClient(transport=httpx2.MockTransport(handler)) as http:
            await JusoClient(FAKE_KEY, http, timeout=10.0).search(KEYWORD, 1)
            await JusoClient(FAKE_KEY, http).search(KEYWORD, 1)

    asyncio.run(go())
    assert [t["read"] for t in seen] == [10.0, 5.0]
