"""일괄 폐업일 규칙과 W0 방식 비교 (docs/10 §5 검증, T-015 수용 기준).

    python -m jobs.measure_bulk_closure --general PATH --rest PATH --bakery PATH [--out PATH]

W0 방식(일반음식점, 서울 전체 하루 100건 이상)이 일괄 폐업으로 분류한 기록 중 새 규칙
(관할별, 식품 3종 합산)도 `bulk_closure`로 표시한 비율을 재고 리포트를 쓴다.
기준(≥ 95%)에 못 미치면 종료 코드 1.
"""

import argparse
import json
from dataclasses import dataclass
from datetime import date, datetime
from decimal import ROUND_HALF_UP, Decimal
from pathlib import Path

import pandas as pd

from app.location.ingest.license_file import SOURCE_TZ, inspect_file, iter_rows
from app.location.normalize.bulk_closure import (
    CLOSED_ON,
    COUNT,
    JURISDICTION,
    MEDIAN_MULTIPLE,
    MIN_COUNT,
    detect_bulk_days,
    flag_bulk_closure,
)

REPO_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_OUT = REPO_ROOT / "reports" / "bulk_closure.md"

JURISDICTION_COLUMN = "개방자치단체코드"
STATUS_COLUMN = "영업상태명"
CLOSED_ON_COLUMN = "폐업일자"
STATUS_CLOSED = "폐업"

LICENSE_TYPE = "license_type"
GENERAL = "general_restaurant"
W0_MIN_COUNT = 100  # analysis/w0_location_signal.py: 서울 전체 하루 100건 이상 (일반음식점)
THRESHOLD_PERCENT = Decimal("95")
# 임계값 민감도: (최소 건수, 중앙값 배수). 첫 줄이 문서 값
SENSITIVITY = ((MIN_COUNT, MEDIAN_MULTIPLE), (30, 5), (20, 10), (20, 5), (10, 10), (10, 5))
TOP_N = 10


@dataclass(frozen=True)
class MissedDay:
    closed_on: date
    w0_records: int
    max_jurisdiction_count: int  # 그날 관할별 건수(3종 합산) 중 최댓값


@dataclass(frozen=True)
class Comparison:
    closed_records: int  # 대상: 폐업이고 폐업일자가 있는 기록 (3종)
    bulk_cells: int  # 탐지된 (관할, 날짜) 수
    bulk_dates: int  # 탐지된 서로 다른 날짜 수
    bulk_records: int
    bulk_only_records: int  # 새 규칙만 표시하고 W0는 일괄로 보지 않은 기록
    w0_days: int
    w0_records: int
    covered: int  # W0 기록 중 새 규칙도 표시한 기록
    hit_days: int  # W0 일괄 폐업일 중 탐지된 관할이 하나 이상 있는 날
    hit_day_records: int
    miss_days: int
    miss_day_records: int
    missed_max_cell: int  # 놓친 W0 기록이 속한 (관할, 날짜) 건수의 최댓값
    sensitivity: tuple[tuple[int, int, int, int], ...]  # (최소 건수, 배수, 표시 기록, covered)
    top_missed_days: tuple[MissedDay, ...]

    @property
    def coverage_percent(self) -> Decimal | None:
        if self.w0_records == 0:
            return None
        return Decimal(100 * self.covered) / Decimal(self.w0_records)

    @property
    def passed(self) -> bool:
        percent = self.coverage_percent
        return percent is not None and percent >= THRESHOLD_PERCENT


