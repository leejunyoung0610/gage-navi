"""층 이력 요약과 과거 폐업 횟수 (docs/10 §7.1·§7.2). 필지·업소·날짜는 모두 가상 예시다."""

from datetime import date

import pandas as pd
import pytest

from app.location.history.build import (
    MAX_AT_OPEN,
    PRIOR,
    PRIOR_EX_SURGE,
    build_floor_summary,
    build_parcels,
    build_record_prior,
    jibun_label,
    max_concurrent,
    max_concurrent_at_open,
    prior_closures,
    scale_of,
    statistical,
)

AS_OF = date(2026, 10, 7)
P1 = "1121510700100470001"  # 화양동 47-1 (가상)
P2 = "1121510700200210000"  # 화양동 산 21 (가상)
DONGS = {"1121510700": "서울특별시 광진구 화양동"}


def record(
    number: int,
    opened: str | None,
    closed: str | None = None,
    *,
    pnu: str = P1,
    floor: str | None = "1",
    status: str | None = None,
    bulk: bool = False,
    mobile: bool = False,
    suppressed: bool = False,
    road: str | None = None,
    geom: str | None = None,
) -> dict[str, object]:
    return {
        "id": number,
        "pnu": pnu,
        "floor": floor,
        "status": status or ("closed" if closed else "open"),
        "opened_on": None if opened is None else date.fromisoformat(opened),
        "closed_on": None if closed is None else date.fromisoformat(closed),
        "bulk_closure": bulk,
        "no_fixed_place": mobile,
        "suppressed": suppressed,
        "road_addr": road,
        "geom_ewkt": geom,
    }


def frame(rows: list[dict[str, object]]) -> pd.DataFrame:
    return pd.DataFrame(rows)


# 합성 층: 동시 영업, 같은 날 개·폐업, 급증일 폐업이 섞인 1층
FLOOR = [
    record(1, "2006-01-01", "2010-06-30"),  # 평범한 폐업
    record(2, "2008-01-01", "2012-03-31", bulk=True),  # 1번과 동시 영업, 급증일에 폐업
    record(3, "2010-06-30", "2015-01-01"),  # 1번이 폐업한 날 개업 → 1번은 세지 않는다
    record(4, "2012-04-01", "2012-04-01"),  # 같은 날 개·폐업
    record(5, "2012-04-01"),  # 4번과 같은 날 개업, 영업 중
    record(6, "2015-01-02"),  # 3번이 폐업한 다음 날 개업
    record(7, "2011-01-01", None, status="closed"),  # 폐업인데 폐업일자 없음
    record(8, None, "2009-01-01"),  # 개업일 없음
]


def priors(rows: list[dict[str, object]]) -> dict[int, tuple[int, int]]:
    result = build_record_prior(frame(rows), AS_OF)
    return {
        int(row["record_id"]): (int(row[PRIOR]), int(row[PRIOR_EX_SURGE]))
        for row in result.to_dict("records")
    }


def test_prior_closures_on_the_synthetic_floor() -> None:
    assert priors(FLOOR) == {
        1: (0, 0),
        2: (0, 0),
        3: (1, 1),  # 8번(2009-01-01 폐업). 1번은 같은 날 폐업이라 세지 않는다
        4: (3, 2),  # 1·2·8번. 2번은 급증일 폐업이라 뺀 값에서는 빠진다
        5: (3, 2),  # 4번은 같은 날 폐업이라 세지 않는다
        6: (5, 4),  # 1·2·3·4·8번. 날짜 없는 7번은 세지 않는다
        7: (2, 2),  # 1·8번
    }  # 8번은 개업일이 없어 행이 없다


def test_prior_closures_accepts_any_exclusion() -> None:
    floor_records = statistical(frame(FLOOR))
    w0_style = floor_records["id"].isin([1, 8])  # 다른 정의로 뺄 폐업 (예: 서울 전체 100건 이상)
    counts = prior_closures(floor_records, w0_style)
    assert dict(zip(floor_records.loc[counts.index, "id"], counts, strict=True))[6] == 3


