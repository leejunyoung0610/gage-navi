"""PNU 생성 실패율 집계·리포트 (docs/10 §2.1). 주소와 법정동코드는 모두 가상 예시다."""

from datetime import date
from decimal import Decimal

from app.address.pnu import (
    FAIL_AMBIGUOUS,
    FAIL_DONG_NOT_FOUND,
    FAIL_REGEX_MISMATCH,
    LegalDongIndex,
)
from app.address.pnu_report import EMPTY_ADDRESS, failure_group, measure, render_report

INDEX = LegalDongIndex.from_rows(
    [
        ("9930010100", "서울특별시 가상구 현행동", False),
        ("9930010200", "서울특별시 가상구 폐지동", True),
        ("9930010300", "서울특별시 가상구 중복동", False),
        ("9930010301", "서울특별시 가상구 중복동", False),
    ]
)
ROAD = "서울특별시 가상구 가상로 1"

ROWS = [
    ("서울특별시 가상구 현행동 1-1", ROAD, 990),
    ("서울특별시 가상구 폐지동 2", ROAD, 5),  # 폐지 코드로 생성: 실패 아님
    ("", ROAD, 2),  # 지번 없음, 도로명이 서울 → 분모에 들어가고 정규식 불일치
    ("서울특별시 가상구 현행동 일대", ROAD, 1),
    ("서울특별시 가상구 없는동 3-1", ROAD, 1),
    ("서울특별시 가상구 중복동 4", ROAD, 1),
    ("가상도 가상시 가상동 5", "가상도 가상시 가상로 5", 7),  # 서울 밖: 분모에서 뺀다
]


def test_counts_and_failure_rate() -> None:
    stats = measure(ROWS, INDEX)

    assert (stats.total, stats.non_seoul, stats.abolished_only) == (1000, 7, 5)
    assert stats.by_reason == {
        FAIL_REGEX_MISMATCH: 3,
        FAIL_DONG_NOT_FOUND: 1,
        FAIL_AMBIGUOUS: 1,
    }
    assert stats.failed == 5
    assert stats.failure_percent == Decimal("0.5")


def test_exactly_half_percent_does_not_pass() -> None:
    assert measure(ROWS, INDEX).passed is False


def test_below_half_percent_passes() -> None:
    rows = [("서울특별시 가상구 현행동 1-1", ROAD, 996), *ROWS[1:]]
    assert measure(rows, INDEX).passed is True


def test_abolished_only_is_not_a_failure() -> None:
    stats = measure([("서울특별시 가상구 폐지동 2", ROAD, 5)], INDEX)
    assert (stats.failed, stats.abolished_only, stats.failure_percent) == (0, 5, Decimal(0))


def test_no_records_is_unmeasurable() -> None:
    stats = measure([], INDEX)
    assert stats.failure_percent is None
    assert stats.passed is None


def test_failure_groups() -> None:
    assert failure_group(FAIL_REGEX_MISMATCH, "  ") == EMPTY_ADDRESS
    assert failure_group(FAIL_REGEX_MISMATCH, "서울특별시 가상구  12로 34") == (
        "서울특별시 가상구 N로 N"
    )
    assert failure_group(FAIL_DONG_NOT_FOUND, "서울특별시 가상구 없는동 3-1 2층") == (
        "서울특별시 가상구 없는동"
    )


def test_report_lists_rate_reasons_and_top_failures() -> None:
    report = render_report(
        measure(ROWS, INDEX),
        measured_on=date(2026, 10, 12),
        snapshots=["general_restaurant #1"],
        legal_dong_rows=4,
    )

    assert "측정일: 2026-10-12" in report
    assert "실패율: 0.5000%** (기준 < 0.5% → 미달)" in report
    assert "| `regex_mismatch` | 3 |" in report
    assert "| `dong_not_found` | 1 |" in report
    assert "| `ambiguous` | 1 |" in report
    assert "폐지 코드만 있는 이름: 5건" in report
    assert f"| 1 | `regex_mismatch` | {EMPTY_ADDRESS} | 2 | {EMPTY_ADDRESS} |" in report
    assert "이름 1개, 기록 1건." in report
    assert "| 서울특별시 가상구 없는동 | 1 | 서울특별시 가상구 없는동 3-1 |" in report


def test_report_keeps_only_top_20_groups() -> None:
    rows = [(f"서울특별시 가상구 없는{i}동 1", ROAD, i + 1) for i in range(25)]
    report = render_report(
        measure(rows, INDEX), measured_on=date(2026, 10, 12), snapshots=[], legal_dong_rows=4
    )

    assert "이름 25개, 기록 325건." in report
    assert "\n| 20 | `" in report
    assert "\n| 21 | `" not in report
    assert "없는24동 |" in report  # 건수가 가장 많은 묶음
    assert "없는4동 |" not in report  # 21번째
    assert "| 없음 | 0 | - |" not in report


def test_report_says_none_when_every_name_is_found() -> None:
    report = render_report(
        measure([("서울특별시 가상구 현행동 1-1", ROAD, 3)], INDEX),
        measured_on=date(2026, 10, 12),
        snapshots=[],
        legal_dong_rows=4,
    )

    assert "| - | - | 실패 없음 | 0 | - |" in report
    assert "| 없음 | 0 | - |" in report
