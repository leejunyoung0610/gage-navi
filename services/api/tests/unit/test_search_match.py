"""검색 일치율 측정의 순수 함수 (docs/50 §7). 관리번호·주소·응답은 모두 가상 예시다."""

import asyncio
import dataclasses
import hashlib
from decimal import Decimal
from typing import Any

import pytest

from app.address.juso import KEYWORD_ERROR_CODES, JusoUnavailableError
from app.address.search_match import (
    CALL_INTERVAL_SECONDS,
    HOLD_RATE,
    JIBUN_CHANGED,
    KEYWORD_ERROR,
    MATCH,
    MULTI_PARCEL,
    NO_RESULT,
    OTHER,
    PASS_RATE,
    REMEASURE_SEED,
    SAMPLE_SIZE,
    SEED,
    TRANSPORT_ERROR,
    TRANSPORT_RETRIES,
    AccessProblemError,
    Outcome,
    Pacer,
    RecordKey,
    ReportContext,
    SampleRecord,
    draw_sample,
    keyword_of,
    measure,
    parse_rel_jibun,
    render_report,
    sample_rank,
    verdict,
    year_band,
)
from app.location.stats.base_rate import wilson_ci

POPULATION = [
    RecordKey(license_type, f"가상-{n:05d}")
    for license_type in ("general_restaurant", "rest_restaurant", "bakery")
    for n in range(400)
]


def test_preregistered_constants() -> None:
    assert (SEED, REMEASURE_SEED, SAMPLE_SIZE) == (20261013, 20261014, 2000)


def test_sample_rank_is_sha256_of_seed_and_key() -> None:
    key = RecordKey("bakery", "가상-00001")
    expected = hashlib.sha256("20261013:bakery:가상-00001".encode()).hexdigest()
    assert sample_rank(20261013, key) == expected


def test_draw_sample_takes_lowest_ranks() -> None:
    sample = draw_sample(POPULATION, seed=SEED, size=50)
    assert len(sample) == len(set(sample)) == 50
    ranks = [sample_rank(SEED, key) for key in sample]
    assert ranks == sorted(ranks)
    rest = set(POPULATION) - set(sample)
    assert max(ranks) < min(sample_rank(SEED, key) for key in rest)


def test_draw_sample_ignores_population_order_and_duplicates() -> None:
    forward = draw_sample(POPULATION, size=50)
    assert draw_sample(reversed(POPULATION), size=50) == forward
    assert draw_sample(POPULATION + POPULATION[:100], size=50) == forward


def test_draw_sample_changes_with_seed() -> None:
    first = draw_sample(POPULATION, seed=SEED, size=50)
    second = draw_sample(POPULATION, seed=REMEASURE_SEED, size=50)
    assert first != second
    assert len(set(first) & set(second)) < 25


def test_draw_sample_smaller_population() -> None:
    assert len(draw_sample(POPULATION[:10], size=50)) == 10


@pytest.mark.parametrize(
    ("road_addr", "expected"),
    [
        ("가상시 가상구 가상로 611 (가상동)", "가상시 가상구 가상로 611"),
        ("가상시 가상구 가상로41길 9, 제시동 1층 좌측호 (가상동)", "가상시 가상구 가상로41길 9"),
        ("가상시 가상구 가상로 지하 88, 374호 (가상동2가)", "가상시 가상구 가상로 지하 88"),
        ("가상시 가상구 가상로 870 (가상동, 지하3층)", "가상시 가상구 가상로 870"),
        ("가상시  가상구   가상로 12-3", "가상시 가상구 가상로 12-3"),
        ("가상시 가상구 가상로 12(가상동)", "가상시 가상구 가상로 12"),
    ],
)
def test_keyword_of(road_addr: str, expected: str) -> None:
    assert keyword_of(road_addr) == expected


# --- 측정 -------------------------------------------------------------------------------