def test_prior_closures_scope() -> None:
    rows = [
        record(1, "2006-01-01", "2010-01-01", floor="1"),
        record(2, "2011-01-01", floor="2"),  # 층이 다르다
        record(3, "2011-01-01", pnu=P2),  # 필지가 다르다
        record(4, "2011-01-01", floor=None),  # 층 없음 → 행 없음
        record(5, "2007-01-01", "2009-01-01", mobile=True),  # 고정된 자리 없음 → F가 아니다
        record(6, "2011-01-01"),
        record(7, "2011-01-01", suppressed=True),  # 숨김 기록도 통계 값은 만든다
    ]
    assert priors(rows) == {1: (0, 0), 2: (0, 0), 3: (0, 0), 6: (1, 1), 7: (1, 1)}


def summary(rows: list[dict[str, object]]) -> dict[tuple[str, str], dict[str, object]]:
    result = build_floor_summary(frame(rows), AS_OF)
    return {(row["pnu"], row["floor"]): row for row in result.to_dict("records")}


def test_floor_summary_on_the_synthetic_floor() -> None:
    row = summary(FLOOR)[(P1, "1")]
    assert (row["record_count"], row["records_since_2005"], row["open_now_count"]) == (8, 7, 2)
    # 폐업 기록의 영업기간(급증일 폐업 2번 제외): 1번 1,641일, 3번 1,646일, 4번 0일 → 중앙값 1,641
    assert row["median_closed_tenure_days"] == 1641
    assert row["has_concurrent"] and row["method_version"] == "2026.10.1"


def test_floor_summary_excludes_hidden_and_mobile_records() -> None:
    rows = [
        record(1, "2006-01-01", "2010-01-01"),
        record(2, "2011-01-01", mobile=True),
        record(3, "2012-01-01", suppressed=True),
        record(4, "2013-01-01", floor=None),
        record(5, "2000-01-01", "2001-01-01", floor="B1"),
    ]
    result = summary(rows)
    assert set(result) == {(P1, "1"), (P1, "B1")}
    assert result[(P1, "1")]["record_count"] == 1 and result[(P1, "1")]["open_now_count"] == 0
    assert result[(P1, "B1")]["records_since_2005"] == 0


def test_median_tenure() -> None:
    even = [record(1, "2010-01-01", "2010-01-11"), record(2, "2011-01-01", "2011-01-12")]
    assert summary(even)[(P1, "1")]["median_closed_tenure_days"] == 11  # (10 + 11) / 2 = 10.5 → 11
    none = [record(1, "2010-01-01"), record(2, "2011-01-01", "2012-01-01", bulk=True)]
    assert pd.isna(summary(none)[(P1, "1")]["median_closed_tenure_days"])


@pytest.mark.parametrize(
    ("rows", "expected"),
    [
        # 정확히 30일 겹침 → 30일을 "넘지" 않는다
        ([record(1, "2020-01-01", "2020-03-01"), record(2, "2020-01-31", "2020-12-31")], False),
        # 31일 겹침
        ([record(1, "2020-01-01", "2020-03-02"), record(2, "2020-01-31", "2020-12-31")], True),
        # 이어서 영업 (겹침 없음)
        ([record(1, "2020-01-01", "2020-06-30"), record(2, "2020-07-01", "2021-01-01")], False),
        # 영업 중 기록은 기준일까지: 기준일 31일 전에 연 두 가게
        ([record(1, "2026-09-06"), record(2, "2026-09-06")], True),
        ([record(1, "2026-09-07"), record(2, "2026-09-07")], False),
        # 짧게 영업한 가게는 길게 영업한 가게 안에 있어도 30일을 넘지 못한다
        ([record(1, "2010-01-01", "2020-01-01"), record(2, "2015-01-01", "2015-01-20")], False),
        # 맨 처음 기록이 가장 늦게 끝나는 경우: 세 번째 기록과의 겹침을 놓치지 않는다
        (
            [
                record(1, "2010-01-01", "2020-01-01"),
                record(2, "2011-01-01", "2011-01-10"),
                record(3, "2012-01-01", "2013-01-01"),
            ],
            True,
        ),
        # 기간을 모르는 기록(개업일 없음, 폐업일 없는 폐업)은 판정에서 뺀다
        ([record(1, "2010-01-01"), record(2, None, "2020-01-01")], False),
        ([record(1, "2010-01-01"), record(2, "2011-01-01", None, status="closed")], False),
        # 층이 다르면 따로 본다
        ([record(1, "2010-01-01"), record(2, "2010-01-01", floor="2")], False),
        ([record(1, "2010-01-01")], False),
    ],
)
def test_has_concurrent(rows: list[dict[str, object]], expected: bool) -> None:
    assert summary(rows)[(P1, "1")]["has_concurrent"] is expected


