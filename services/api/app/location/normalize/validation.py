"""데이터 검증 DV1~DV10 판정 (docs/50 §2). 집계는 `records.normalize`가 한다."""

from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal
from typing import Any

from app.location.normalize.records import PARSE_VERSION, TypeStats

PASS, FAIL, WARN, RECORDED, SKIPPED = "pass", "fail", "warn", "recorded", "skipped"

ROW_CHANGE_MAX = Decimal("0.05")  # DV1
OPENED_PARSED_MIN = Decimal("0.99")  # DV3
PNU_FAILURE_MAX = Decimal("0.005")  # DV6: 이 값 이상이면 실패
FLOOR_RATIO_CHANGE_MAX = Decimal("0.03")  # DV7
COORDS_OUTSIDE_MAX = Decimal("0.01")  # DV8
CLOSED_WITHOUT_DATE_MAX = Decimal("0.001")  # DV10

_RATIO = Decimal("0.000001")


@dataclass(frozen=True)
class Previous:
    """같은 종류의 가장 최근 `validated` 스냅샷에서 읽은 비교 값."""

    row_count: int
    floor_ratio: Decimal | None


def ratio(part: int, whole: int) -> Decimal | None:
    if whole == 0:
        return None
    return (Decimal(part) / Decimal(whole)).quantize(_RATIO, rounding=ROUND_HALF_UP)


def _text(value: Decimal | None) -> str | None:
    return None if value is None else str(value)


def build_validation(
    stat: TypeStats, previous: Previous | None, surge_cells: int, surge_dates: int
) -> dict[str, Any]:
    """스냅샷 하나의 `validation.normalize` 값. `passed`가 거짓이면 실패 검사가 있다."""
    checks: dict[str, dict[str, Any]] = {}

    if previous is None or previous.row_count == 0:
        checks["DV1"] = {"result": SKIPPED, "rows": stat.input_rows, "previous_rows": None}
    else:
        change = ratio(abs(stat.input_rows - previous.row_count), previous.row_count)
        assert change is not None
        checks["DV1"] = {
            "result": FAIL if change > ROW_CHANGE_MAX else PASS,
            "rows": stat.input_rows,
            "previous_rows": previous.row_count,
            "change": str(change),
        }

    checks["DV2"] = {
        "result": FAIL if stat.duplicate_mgmt_no else PASS,
        "duplicates": stat.duplicate_mgmt_no,
    }

    parsed = ratio(stat.opened_on_parsed, stat.seoul_rows)
    checks["DV3"] = {
        "result": FAIL if parsed is not None and parsed < OPENED_PARSED_MIN else PASS,
        "parsed": stat.opened_on_parsed,
        "rows": stat.seoul_rows,
        "ratio": _text(parsed),
    }

    checks["DV4"] = {
        "result": WARN if stat.date_inversion else PASS,
        "isolated": stat.date_inversion,
    }

    checks["DV5"] = {
        "result": FAIL if stat.unknown_status else PASS,
        "unknown": stat.unknown_status,
    }

    pnu_failure = ratio(stat.pnu_failed, stat.seoul_rows)
    checks["DV6"] = {
        "result": FAIL if pnu_failure is not None and pnu_failure >= PNU_FAILURE_MAX else PASS,
        "failed": stat.pnu_failed,
        "rows": stat.seoul_rows,
        "ratio": _text(pnu_failure),
        "by_reason": stat.pnu_failures,
        "abolished_only": stat.pnu_abolished_only,
    }

    floor_ratio = ratio(stat.since_2005_with_floor, stat.since_2005)
    dv7: dict[str, Any] = {
        "ratio": _text(floor_ratio),
        "previous_ratio": None,
        "with_floor": stat.since_2005_with_floor,
        "rows": stat.since_2005,
    }
    if previous is None or previous.floor_ratio is None or floor_ratio is None:
        dv7["result"] = SKIPPED
    else:
        dv7["previous_ratio"] = str(previous.floor_ratio)
        changed = abs(floor_ratio - previous.floor_ratio) > FLOOR_RATIO_CHANGE_MAX
        dv7["result"] = WARN if changed else PASS
    checks["DV7"] = dv7

    outside = ratio(stat.coords_outside, stat.with_coords)
    checks["DV8"] = {
        "result": WARN if outside is not None and outside > COORDS_OUTSIDE_MAX else PASS,
        "outside": stat.coords_outside,
        "with_coords": stat.with_coords,
        "ratio": _text(outside),
    }

    checks["DV9"] = {
        "result": RECORDED,
        "surge_cells": surge_cells,  # 식품 3종 합산으로 탐지한 (관할, 날짜) 수
        "surge_dates": surge_dates,
        "records": stat.surge_records,  # 이 종류의 기록 중 표시된 것
    }

    without_date = ratio(stat.closed_without_date, stat.closed)
    over = without_date is not None and without_date > CLOSED_WITHOUT_DATE_MAX
    checks["DV10"] = {
        "result": WARN if over else PASS,
        "closed_without_date": stat.closed_without_date,
        "closed": stat.closed,
        "ratio": _text(without_date),
    }

    failed = sorted(name for name, check in checks.items() if check["result"] == FAIL)
    warned = sorted(name for name, check in checks.items() if check["result"] == WARN)
    return {
        "parse_version": PARSE_VERSION,
        "passed": not failed,
        "failed": failed,
        "warnings": warned,
        "checks": checks,
        "input_rows": stat.input_rows,
        "non_seoul_excluded": stat.non_seoul_excluded,
        "records": stat.records,
        "no_fixed_place": stat.no_fixed_place,
        "floor_conflict": stat.floor_conflict,
        "ho_conflict": stat.ho_conflict,
        "status_counts": stat.status_counts,
        "category_counts": stat.category_counts,
    }
