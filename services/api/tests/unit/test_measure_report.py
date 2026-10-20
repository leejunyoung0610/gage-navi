"""수요 검증 측정값 (docs/70 §5 정의). 날짜·수는 가상 예시다."""

from datetime import date, timedelta

import pytest

from app.measure.report import daily_rows, demand_report, ratio

START = date(2026, 11, 1)  # 1일차, 가상 예시


def day(n: int) -> date:
    """n일차 (1부터)."""
    return START + timedelta(days=n - 1)


def test_unique_visitors_count_first_visits_on_days_1_to_28() -> None:
    counts = {(day(1), "first_visit"): 3, (day(28), "first_visit"): 2, (day(29), "first_visit"): 9}
    counts[(day(0), "first_visit")] = 7  # 공개 전
    report = demand_report(counts, START, 28)
    assert report.unique_visitors == 5
    assert report.end == day(28)


def test_revisit_rate_uses_first_visits_on_days_1_to_21_only() -> None:
    counts = {
        (day(1), "first_visit"): 10,
        (day(1), "revisit_7d"): 2,
        (day(21), "first_visit"): 10,
        (day(21), "revisit_7d"): 1,
        # 22일차 첫 방문은 7일 뒤까지 볼 수 없어 분모·분자 모두에서 빠진다
        (day(22), "first_visit"): 50,
        (day(22), "revisit_7d"): 50,
        # 공개 전 첫 방문의 재방문도 빠진다
        (day(0), "revisit_7d"): 4,
    }
    report = demand_report(counts, START, 28)
    assert report.revisit_cohort_end == day(21)
    assert (report.revisit.numerator, report.revisit.denominator) == (3, 20)
    assert report.revisit.rate == "0.1500"
    assert report.unique_visitors == 70


def test_helpful_counts_and_share() -> None:
    counts = {(day(3), "helpful_yes"): 2, (day(5), "helpful_no"): 1, (day(30), "helpful_yes"): 9}
    report = demand_report(counts, START, 28)
    assert (report.helpful_yes, report.helpful_no) == (2, 1)
    assert report.helpful_yes_share.rate == "0.6667"  # 반올림(0.5 올림)


def test_empty_period_has_no_rates() -> None:
    report = demand_report({}, START, 28)
    assert report.unique_visitors == 0
    assert report.revisit.rate is None and report.helpful_yes_share.rate is None
    assert len(report.daily) == 28 and all(row.first_visit == 0 for row in report.daily)


def test_extension_period_uses_same_definition() -> None:
    # 연장하면 연장한 28일만 본다 (docs/70 §5) — 시작일만 바꿔 같은 함수로
    start = day(29)
    counts = {(day(29), "first_visit"): 4, (day(1), "first_visit"): 100}
    assert demand_report(counts, start, 28).unique_visitors == 4


def test_daily_rows_fill_missing_days_with_zero() -> None:
    rows = daily_rows({(day(2), "helpful_no"): 1}, day(1), day(3))
    assert [(r.day, r.helpful_no, r.first_visit) for r in rows] == [
        (day(1), 0, 0),
        (day(2), 1, 0),
        (day(3), 0, 0),
    ]


def test_ratio_rounds_half_up() -> None:
    assert ratio(1, 8).rate == "0.1250"
    assert ratio(1, 3).rate == "0.3333"
    assert ratio(0, 0).rate is None


def test_period_must_be_longer_than_revisit_window() -> None:
    with pytest.raises(ValueError):
        demand_report({}, START, 7)