def brute_force(rows: list[dict[str, object]], until: date) -> int:
    """정의 그대로: `until`에서 자른 기간들 중 함께 겹치는 길이가 30일을 넘는 가장 큰 묶음."""
    spans = []
    for row in rows:
        start, end = row["opened_on"], row["closed_on"] or (row["status"] == "open" and AS_OF)
        if isinstance(start, date) and isinstance(end, date):
            spans.append((start, min(end, until)))
    best = 1
    for anchor, _ in spans:  # 가장 큰 묶음의 겹침은 어떤 기록의 개업일에서 시작한다
        ends = [end for start, end in spans if start <= anchor and (end - anchor).days > 30]
        best = max(best, len(ends))
    return best


def full(rows: list[dict[str, object]]) -> int:
    return int(summary(rows)[(P1, "1")]["max_concurrent"])


def at_open(rows: list[dict[str, object]]) -> dict[int, int]:
    records = frame(rows)
    counts = max_concurrent_at_open(statistical(records), AS_OF)
    return {int(records.loc[index, "id"]): int(count) for index, count in counts.items()}


def stores(count: int, opened: str = "2010-01-01", closed: str | None = "2015-01-01"):
    return [record(number, opened, closed) for number in range(1, count + 1)]


def test_max_concurrent_on_the_synthetic_floor() -> None:
    # 1·2번(2008~2010), 2·3번, 3·5번이 둘씩 겹친다. 셋이 30일 넘게 함께 겹친 적은 없다
    assert full(FLOOR) == 2 == brute_force(FLOOR, AS_OF)
    # 개업일까지의 이력: 1·2번이 겹친 뒤에 연 3~7번은 2, 그 전에 연 1·2번은 1
    assert at_open(FLOOR) == {1: 1, 2: 1, 3: 2, 4: 2, 5: 2, 6: 2, 7: 2}
    priors_frame = build_record_prior(frame(FLOOR), AS_OF)
    assert dict(zip(priors_frame["record_id"], priors_frame[MAX_AT_OPEN], strict=True)) == at_open(
        FLOOR
    )


@pytest.mark.parametrize(
    ("rows", "expected"),
    [
        ([record(1, "2010-01-01")], 1),
        # 기간을 아는 기록이 없어도 최소 1
        ([record(1, None, "2020-01-01"), record(2, "2011-01-01", None, status="closed")], 1),
        # 가게가 바뀌면서 정확히 30일 겹침 → 동시가 아니다. 31일이면 동시
        ([record(1, "2020-01-01", "2020-03-01"), record(2, "2020-01-31", "2020-12-31")], 1),
        ([record(1, "2020-01-01", "2020-03-02"), record(2, "2020-01-31", "2020-12-31")], 2),
        # 쌍으로는 겹쳐도 셋이 함께 겹치는 기간이 30일 이하면 2
        (
            [
                record(1, "2020-01-01", "2020-06-30"),
                record(2, "2020-06-01", "2020-12-31"),  # 1번과 29일
                record(3, "2020-03-01", "2020-09-30"),
            ],
            2,
        ),
        # 규모 경계: 9곳과 10곳
        (stores(9), 9),
        (stores(10), 10),
        # 10번째 가게가 30일만 겹치면 9
        ([*stores(9, closed="2010-03-02"), record(10, "2010-01-31", "2011-01-01")], 9),
        ([*stores(9, closed="2010-03-03"), record(10, "2010-01-31", "2011-01-01")], 10),
        # 기간을 모르는 기록은 세지 않는다
        (
            [
                *stores(2),
                record(3, None, "2012-01-01"),
                record(4, "2011-01-01", None, status="closed"),
            ],
            2,
        ),
        # 영업 중 기록은 기준일까지
        ([record(1, "2026-09-06"), record(2, "2026-09-06")], 2),
        ([record(1, "2026-09-07"), record(2, "2026-09-07")], 1),
    ],
)
def test_max_concurrent(rows: list[dict[str, object]], expected: int) -> None:
    assert full(rows) == expected == brute_force(rows, AS_OF)
    assert summary(rows)[(P1, "1")]["has_concurrent"] is (expected >= 2)


def test_scale_boundaries() -> None:
    counts = pd.Series([1, 2, 9, 10, 250])
    assert list(scale_of(counts)) == ["single", "small", "small", "large", "large"]


