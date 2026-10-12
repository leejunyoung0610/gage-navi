"""일괄 폐업일 규칙과 W0 방식 비교 (T-015). 여기의 관할 코드·날짜·건수는 모두 가상 예시다."""

from datetime import date, timedelta

import pandas as pd

from app.location.normalize.bulk_closure import CLOSED_ON, JURISDICTION
from jobs.measure_bulk_closure import (
    AREA,
    CLOSED,
    FLOOR,
    GENERAL,
    GROUP_BULK,
    GROUP_PLAIN,
    GROUP_W0_ONLY_DAY,
    GROUP_W0_OTHER,
    HO_LIST,
    LICENSE_TYPE,
    OPENED_ON,
    PNU,
    compare,
    group_labels,
    parse_area_x100,
    render_report,
    successor_flags,
    validity,
)

START = date(2020, 1, 1)


def closed_frame() -> pd.DataFrame:
    rows: list[tuple[str, pd.Timestamp | None, str]] = []

    def add(jurisdiction: str, offset: int, count: int, license_type: str = GENERAL) -> None:
        day = pd.Timestamp(START + timedelta(days=offset))
        rows.extend((jurisdiction, day, license_type) for _ in range(count))

    for offset in range(4):  # 평소: 관할마다 하루 2건
        for jurisdiction in ("A", "B", "C", "D"):
            add(jurisdiction, offset, 2)
    # 4일째: A가 90건 일괄 정리, B·C는 평소 5건씩 → 서울 전체 100건 (W0 일괄 폐업일)
    add("A", 4, 90)
    add("B", 4, 5)
    add("C", 4, 5)
    # 5일째: 네 관할이 25건씩 → 서울 전체 100건이지만 어느 관할도 30건 미만
    for jurisdiction in ("A", "B", "C", "D"):
        add(jurisdiction, 5, 25)
    # 6일째: D에서 휴게음식점 40건 → 새 규칙만 탐지 (W0는 일반음식점 100건 미만)
    add("D", 6, 40, "rest_restaurant")
    rows.append(("A", None, GENERAL))  # 폐업일자 없음 → 대상 아님
    return pd.DataFrame(rows, columns=[JURISDICTION, CLOSED_ON, LICENSE_TYPE])


def test_compare() -> None:
    result = compare(closed_frame())
    assert result.closed_records == 32 + 100 + 100 + 40
    assert (result.bulk_cells, result.bulk_dates, result.bulk_records) == (2, 2, 130)
    assert (result.w0_days, result.w0_records) == (2, 200)
    assert result.covered == 90
    assert result.bulk_only_records == 40
    assert (result.hit_days, result.hit_day_records) == (1, 100)
    assert (result.miss_days, result.miss_day_records) == (1, 100)
    assert result.missed_max_cell == 25
    assert result.coverage_percent == 45
    assert [
        (day.closed_on, day.w0_records, day.max_jurisdiction_count)
        for day in result.top_missed_days
    ] == [(START + timedelta(days=5), 100, 25)]
    # 문서 값(30, 10)이 첫 줄. 최소 건수를 20으로 낮추면 5일째 네 관할도 잡힌다
    assert result.sensitivity[0] == (30, 10, 130, 90)
    assert (20, 10, 230, 190) in result.sensitivity


def test_render_report() -> None:
    frame = closed_frame()
    report = render_report(compare(frame), (), date(2026, 10, 13), ["가상.csv"], 273)
    assert "- 비율: 45.00%" in report
    assert "| 탐지된 관할이 하나 이상 있는 날 | 1 | 100 | 90 | 10 |" in report
    assert "| 탐지된 관할이 없는 날 | 1 | 100 | 0 | 100 |" in report
    assert "| 2020-01-06 | 100 | 25 |" in report


def test_group_labels() -> None:
    frame = closed_frame()
    labels = group_labels(frame)
    assert labels.value_counts().to_dict() == {
        GROUP_BULK: 130,  # A의 90건 + D의 휴게음식점 40건
        GROUP_W0_ONLY_DAY: 100,  # 5일째
        GROUP_PLAIN: 32,
        GROUP_W0_OTHER: 10,  # 4일째 B·C
    }
    assert len(labels) == len(frame) - 1  # 폐업일자 없는 기록은 묶음이 없다


def record(
    pnu: str | None,
    opened: str,
    closed: str | None,
    ho: tuple[str, ...] = (),
    area: int | None = None,
    floor: str | None = "1",
) -> dict[str, object]:
    return {
        "jurisdiction": "A",
        CLOSED: closed is not None,
        CLOSED_ON: pd.Timestamp(closed) if closed else pd.NaT,
        OPENED_ON: pd.Timestamp(opened),
        LICENSE_TYPE: GENERAL,
        PNU: pnu,
        FLOOR: floor,
        HO_LIST: ho,
        AREA: area,
    }