def read_closures(files: dict[str, Path]) -> tuple[pd.DataFrame, int]:
    """폐업 기록의 (`jurisdiction`, `closed_on`, `license_type`)과 파일 전체 행 수."""
    rows: list[tuple[str, str, str]] = []
    total = 0
    for license_type, path in files.items():
        for row in iter_rows(path, inspect_file(path).encoding):
            total += 1
            if row[STATUS_COLUMN].strip() == STATUS_CLOSED:
                rows.append(
                    (row[JURISDICTION_COLUMN].strip(), row[CLOSED_ON_COLUMN].strip(), license_type)
                )
    frame = pd.DataFrame(rows, columns=[JURISDICTION, CLOSED_ON, LICENSE_TYPE])
    frame[CLOSED_ON] = pd.to_datetime(frame[CLOSED_ON], errors="coerce")
    return frame, total


def compare(closed: pd.DataFrame) -> Comparison:
    """`closed`: 폐업 기록의 `jurisdiction`, `closed_on`(없으면 NaT), `license_type`."""
    target = closed.dropna(subset=[CLOSED_ON]).reset_index(drop=True)
    general = target[LICENSE_TYPE] == GENERAL
    per_day = target.loc[general, CLOSED_ON].value_counts()
    w0_dates = per_day[per_day >= W0_MIN_COUNT].index
    w0 = general & target[CLOSED_ON].isin(w0_dates)

    days = detect_bulk_days(target)
    flags = flag_bulk_closure(target, days)

    w0_rows = target[w0].assign(flag=flags[w0])
    by_day = w0_rows.groupby(CLOSED_ON)["flag"].agg(["size", "sum"])
    hit = by_day[by_day["sum"] > 0]
    miss = by_day[by_day["sum"] == 0]

    cell_size = target.groupby([JURISDICTION, CLOSED_ON])[CLOSED_ON].transform("size")
    missed_cells = cell_size[w0 & ~flags]
    day_max = cell_size.groupby(target[CLOSED_ON]).max()
    top = miss.sort_values("size", ascending=False, kind="stable").head(TOP_N)

    sensitivity = []
    for min_count, multiple in SENSITIVITY:
        other = flag_bulk_closure(target, detect_bulk_days(target, min_count, multiple))
        sensitivity.append((min_count, multiple, int(other.sum()), int((other & w0).sum())))

    return Comparison(
        closed_records=len(target),
        bulk_cells=len(days),
        bulk_dates=int(days[CLOSED_ON].nunique()),
        bulk_records=int(days[COUNT].sum()),
        bulk_only_records=int((flags & ~w0).sum()),
        w0_days=len(w0_dates),
        w0_records=int(w0.sum()),
        covered=int((flags & w0).sum()),
        hit_days=len(hit),
        hit_day_records=int(hit["size"].sum()),
        miss_days=len(miss),
        miss_day_records=int(miss["size"].sum()),
        missed_max_cell=0 if missed_cells.empty else int(missed_cells.max()),
        sensitivity=tuple(sensitivity),
        top_missed_days=tuple(
            MissedDay(day.date(), int(size), int(day_max.loc[day]))
            for day, size in zip(pd.DatetimeIndex(top.index), top["size"], strict=True)
        ),
    )


def _percent(part: int, whole: int) -> str:
    if whole == 0:
        return "—"
    value = Decimal(100 * part) / Decimal(whole)
    return f"{value.quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)}%"