def test_max_concurrent_at_open_uses_only_history_up_to_the_opening_day() -> None:
    rows = [
        record(1, "2010-01-01"),  # 10년 넘게 혼자 영업 중
        record(2, "2020-01-01", "2020-06-30"),  # 1번과 겹치지만 자기 개업일에는 혼자 있던 층
        record(3, "2021-01-01"),  # 1·2번이 겹친 뒤에 열었다
        *[record(number, "2024-01-01") for number in range(4, 13)],  # 나중에 푸드코트가 된다
        record(13, "2024-02-01"),  # 푸드코트가 열린 지 31일째에 연 가게
        record(14, "2024-01-31"),  # 30일째에 연 가게
    ]
    counts = at_open(rows)
    # 자기 자신은 개업일에 기간이 0일이라 누구와도 동시가 되지 않는다
    assert (counts[1], counts[2]) == (1, 1)
    assert counts[3] == 2
    assert counts[4] == 2  # 같은 날 연 가게들끼리는 아직 겹친 적이 없다
    assert counts[13] == 11  # 1·3번 + 푸드코트 9곳
    assert counts[14] == 2
    # 미래 정보가 새어 들어가지 않는다: 전체 이력으로는 모두 대형이다
    assert full(rows) == 13 and int(max_concurrent(statistical(frame(rows)), AS_OF).min()) == 13
    for number, row in enumerate(rows, start=1):
        opened = row["opened_on"]
        assert isinstance(opened, date)
        others = [other for other in rows if other is not row]
        assert counts[number] == brute_force(others, opened)


def test_max_concurrent_at_open_scope() -> None:
    rows = [
        *stores(3, closed=None),
        record(4, "2012-01-01", floor="2"),  # 층이 다르다
        record(5, "2012-01-01", pnu=P2),  # 필지가 다르다
        record(6, "2012-01-01"),
        record(7, None),  # 개업일 없음 → 값 없음
        record(8, "2005-01-01", mobile=True),  # 고정된 자리 없음 → F가 아니다
        record(9, "2005-01-01", "2020-01-01", suppressed=True),  # 숨김 기록도 통계에는 센다
    ]
    counts = at_open(rows)
    assert (counts[4], counts[5], counts[6]) == (1, 1, 4)
    assert 7 not in counts and 8 not in counts
    # 화면용 값은 이력에 보이는 기록만 센다
    assert full(rows) == 4


def test_parcels() -> None:
    rows = [
        record(
            1,
            "2006-01-01",
            "2010-01-01",
            floor="2",
            road="서울특별시 광진구 가상로 1, 2층",
            geom="G1",
        ),
        record(2, "2015-01-01", floor="B1", road="서울특별시 광진구 가상로 1-1, 지하1층 (화양동)"),
        record(3, "2020-01-01", floor="1"),  # 가장 최근이지만 도로명주소·좌표가 없다
        record(
            4, None, floor="RF", road="서울특별시 광진구 옛가상로 9", geom="G4"
        ),  # 개업일 없음 → 맨 뒤
        record(5, "2018-01-01", floor=None, geom="G5"),
        record(
            6, "2021-01-01", floor="3", mobile=True, road="서울특별시 광진구 트럭로 1", geom="G6"
        ),
        record(7, "2022-01-01", floor="4", suppressed=True),
        record(8, "2010-01-01", floor=None, pnu=P2),
    ]
    parcels = {row["pnu"]: row for row in build_parcels(frame(rows), DONGS).to_dict("records")}
    first = parcels[P1]
    assert first["legal_dong_code"] == "1121510700"
    assert first["jibun_label"] == "서울특별시 광진구 화양동 47-1"
    assert first["road_addr"] == "서울특별시 광진구 가상로 1-1"
    assert first["geom_ewkt"] == "G5"
    assert first["floors"] == ["B1", "1", "2", "RF"]
    assert first["record_count"] == 5
    second = parcels[P2]
    assert second["jibun_label"] == "서울특별시 광진구 화양동 산 21"
    assert (second["floors"], second["road_addr"], second["geom_ewkt"]) == ([], None, None)


def test_parcels_need_known_legal_dong() -> None:
    with pytest.raises(ValueError, match="1121510700"):
        build_parcels(frame([record(1, "2010-01-01")]), {})


def test_jibun_label() -> None:
    assert (
        jibun_label("1121510700100470000", "서울특별시 광진구 화양동")
        == "서울특별시 광진구 화양동 47"
    )