PNU = "1121510700100470001"
OTHER_PNU = "1121510700100480000"
RECORD = SampleRecord(
    key=RecordKey("bakery", "가상-00001"),
    road_addr="서울특별시 가상구 가상로 12, 1층 (가상동)",
    jibun_addr="서울특별시 가상구 가상동 47-1 가상빌딩",
    pnu=PNU,
    sigungu_code="11215",
    opened_year=2018,
)
KEYWORD = "서울특별시 가상구 가상로 12"


def juso_row(main: str = "47", sub: str = "1", **extra: Any) -> dict[str, Any]:
    base = {
        "roadAddr": f"{KEYWORD} (가상동)",
        "roadAddrPart1": KEYWORD,
        "jibunAddr": f"서울특별시 가상구 가상동 {main}-{sub}",
        "admCd": "1121510700",
        "mtYn": "0",
        "lnbrMnnm": main,
        "lnbrSlno": sub,
        "bdMgtSn": "가상",
        "bdNm": "",
    }
    return base | extra


def body(rows: list[dict[str, Any]], code: str = "0") -> Any:
    common = {"errorCode": code, "errorMessage": "가상", "totalCount": str(len(rows))}
    return {"results": {"common": common, "juso": rows}}


class FakeTime:
    def __init__(self) -> None:
        self.now = 100.0
        self.sleeps: list[float] = []

    def clock(self) -> float:
        return self.now

    async def sleep(self, seconds: float) -> None:
        self.sleeps.append(seconds)
        self.now += seconds


class FakeFetch:
    """응답(또는 예외)을 순서대로 돌려주고 호출 시각·인자를 적어 둔다."""

    def __init__(self, time: FakeTime, replies: list[Any], took: float = 0.2) -> None:
        self.time = time
        self.replies = list(replies)
        self.took = took
        self.calls: list[tuple[float, str, int, bool]] = []

    async def __call__(self, keyword: str, page: int, *, add_info: bool = False) -> Any:
        self.calls.append((self.time.now, keyword, page, add_info))
        self.time.now += self.took
        reply = self.replies.pop(0)
        if isinstance(reply, Exception):
            raise reply
        return reply


def run_measure(records: list[SampleRecord], replies: list[Any]) -> tuple[list[str], FakeFetch]:
    time = FakeTime()
    fetch = FakeFetch(time, replies)
    pacer = Pacer(time.clock, time.sleep)
    outcomes = asyncio.run(measure(records, fetch, pacer))
    assert pacer.calls == len(fetch.calls)
    return [row.outcome for row in outcomes], fetch


def test_preregistered_procedure_constants() -> None:
    assert CALL_INTERVAL_SECONDS == 1.0 and TRANSPORT_RETRIES == 2
    assert (PASS_RATE, HOLD_RATE) == (Decimal("0.95"), Decimal("0.90"))
    # ADR-028 개정: 이 코드만 "검색어 문제", 나머지는 모두 접근 문제
    assert KEYWORD_ERROR_CODES == {
        "E0005", "E0006", "E0008", "E0009", "E0010", "E0011", "E0012", "E0013", "E0015",
    }  # fmt: skip


def test_match_uses_first_page_candidates_and_proxy_request() -> None:
    outcomes, fetch = run_measure([RECORD], [body([juso_row("48", "0"), juso_row()])])
    assert outcomes == [MATCH]
    assert [(k, p, a) for _, k, p, a in fetch.calls] == [(KEYWORD, 1, False)]


def test_calls_are_sequential_and_one_second_apart() -> None:
    replies = [body([juso_row()]), httpx_like_timeout(), body([juso_row()]), body([juso_row()])]
    outcomes, fetch = run_measure([RECORD] * 3, replies)
    assert outcomes == [MATCH] * 3
    starts = [at for at, *_ in fetch.calls]
    assert [round(b - a, 6) for a, b in zip(starts, starts[1:], strict=False)] == [1.0, 1.0, 1.0]


def httpx_like_timeout() -> JusoUnavailableError:
    return JusoUnavailableError("ConnectTimeout")