def render_report(result: Comparison, measured_on: date, files: list[str], file_rows: int) -> str:
    verdict = "통과" if result.passed else "미달"
    hit_rest = result.hit_day_records - result.covered
    lines = [
        "# 일괄 폐업일 규칙과 W0 방식 비교 (T-015, docs/10 §5)",
        "",
        "`python -m jobs.measure_bulk_closure`가 만든 파일이다. 손으로 고치지 않는다.",
        "",
        f"- 측정일: {measured_on.isoformat()}",
        f"- 파일: {', '.join(files)}",
        f"- 파일 전체 행: {file_rows:,} / 대상(폐업이고 폐업일자 있음): {result.closed_records:,}",
        f"- 새 규칙: 관할별 하루 {MIN_COUNT}건 이상이고 관할 중앙값의 {MEDIAN_MULTIPLE}배 이상"
        " (식품 3종 합산)",
        f"- W0 방식: 일반음식점, 서울 전체 하루 {W0_MIN_COUNT}건 이상",
        "",
        "## 결과",
        "",
        f"- 새 규칙이 탐지한 (관할, 날짜): {result.bulk_cells:,} (서로 다른 날짜 "
        f"{result.bulk_dates:,}일), 기록 {result.bulk_records:,}",
        f"- W0 일괄 폐업일: {result.w0_days:,}일, 기록 {result.w0_records:,}",
        f"- W0 기록 중 새 규칙도 표시한 기록: {result.covered:,}",
        f"- **비율: {_percent(result.covered, result.w0_records)}** "
        f"(기준 ≥ {THRESHOLD_PERCENT}% → {verdict})",
        f"- 새 규칙만 표시한 기록(W0는 일괄로 보지 않음): {result.bulk_only_records:,}",
        "",
        "## 놓친 기록의 구성",
        "",
        "| W0 일괄 폐업일 | 날 수 | W0 기록 | 새 규칙도 표시 | 표시 안 함 |",
        "|---|---|---|---|---|",
        f"| 탐지된 관할이 하나 이상 있는 날 | {result.hit_days:,} | {result.hit_day_records:,} "
        f"| {result.covered:,} | {hit_rest:,} |",
        f"| 탐지된 관할이 없는 날 | {result.miss_days:,} | {result.miss_day_records:,} | 0 "
        f"| {result.miss_day_records:,} |",
        "",
        f"- 놓친 W0 기록이 속한 (관할, 날짜)의 건수(3종 합산) 최댓값: {result.missed_max_cell}",
        "",
        "## 임계값 민감도",
        "",
        "| 최소 건수 | 중앙값 배수 | 표시 기록 | W0 기록 중 표시 | 비율 |",
        "|---|---|---|---|---|",
    ]
    lines += [
        f"| {min_count} | {multiple} | {records:,} | {covered:,} "
        f"| {_percent(covered, result.w0_records)} |"
        for min_count, multiple, records, covered in result.sensitivity
    ]
    lines += [
        "",
        f"## 탐지된 관할이 없는 W0 일괄 폐업일 상위 {TOP_N}",
        "",
        "| 날짜 | W0 기록(일반음식점, 서울 전체) | 그날 관할별 건수 최댓값(3종 합산) |",
        "|---|---|---|",
    ]
    lines += [
        f"| {day.closed_on.isoformat()} | {day.w0_records:,} | {day.max_jurisdiction_count} |"
        for day in result.top_missed_days
    ]
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="jobs.measure_bulk_closure", description="일괄 폐업일 규칙과 W0 방식 비교"
    )
    parser.add_argument("--general", type=Path, required=True, help="일반음식점 원천 CSV")
    parser.add_argument("--rest", type=Path, required=True, help="휴게음식점 원천 CSV")
    parser.add_argument("--bakery", type=Path, required=True, help="제과점영업 원천 CSV")
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT, help="리포트 경로")
    args = parser.parse_args(argv)

    files = {GENERAL: args.general, "rest_restaurant": args.rest, "bakery": args.bakery}
    closed, file_rows = read_closures(files)
    result = compare(closed)
    report = render_report(
        result,
        measured_on=datetime.now(SOURCE_TZ).date(),
        files=[path.name for path in files.values()],
        file_rows=file_rows,
    )
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(report, encoding="utf-8")
    percent = result.coverage_percent
    line = {
        "job": "measure_bulk_closure",
        "bulk_cells": result.bulk_cells,
        "bulk_records": result.bulk_records,
        "w0_days": result.w0_days,
        "w0_records": result.w0_records,
        "covered": result.covered,
        "coverage_percent": None if percent is None else str(round(percent, 4)),
        "out": str(args.out),
    }
    print(json.dumps(line, ensure_ascii=False))
    return 0 if result.passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
