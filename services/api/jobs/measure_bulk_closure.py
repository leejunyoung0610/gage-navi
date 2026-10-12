"""일괄 폐업일 규칙과 W0 방식 비교 (docs/10 §5 검증, T-015 수용 기준).

    python -m jobs.measure_bulk_closure --general PATH --rest PATH --bakery PATH \\
        --legal-dong PATH [--out PATH]

타당성 검증(ADR-020): 같은 층키에서 같은 호 또는 면적 ±1%인 다른 기록이 공식 폐업일 전에 이미
개업한 비율을 ① 새 규칙이 표시한 폐업 ② 표시 안 된 일반 폐업 ③ W0만 일괄로 본 날의 폐업으로
나눠 잰다. 통과 여부("①이 ②보다 뚜렷하게 높고 ③이 ②와 비슷")는 사람이 리포트를 보고 정한다.
W0 방식(일반음식점, 서울 전체 하루 100건 이상)과의 일치율은 참고값으로 함께 적는다.
"""

import argparse
import json
from dataclasses import dataclass
from datetime import date, datetime
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from pathlib import Path

import numpy as np
import pandas as pd

from app.address import legal_dong_file
from app.address.pnu import LegalDongIndex, parse_jibun, to_pnu
from app.location.ingest.license_file import (
    JIBUN_ADDR,
    ROAD_ADDR,
    SOURCE_TZ,
    inspect_file,
    iter_rows,
)
from app.location.normalize.bulk_closure import (
    CLOSED_ON,
    COUNT,
    JURISDICTION,
    MEDIAN_MULTIPLE,
    MIN_COUNT,
    detect_bulk_days,
    flag_bulk_closure,
)
from app.location.normalize.floor_parser import parse_floor, road_detail
from app.location.normalize.ho_parser import parse_ho

REPO_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_OUT = REPO_ROOT / "reports" / "bulk_closure.md"

JURISDICTION_COLUMN = "개방자치단체코드"
STATUS_COLUMN = "영업상태명"
CLOSED_ON_COLUMN = "폐업일자"
OPENED_ON_COLUMN = "인허가일자"
AREA_COLUMN = "소재지면적"
STATUS_CLOSED = "폐업"

CLOSED = "closed"
OPENED_ON = "opened_on"
PNU = "pnu"
FLOOR = "floor"
HO_LIST = "ho_list"
AREA = "area_x100"  # 면적(㎡) × 100, 정수. 없거나 0이면 NA

LICENSE_TYPE = "license_type"
GENERAL = "general_restaurant"
W0_MIN_COUNT = 100  # analysis/w0_location_signal.py: 서울 전체 하루 100건 이상 (일반음식점)
AREA_TOLERANCE_PERCENT = 1  # docs/10 §6: 면적 차이 ±1% 이내

# 타당성 검증의 묶음 (ADR-020)
GROUP_BULK = "① 새 규칙이 표시한 폐업"
GROUP_PLAIN = "② 표시 안 된 일반 폐업"
GROUP_W0_ONLY_DAY = "③ W0만 일괄로 본 날(탐지된 관할 없음)의 폐업"
GROUP_W0_OTHER = "(참고) 탐지된 관할이 있는 W0 일괄 폐업일의 다른 관할 폐업"
GROUPS = (GROUP_BULK, GROUP_PLAIN, GROUP_W0_ONLY_DAY, GROUP_W0_OTHER)
ERAS = (
    (None, 2000, "~1999"),
    (2000, 2010, "2000~2009"),
    (2010, 2020, "2010~2019"),
    (2020, None, "2020~"),
)
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


@dataclass(frozen=True)
class GroupRate:
    group: str
    era: str | None  # 폐업 연도 구간. 전체면 `None`
    records: int  # 묶음의 폐업 기록
    eligible: int  # 그중 층키·개업일·폐업일이 모두 있는 기록 (분모)
    successor: int  # 같은 호 또는 면적 ±1%인 기록이 폐업일 전에 이미 개업
    by_ho: int
    by_area: int


def parse_area_x100(value: str) -> int | None:
    """`소재지면적` → 면적 × 100 (정수). 비었거나 숫자가 아니거나 0 이하면 `None`."""
    try:
        scaled = Decimal(value.strip().replace(",", "")) * 100
    except InvalidOperation:
        return None
    if not scaled.is_finite() or scaled <= 0:
        return None
    return int(scaled.to_integral_value(rounding=ROUND_HALF_UP))