def records_frame(rows: list[dict[str, object]]) -> pd.DataFrame:
    frame = pd.DataFrame(rows)
    frame[AREA] = frame[AREA].astype("Int64")
    return frame


def test_successor_flags() -> None:
    frame = records_frame(
        [
            # 0: 폐업 전에 같은 호의 기록(1)이 이미 개업 → 같은 호
            record("P1", "2010-01-01", "2020-01-01", ho=("101",)),
            record("P1", "2015-01-01", None, ho=("101", "102")),
            # 2: 폐업 전에 면적이 1% 이내인 기록(3)이 개업 → 면적. 호는 겹치지 않는다
            record("P2", "2010-01-01", "2020-01-01", ho=("201",), area=10000),
            record("P2", "2012-01-01", "2013-01-01", ho=("202",), area=10100),
            # 4: 뒤 기록(5)의 면적 차이가 1%를 넘는다 (10000 vs 10102, 큰 쪽의 1%는 101.02)
            record("P3", "2010-01-01", "2020-01-01", area=10000),
            record("P3", "2012-01-01", None, area=10102),
            # 6: 뒤 기록(7)이 폐업일 당일에 개업 → 폐업일 "전"이 아니다
            record("P4", "2010-01-01", "2020-01-01", ho=("1",)),
            record("P4", "2020-01-01", None, ho=("1",)),
            # 8: 같은 호 기록(9)이 먼저 개업 → 9에게는 8이 폐업 전에 개업한 뒤 기록
            record("P5", "2010-01-01", "2011-01-01", ho=("1",)),
            record("P5", "2005-01-01", "2020-01-01", ho=("1",)),
            # 10·11: 층이 다르면 다른 층키
            record("P6", "2010-01-01", "2020-01-01", ho=("1",), floor="1"),
            record("P6", "2015-01-01", None, ho=("1",), floor="2"),
            # 12: 층키 없음 → 분모 아님. 13: 영업 중 → 분모 아님
            record(None, "2010-01-01", "2020-01-01", ho=("1",)),
            record("P7", "2010-01-01", None, ho=("1",)),
        ]
    )
    flags = successor_flags(frame)
    assert list(flags.index[flags["by_ho"]]) == [0, 9]
    assert list(flags.index[flags["by_area"]]) == [2]
    assert list(flags.index[~flags["eligible"]]) == [1, 5, 7, 11, 12, 13]


def test_validity_rates() -> None:
    rows = []
    for jurisdiction, offset, count in [("A", 4, 30)] + [("A", day, 2) for day in range(4)]:
        closed_on = (START + timedelta(days=offset)).isoformat()
        for number in range(count):
            row = record(f"{jurisdiction}{offset}-{number}", "2010-01-01", closed_on, ho=("1",))
            rows.append(row)
    # 일괄 폐업 30건 중 처음 3건, 평소 폐업 8건 중 1건에 "폐업 전에 개업한 같은 호 기록"을 붙인다
    for key in ("A4-0", "A4-1", "A4-2", "A0-0"):
        rows.append(record(key, "2015-01-01", None, ho=("1",)))
    rates = {(rate.group, rate.era): rate for rate in validity(records_frame(rows))}
    bulk, plain = rates[(GROUP_BULK, None)], rates[(GROUP_PLAIN, None)]
    assert (bulk.records, bulk.eligible, bulk.successor, bulk.by_ho, bulk.by_area) == (
        30,
        30,
        3,
        3,
        0,
    )
    assert (plain.records, plain.eligible, plain.successor) == (8, 8, 1)
    assert rates[(GROUP_W0_ONLY_DAY, None)].records == 0
    assert rates[(GROUP_BULK, "2020~")].successor == 3
    assert rates[(GROUP_BULK, "2010~2019")].records == 0
    report = render_report(compare(records_frame(rows)), tuple(rates.values()), START, [], 42)
    assert "| ① 새 규칙이 표시한 폐업 | 30 | 30 | 3 | **10.00%** | 10.00% | 0.00% |" in report
    assert "| ② 표시 안 된 일반 폐업 | 8 | 8 | 1 | **12.50%** | 12.50% | 0.00% |" in report


def test_parse_area_x100() -> None:
    assert parse_area_x100("74.38") == 7438
    assert parse_area_x100(" 1,367.33 ") == 136733
    assert parse_area_x100("33") == 3300
    assert parse_area_x100("") is None
    assert parse_area_x100("0") is None
    assert parse_area_x100("-3") is None
    assert parse_area_x100("약 30") is None
    assert parse_area_x100("NaN") is None


def test_no_w0_days() -> None:
    frame = closed_frame()
    result = compare(frame[frame[CLOSED_ON] < pd.Timestamp(START + timedelta(days=4))])
    assert (result.w0_days, result.coverage_percent) == (0, None)
