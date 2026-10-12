"""행정 일괄 폐업일 탐지 (docs/10 §5). 여기의 관할 코드·날짜·건수는 모두 가상 예시다."""

from datetime import date, timedelta

import pandas as pd
import pytest

from app.location.normalize.bulk_closure import (
    CLOSED_ON,
    COUNT,
    JURISDICTION,
    MEDIAN,
    daily_counts,
    detect_bulk_days,
    flag_bulk_closure,
    is_bulk,
)

START = date(2020, 1, 1)


def closures(per_day: dict[str, list[int]]) -> pd.DataFrame:
    """관할별 날짜 순 건수 목록 → 기록 한 줄에 폐업 1건."""
    rows = [
        (jurisdiction, START + timedelta(days=offset))
        for jurisdiction, counts in per_day.items()
        for offset, count in enumerate(counts)
        for _ in range(count)
    ]
    return pd.DataFrame(rows, columns=[JURISDICTION, CLOSED_ON])


@pytest.mark.parametrize(
    ("count", "median", "expected"),
    [
        (30, 3, True),  # 정확히 30건, 정확히 중앙값 10배
        (29, 2, False),  # 30건 미만 (중앙값의 10배는 넘는다)
        (30, 1, True),  # 정확히 30건
        (31, 3, True),
        (40, 4, True),  # 정확히 중앙값 10배
        (39, 4, False),  # 30건 이상이지만 중앙값 10배 미만
        (35, 3.5, True),  # 중앙값이 .5로 끝나는 경우의 정확히 10배
        (34, 3.5, False),
        (30, 3.5, False),
    ],
)
def test_is_bulk_boundaries(count: int, median: float, expected: bool) -> None:
    assert is_bulk(count, median) is expected


def test_exactly_30_is_bulk_and_29_is_not() -> None:
    days = detect_bulk_days(closures({"A": [2, 2, 2, 2, 30], "B": [2, 2, 2, 2, 29]}))
    assert days.to_dict("records") == [
        {JURISDICTION: "A", CLOSED_ON: START + timedelta(days=4), COUNT: 30, MEDIAN: 2.0}
    ]


def test_exactly_ten_times_median_is_bulk_and_one_less_is_not() -> None:
    days = detect_bulk_days(closures({"A": [4, 4, 4, 4, 40], "B": [4, 4, 4, 4, 39]}))
    assert list(days[JURISDICTION]) == ["A"]
    assert list(days[COUNT]) == [40]


def test_median_counts_only_days_with_closures_and_includes_bulk_day() -> None:
    # 폐업이 없던 날(0건)은 중앙값에 넣지 않는다. 건수 [1, 3, 5, 60] → 중앙값 4
    counts = daily_counts(closures({"A": [1, 0, 3, 0, 0, 5, 60]}))
    assert list(counts[COUNT]) == [1, 3, 5, 60]
    assert set(counts[MEDIAN]) == {4.0}


def test_half_median() -> None:
    # 날 수가 짝수면 중앙값이 .5로 끝날 수 있다. [3, 3, 3, 4, 4, N] → 중앙값 3.5, 10배는 35
    days = detect_bulk_days(closures({"A": [3, 3, 3, 4, 4, 35], "B": [3, 3, 3, 4, 4, 34]}))
    assert days.to_dict("records") == [
        {JURISDICTION: "A", CLOSED_ON: START + timedelta(days=5), COUNT: 35, MEDIAN: 3.5}
    ]


def test_jurisdictions_are_independent() -> None:
    # 같은 날 A는 일괄 폐업, B는 평소 건수. B의 중앙값이 커서 B의 35건은 일괄이 아니다
    frame = closures({"A": [1, 1, 1, 1, 50], "B": [20, 20, 20, 20, 35]})
    days = detect_bulk_days(frame)
    assert list(days[JURISDICTION]) == ["A"]
    flags = flag_bulk_closure(frame, days)
    assert int(flags.sum()) == 50
    assert set(frame.loc[flags, JURISDICTION]) == {"A"}
    assert set(frame.loc[flags, CLOSED_ON]) == {START + timedelta(days=4)}


def test_missing_closed_on_is_not_counted_or_flagged() -> None:
    frame = closures({"A": [2, 2, 2, 2, 30]})
    frame = pd.concat(
        [frame, pd.DataFrame({JURISDICTION: ["A"] * 40, CLOSED_ON: [None] * 40})],
        ignore_index=True,
    )
    days = detect_bulk_days(frame)
    assert list(days[COUNT]) == [30]
    assert int(flag_bulk_closure(frame, days).sum()) == 30


def test_no_closures() -> None:
    empty = pd.DataFrame({JURISDICTION: [], CLOSED_ON: []})
    assert detect_bulk_days(empty).empty
    assert flag_bulk_closure(empty, detect_bulk_days(empty)).empty