def read_records(files: dict[str, Path], index: LegalDongIndex) -> pd.DataFrame:
    """파일의 모든 행을 층키·호·면적·날짜가 붙은 기록으로 읽는다 (T-011·T-012·T-013 함수 사용)."""
    rows = []
    for license_type, path in files.items():
        for row in iter_rows(path, inspect_file(path).encoding):
            parts = parse_jibun(row[JIBUN_ADDR])
            tail = None if parts is None else parts.tail
            detail = road_detail(row[ROAD_ADDR])
            rows.append(
                (
                    row[JURISDICTION_COLUMN].strip(),
                    row[STATUS_COLUMN].strip() == STATUS_CLOSED,
                    row[CLOSED_ON_COLUMN].strip(),
                    row[OPENED_ON_COLUMN].strip(),
                    license_type,
                    None if parts is None else to_pnu(parts, index),
                    parse_floor(tail, detail).floor,
                    tuple(parse_ho(tail, detail).ho_list),
                    parse_area_x100(row[AREA_COLUMN]),
                )
            )
    frame = pd.DataFrame(
        rows,
        columns=[
            JURISDICTION,
            CLOSED,
            CLOSED_ON,
            OPENED_ON,
            LICENSE_TYPE,
            PNU,
            FLOOR,
            HO_LIST,
            AREA,
        ],
    )
    for column in (CLOSED_ON, OPENED_ON):
        frame[column] = pd.to_datetime(frame[column], errors="coerce")
    frame[AREA] = frame[AREA].astype("Int64")
    return frame


def _w0_mask(target: pd.DataFrame) -> "tuple[pd.Series[bool], pd.Index[pd.Timestamp]]":
    general = target[LICENSE_TYPE] == GENERAL
    per_day = target.loc[general, CLOSED_ON].value_counts()
    w0_dates = per_day[per_day >= W0_MIN_COUNT].index
    return general & target[CLOSED_ON].isin(w0_dates), w0_dates


def group_labels(closed: pd.DataFrame) -> "pd.Series[str]":
    """폐업일자가 있는 폐업 기록마다 타당성 검증의 묶음 이름. 인덱스는 `closed`의 것."""
    target = closed.dropna(subset=[CLOSED_ON])
    w0, _ = _w0_mask(target)
    flags = flag_bulk_closure(target, detect_bulk_days(target))
    hit_dates = target.loc[w0 & flags, CLOSED_ON].unique()
    on_hit_day = target[CLOSED_ON].isin(hit_dates)
    labels = pd.Series(GROUP_PLAIN, index=target.index, name="group")
    labels[w0 & ~flags & on_hit_day] = GROUP_W0_OTHER
    labels[w0 & ~flags & ~on_hit_day] = GROUP_W0_ONLY_DAY
    labels[flags] = GROUP_BULK
    return labels


def successor_flags(records: pd.DataFrame) -> pd.DataFrame:
    """기록 A마다: 같은 층키에서 A보다 나중에, A의 폐업일 전에 개업한 기록 B가 있는가.

    `by_ho`는 `ho_list`가 하나 이상 겹치는 B, `by_area`는 면적 차이가 큰 쪽의 1% 이하인 B.
    `eligible`은 A가 폐업 기록이고 층키·개업일·폐업일이 모두 있다는 뜻이다. B는 영업 중이어도 된다.
    """
    out = pd.DataFrame({"eligible": False, "by_ho": False, "by_area": False}, index=records.index)
    keyed = records.dropna(subset=[PNU, FLOOR, OPENED_ON])
    eligible = keyed[CLOSED] & keyed[CLOSED_ON].notna()
    out.loc[eligible[eligible].index, "eligible"] = True
    by_ho: list[object] = []
    by_area: list[object] = []
    for _, group in keyed.groupby([PNU, FLOOR], sort=False):
        ok = eligible[group.index].to_numpy()
        if len(group) < 2 or not ok.any():
            continue
        opened = group[OPENED_ON].to_numpy()
        closed_on = group[CLOSED_ON].to_numpy()
        area = group[AREA].to_numpy(dtype="float64", na_value=np.nan)
        hos = [set(ho) for ho in group[HO_LIST]]
        labels = group.index.to_list()
        for position in np.flatnonzero(ok):
            later = (opened > opened[position]) & (opened < closed_on[position])
            if not later.any():
                continue
            # 면적은 × 100 정수라 2^53 미만에서 float64 연산이 정확하다
            gap = np.abs(area - area[position]) * 100
            near = later & (gap <= AREA_TOLERANCE_PERCENT * np.maximum(area, area[position]))
            if near.any():
                by_area.append(labels[position])
            mine = hos[position]
            if mine and any(mine & hos[other] for other in np.flatnonzero(later)):
                by_ho.append(labels[position])
    out.loc[by_ho, "by_ho"] = True
    out.loc[by_area, "by_area"] = True
    return out


def _era(year: "pd.Series[int]", start: int | None, end: int | None) -> "pd.Series[bool]":
    mask = pd.Series(True, index=year.index)
    if start is not None:
        mask &= year >= start
    if end is not None:
        mask &= year < end
    return mask


