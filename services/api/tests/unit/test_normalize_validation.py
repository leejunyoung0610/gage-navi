"""DV1~DV10 판정 (docs/50 §2, T-016). 검사마다 실패·경고를 유도하는 가상 집계를 쓴다."""

from dataclasses import replace
from decimal import Decimal

import pytest

from app.location.normalize.records import TypeStats
from app.location.normalize.validation import Previous, build_validation, ratio

# 모든 검사를 통과하는 가상 집계
CLEAN = TypeStats(
    input_rows=1000,
    seoul_rows=1000,
    opened_on_parsed=1000,
    records=1000,
    status_counts={"영업/정상": 400, "폐업": 600},
    category_counts={"한식": 1000},
    pnu_failed=4,
    pnu_failures={"regex_mismatch": 4},
    since_2005=500,
    since_2005_with_floor=400,
    with_coords=900,
    coords_outside=9,
    closed=600,
    surge_records=30,
)
PREVIOUS = Previous(row_count=1000, floor_ratio=Decimal("0.80"))


def check(stat: TypeStats, name: str, previous: Previous | None = PREVIOUS) -> dict[str, object]:
    result: dict[str, object] = build_validation(stat, previous, 3, 2)["checks"][name]
    return result


def test_clean_snapshot_passes_everything() -> None:
    validation = build_validation(CLEAN, PREVIOUS, 3, 2)
    assert validation["passed"] and validation["failed"] == [] and validation["warnings"] == []
    results = {name: check["result"] for name, check in validation["checks"].items()}
    assert results == {f"DV{n}": "pass" for n in range(1, 11)} | {"DV9": "recorded"}
    assert validation["checks"]["DV9"] == {
        "result": "recorded",
        "surge_cells": 3,
        "surge_dates": 2,
        "records": 30,
    }


def test_first_load_skips_comparisons() -> None:
    validation = build_validation(CLEAN, None, 0, 0)
    assert validation["passed"]
    assert validation["checks"]["DV1"]["result"] == "skipped"
    assert validation["checks"]["DV7"]["result"] == "skipped"
    assert validation["checks"]["DV7"]["ratio"] == "0.800000"


@pytest.mark.parametrize(
    ("name", "stat", "expected"),
    [
        ("DV1", replace(CLEAN, input_rows=1051), "fail"),  # +5.1%
        ("DV1", replace(CLEAN, input_rows=1050), "pass"),  # 정확히 +5%
        ("DV1", replace(CLEAN, input_rows=949), "fail"),  # −5.1%
        ("DV2", replace(CLEAN, duplicate_mgmt_no=1), "fail"),
        ("DV3", replace(CLEAN, opened_on_parsed=989), "fail"),  # 98.9%
        ("DV3", replace(CLEAN, opened_on_parsed=990), "pass"),  # 정확히 99%
        ("DV4", replace(CLEAN, date_inversion=1), "warn"),
        ("DV5", replace(CLEAN, unknown_status={"직권말소": 1}), "fail"),
        ("DV6", replace(CLEAN, pnu_failed=5), "fail"),  # 정확히 0.5%는 실패
        ("DV6", replace(CLEAN, pnu_failed=4), "pass"),
        ("DV7", replace(CLEAN, since_2005_with_floor=384), "warn"),  # 76.8%, −3.2%p
        ("DV7", replace(CLEAN, since_2005_with_floor=415), "pass"),  # 83.0%, 정확히 +3%p
        ("DV8", replace(CLEAN, coords_outside=10), "warn"),  # 1.11%
        ("DV8", replace(CLEAN, coords_outside=9), "pass"),  # 정확히 1%
        ("DV10", replace(CLEAN, closed_without_date=1), "warn"),  # 0.17%
        ("DV10", replace(CLEAN, closed=1000, closed_without_date=1), "pass"),  # 정확히 0.1%
    ],
)
def test_each_check_boundary(name: str, stat: TypeStats, expected: str) -> None:
    assert check(stat, name)["result"] == expected


@pytest.mark.parametrize("name", ["DV1", "DV2", "DV3", "DV5", "DV6"])
def test_failing_checks_fail_the_snapshot(name: str) -> None:
    broken = {
        "DV1": replace(CLEAN, input_rows=2000),
        "DV2": replace(CLEAN, duplicate_mgmt_no=2),
        "DV3": replace(CLEAN, opened_on_parsed=100),
        "DV5": replace(CLEAN, unknown_status={"가상상태": 3}),
        "DV6": replace(CLEAN, pnu_failed=100),
    }[name]
    validation = build_validation(broken, PREVIOUS, 0, 0)
    assert not validation["passed"] and validation["failed"] == [name]


def test_warnings_do_not_fail_the_snapshot() -> None:
    warned = replace(
        CLEAN,
        date_inversion=2,
        since_2005_with_floor=100,
        coords_outside=500,
        closed_without_date=50,
    )
    validation = build_validation(warned, PREVIOUS, 0, 0)
    assert validation["passed"]
    assert validation["warnings"] == ["DV10", "DV4", "DV7", "DV8"]


def test_recorded_counts() -> None:
    stat = replace(CLEAN, non_seoul_excluded=3, no_fixed_place=7, floor_conflict=5, ho_conflict=9)
    validation = build_validation(stat, PREVIOUS, 0, 0)
    assert (
        validation["non_seoul_excluded"],
        validation["no_fixed_place"],
        validation["floor_conflict"],
        validation["ho_conflict"],
    ) == (3, 7, 5, 9)
    assert validation["status_counts"] == {"영업/정상": 400, "폐업": 600}
    assert validation["category_counts"] == {"한식": 1000}


def test_empty_snapshot_has_no_ratios() -> None:
    validation = build_validation(TypeStats(), None, 0, 0)
    assert validation["passed"]
    assert validation["checks"]["DV6"]["ratio"] is None
    assert ratio(1, 0) is None
