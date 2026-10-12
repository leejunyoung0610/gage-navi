"""일괄 폐업일 규칙과 W0 방식 비교 (T-015). 여기의 관할 코드·날짜·건수는 모두 가상 예시다."""

from datetime import date, timedelta

import pandas as pd

from app.location.normalize.bulk_closure import CLOSED_ON, JURISDICTION
from jobs.measure_bulk_closure import GENERAL, LICENSE_TYPE, compare, render_report

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
    assert not result.passed
    assert [
        (day.closed_on, day.w0_records, day.max_jurisdiction_count)
        for day in result.top_missed_days
    ] == [(START + timedelta(days=5), 100, 25)]
    # 문서 값(30, 10)이 첫 줄. 최소 건수를 20으로 낮추면 5일째 네 관할도 잡힌다
    assert result.sensitivity[0] == (30, 10, 130, 90)
    assert (20, 10, 230, 190) in result.sensitivity


def test_render_report() -> None:
    report = render_report(compare(closed_frame()), date(2026, 10, 13), ["가상.csv"], 273)
    assert "**비율: 45.00%** (기준 ≥ 95% → 미달)" in report
    assert "| 탐지된 관할이 하나 이상 있는 날 | 1 | 100 | 90 | 10 |" in report
    assert "| 탐지된 관할이 없는 날 | 1 | 100 | 0 | 100 |" in report
    assert "| 2020-01-06 | 100 | 25 |" in report


def test_no_w0_days() -> None:
    frame = closed_frame()
    result = compare(frame[frame[CLOSED_ON] < pd.Timestamp(START + timedelta(days=4))])
    assert (result.w0_days, result.coverage_percent, result.passed) == (0, None, False)