def validity(records: pd.DataFrame) -> tuple[GroupRate, ...]:
    """묶음별(전체, 그리고 폐업 연도 구간별) 비율."""
    closed = records[records[CLOSED]]
    labels = group_labels(closed)
    flags = successor_flags(records).loc[labels.index]
    year = records.loc[labels.index, CLOSED_ON].dt.year
    rates = []
    for era_start, era_end, era_name in ((None, None, None), *ERAS):
        in_era = _era(year, era_start, era_end)
        for group in GROUPS:
            rows = flags[(labels == group) & in_era]
            eligible = rows[rows["eligible"]]
            rates.append(
                GroupRate(
                    group=group,
                    era=era_name,
                    records=len(rows),
                    eligible=len(eligible),
                    successor=int((eligible["by_ho"] | eligible["by_area"]).sum()),
                    by_ho=int(eligible["by_ho"].sum()),
                    by_area=int(eligible["by_area"].sum()),
                )
            )
    return tuple(rates)


def compare(closed: pd.DataFrame) -> Comparison:
    """`closed`: 폐업 기록의 `jurisdiction`, `closed_on`(없으면 NaT), `license_type`."""
    target = closed.dropna(subset=[CLOSED_ON]).reset_index(drop=True)
    w0, w0_dates = _w0_mask(target)

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


def _rate_rows(rates: tuple[GroupRate, ...], era: str | None) -> list[str]:
    return [
        f"| {rate.group} | {rate.records:,} | {rate.eligible:,} | {rate.successor:,} "
        f"| **{_percent(rate.successor, rate.eligible)}** | {_percent(rate.by_ho, rate.eligible)} "
        f"| {_percent(rate.by_area, rate.eligible)} |"
        for rate in rates
        if rate.era == era
    ]


def render_report(
    result: Comparison,
    rates: tuple[GroupRate, ...],
    measured_on: date,
    files: list[str],
    file_rows: int,
) -> str:
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
        "## 타당성 검증 (수용 기준, ADR-020)",
        "",
        "같은 층키(PNU+층)에서 같은 호(`ho_list` 겹침) 또는 면적 ±1%인 다른 기록이, 이 기록보다 "
        "나중에 그리고 이 기록의 공식 폐업일 전에 이미 개업한 비율. 분모는 층키·개업일·폐업일이 "
        "모두 있는 폐업 기록. **①이 ②보다 뚜렷하게 높고 ③이 ②와 비슷하면 통과**"
        "(판정은 사람이 한다).",
        "",
        "| 묶음 | 폐업 기록 | 분모 | 해당 | 비율 | 같은 호 | 면적 ±1% |",
        "|---|---|---|---|---|---|---|",
        *_rate_rows(rates, None),
        "",
        "### 폐업 연도 구간별",
        "",
        "일괄 정리는 특정 시기에 몰려 있어, 층 정보가 있는 비율과 건물의 기록 밀도가 시기마다 "
        "다른 영향을 따로 본다.",
    ]
    for _, _, era in ERAS:
        lines += [
            "",
            f"**{era}**",
            "",
            "| 묶음 | 폐업 기록 | 분모 | 해당 | 비율 | 같은 호 | 면적 ±1% |",
            "|---|---|---|---|---|---|---|",
            *_rate_rows(rates, era),
        ]
    lines += [
        "",
        "## W0 방식과의 일치 (참고값, 기준 아님)",
        "",
        f"- 새 규칙이 탐지한 (관할, 날짜): {result.bulk_cells:,} (서로 다른 날짜 "
        f"{result.bulk_dates:,}일), 기록 {result.bulk_records:,}",
        f"- W0 일괄 폐업일: {result.w0_days:,}일, 기록 {result.w0_records:,}",
        f"- W0 기록 중 새 규칙도 표시한 기록: {result.covered:,}",
        f"- 비율: {_percent(result.covered, result.w0_records)}",
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
    parser.add_argument("--legal-dong", type=Path, required=True, help="법정동코드 CSV")
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT, help="리포트 경로")
    args = parser.parse_args(argv)

    files = {GENERAL: args.general, "rest_restaurant": args.rest, "bakery": args.bakery}
    dongs, _ = legal_dong_file.read_file(args.legal_dong)
    index = LegalDongIndex.from_rows((dong.code, dong.full_name, dong.abolished) for dong in dongs)
    records = read_records(files, index)
    file_rows = len(records)
    result = compare(records[records[CLOSED]])
    rates = validity(records)
    report = render_report(
        result,
        rates,
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
        "w0_coverage_percent": None if percent is None else str(round(percent, 4)),
        **{
            f"successor_rate_{number}": _percent(rate.successor, rate.eligible)
            for number, rate in enumerate(rates[: len(GROUPS)], start=1)
        },
        "out": str(args.out),
    }
    print(json.dumps(line, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