def test_transport_error_retries_twice_then_counts_as_failure() -> None:
    errors = [httpx_like_timeout(), JusoUnavailableError("http_503"), JusoUnavailableError("x")]
    outcomes, fetch = run_measure([RECORD, RECORD], [*errors, body([juso_row()])])
    assert outcomes == [TRANSPORT_ERROR, MATCH]
    assert len(fetch.calls) == 4


def test_transport_error_recovers_on_retry() -> None:
    outcomes, fetch = run_measure([RECORD], [httpx_like_timeout(), body([juso_row()])])
    assert outcomes == [MATCH] and len(fetch.calls) == 2


@pytest.mark.parametrize("code", sorted(KEYWORD_ERROR_CODES))
def test_keyword_error_code_counts_as_failure_and_continues(code: str) -> None:
    outcomes, fetch = run_measure([RECORD, RECORD], [body([], code), body([juso_row()])])
    assert outcomes == [KEYWORD_ERROR, MATCH]
    assert len(fetch.calls) == 2  # 재시도하지 않는다


@pytest.mark.parametrize("code", ["-999", "E0001", "E0014", "E0007", "E9999", "LIMIT"])
def test_access_problem_code_stops_immediately(code: str) -> None:
    time = FakeTime()
    fetch = FakeFetch(time, [body([juso_row()]), body([], code), body([juso_row()])])
    with pytest.raises(AccessProblemError) as caught:
        asyncio.run(measure([RECORD] * 3, fetch, Pacer(time.clock, time.sleep)))
    assert caught.value.call_no == 2 and caught.value.reason == f"error_code_{code}"
    assert len(fetch.calls) == 2  # 멈춘 뒤에는 부르지 않는다
    assert KEYWORD not in str(caught.value)


def test_unexpected_response_shape_stops() -> None:
    time = FakeTime()
    fetch = FakeFetch(time, [{"가상": 1}])
    with pytest.raises(AccessProblemError):
        asyncio.run(measure([RECORD], fetch, Pacer(time.clock, time.sleep)))


def test_keyword_too_short_is_keyword_error_without_call() -> None:
    record = dataclasses.replace(RECORD, road_addr="가, 1층")
    outcomes, fetch = run_measure([record], [])
    assert outcomes == [KEYWORD_ERROR] and fetch.calls == []


def test_no_result() -> None:
    outcomes, fetch = run_measure([RECORD], [body([])])
    assert outcomes == [NO_RESULT] and len(fetch.calls) == 1


def test_mismatch_is_reclassified_with_related_lots() -> None:
    first = body([juso_row("48", "0")])
    related = body([juso_row("48", "0", relJibun="서울특별시 가상구 다른동 1,가상동 3-2,47-1")])
    outcomes, fetch = run_measure([RECORD], [first, related])
    assert outcomes == [MULTI_PARCEL]  # 관련지번에 있어도 일치로 바꾸지 않는다
    assert [(k, a) for _, k, _, a in fetch.calls] == [(KEYWORD, False), (KEYWORD, True)]


def test_mismatch_same_road_address_is_jibun_changed() -> None:
    first = body([juso_row("48", "0")])
    related = body([juso_row("48", "0", relJibun="서울특별시 가상구 다른동 47-1,가상동 47-2")])
    assert run_measure([RECORD], [first, related])[0] == [JIBUN_CHANGED]


def test_mismatch_other() -> None:
    row = juso_row("48", "0", roadAddrPart1="서울특별시 가상구 가상로 120", relJibun="")
    assert run_measure([RECORD], [body([row]), body([row])])[0] == [OTHER]


@pytest.mark.parametrize(
    "second", [[httpx_like_timeout()] * 3, [body([], "E0006")]], ids=["transport", "keyword"]
)
def test_mismatch_is_other_when_second_lookup_fails(second: list[Any]) -> None:
    assert run_measure([RECORD], [body([juso_row("48", "0")]), *second])[0] == [OTHER]


def test_second_lookup_access_problem_stops() -> None:
    time = FakeTime()
    fetch = FakeFetch(time, [body([juso_row("48", "0")]), body([], "E0014")])
    with pytest.raises(AccessProblemError):
        asyncio.run(measure([RECORD], fetch, Pacer(time.clock, time.sleep)))


def test_parse_rel_jibun() -> None:
    text = "서울특별시 가상구 가동 225-79,나동 4-1,4-3,산4-8,528,읽을수없음,다동 산54"
    assert parse_rel_jibun(text) == {
        ("가동", False, 225, 79),
        ("나동", False, 4, 1),
        ("나동", False, 4, 3),
        ("나동", True, 4, 8),
        ("나동", False, 528, 0),
        ("다동", True, 54, 0),
    }
    assert parse_rel_jibun("") == set() and parse_rel_jibun(None) == set()
    assert parse_rel_jibun("4-1,4-3") == set()  # 법정동 이름을 모르면 읽지 않는다


def test_year_band() -> None:
    years = [None, 1975, 1999, 2000, 2009, 2010, 2015, 2016, 2020, 2021, 2026]
    assert [year_band(year) for year in years] == [
        "개업일 없음", "1999년 이전", "1999년 이전", "2000~2009", "2000~2009", "2010~2015",
        "2010~2015", "2016~2020", "2016~2020", "2021년 이후", "2021년 이후",
    ]  # fmt: skip


@pytest.mark.parametrize(
    ("matched", "remeasure", "expected"),
    [
        (2000, False, "통과"),
        (1900, False, "통과"),  # 정확히 95%
        (1899, False, "실패 유형을 분류해 고친 뒤 다시 측정한다"),
        (1800, False, "실패 유형을 분류해 고친 뒤 다시 측정한다"),  # 정확히 90%
        (1799, False, "Gate 1 보류"),
        (1900, True, "통과"),
        (1899, True, "Gate 1은 진행하되 조건 두 가지"),
        (1800, True, "Gate 1은 진행하되 조건 두 가지"),
        (1799, True, "Gate 1 보류"),
    ],
)
def test_verdict(matched: int, remeasure: bool, expected: str) -> None:
    assert verdict(matched, 2000, remeasure=remeasure).startswith(expected)


def test_render_report() -> None:
    other_gu = dataclasses.replace(RECORD, sigungu_code="11440", opened_year=None)
    results = [MATCH] * 7 + [NO_RESULT, MULTI_PARCEL, KEYWORD_ERROR]
    outcomes = [Outcome(RECORD if i % 2 else other_gu, name) for i, name in enumerate(results)]
    report = render_report(
        outcomes,
        ReportContext(
            measured_on="2026-10-13",
            criteria_commit="2026-10-13 (가상0000)",
            seed=20261013,
            remeasure=False,
            population=400_000,
            snapshots="bakery #3",
            records_total=1000,
            records_with_pnu=990,
            calls=11,
            stopped_runs="없음",
            gu_names={"11215": "가상구", "11440": "나상구"},
        ),
    )
    low, high = wilson_ci(7, 10)
    assert "- **검색 일치율: 70.00%** (7 / 10)" in report
    assert f"{(low * 100):.2f}% ~ {(high * 100):.2f}%" in report
    assert "- PNU 성공률: 99.00% (990 / 1,000" in report
    assert "- 종단 값(PNU 성공률 × 검색 일치율): 69.30%" in report
    assert "- **판정: Gate 1 보류**" in report
    assert "| 결과 없음 | 1 | 10.00% |" in report
    assert "| 여러 필지 건물 | 1 | 10.00% |" in report
    assert "| 검색어 오류 | 1 | 10.00% |" in report
    assert "| 지번 변경 (추정) | 0 | 0.00% |" in report
    assert "| 합계 | 3 | 30.00% |" in report
    assert "| 가상구 | 5 | " in report and "| 나상구 | 5 | " in report
    assert "| 2016~2020 | 5 | " in report and "| 개업일 없음 | 5 | " in report
    assert "가상로" not in report and "가상-00001" not in report  # 주소·관리번호는 싣지 않는다
