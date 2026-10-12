"""미갱신 의심 표시와 리포트 (docs/10 §6, T-017).

    python -m jobs.flag_stale_suspects [--out reports/stale_suspect.md]

`license_record`를 읽어 `stale_suspect`(같은 호)·`stale_area_match`(같은 면적 ±1%)를 전체 기록에
다시 쓰고, 근거별 건수와 같은 가게로 보아 뺀 건수를 리포트로 남긴다. 정규화
(`jobs.normalize_licenses`) 뒤에 실행한다. 같은 데이터로 다시 실행하면 같은 결과가 된다.
"""

import argparse
import asyncio
import json
from dataclasses import dataclass
from datetime import date, datetime
from decimal import ROUND_HALF_UP, Decimal
from pathlib import Path

import pandas as pd
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from app.core.db import get_engine
from app.location.ingest.license_file import SOURCE_TZ
from app.location.normalize.stale import SAME_AREA, SAME_HO, StaleResult, detect_stale

REPO_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_OUT = REPO_ROOT / "reports" / "stale_suspect.md"

LICENSE_LABELS = {
    "general_restaurant": "일반음식점",
    "rest_restaurant": "휴게음식점",
    "bakery": "제과점영업",
}
CROWDED_FLOOR = 10  # 한 층키에 같은 호 근거 기록이 이만큼 이상이면 "몰린 층"으로 센다
TOP_FLOORS = 10

_RECORDS = """
SELECT id, license_type, name, status, opened_on, area_m2, pnu, floor, ho_list, no_fixed_place
FROM license_record
"""
_STAGING = """
CREATE TEMP TABLE stale_staging (id BIGINT PRIMARY KEY, same_ho BOOLEAN, same_area BOOLEAN)
ON COMMIT DROP
"""
_APPLY = """
UPDATE license_record r
SET stale_suspect = coalesce(s.same_ho, false), stale_area_match = coalesce(s.same_area, false)
FROM license_record target LEFT JOIN stale_staging s ON s.id = target.id
WHERE r.id = target.id
  AND (r.stale_suspect, r.stale_area_match)
      IS DISTINCT FROM (coalesce(s.same_ho, false), coalesce(s.same_area, false))
"""


@dataclass(frozen=True)
class Summary:
    records: int
    open_records: int
    result: StaleResult
    ho_only: int
    both: int
    area_only: int
    by_license: dict[str, tuple[int, int, int]]  # 종류 → (영업 중, 같은 호, 같은 면적)
    crowded_floors: int  # 같은 호 근거 기록이 CROWDED_FLOOR건 이상인 층키 수
    crowded_records: int
    top_floor_counts: tuple[int, ...]

    @property
    def same_ho(self) -> int:
        return self.ho_only + self.both

    @property
    def same_area(self) -> int:
        return self.area_only + self.both


def summarize(records: pd.DataFrame, result: StaleResult) -> Summary:
    """`records`: `_RECORDS`의 열. 리포트에 쓸 집계만 만든다 (업소 이름은 넣지 않는다)."""
    flags = result.flags.set_index("id")
    ho = records["id"].map(flags[SAME_HO]).eq(True)
    area = records["id"].map(flags[SAME_AREA]).eq(True)
    is_open = records["status"] == "open"
    by_license = {
        str(kind): (
            int((is_open & (records["license_type"] == kind)).sum()),
            int((ho & (records["license_type"] == kind)).sum()),
            int((area & (records["license_type"] == kind)).sum()),
        )
        for kind in LICENSE_LABELS
    }
    per_floor = records[ho].groupby(["pnu", "floor"]).size().sort_values(ascending=False)
    crowded = per_floor[per_floor >= CROWDED_FLOOR]
    return Summary(
        records=len(records),
        open_records=int(is_open.sum()),
        result=result,
        ho_only=int((ho & ~area).sum()),
        both=int((ho & area).sum()),
        area_only=int((area & ~ho).sum()),
        by_license=by_license,
        crowded_floors=len(crowded),
        crowded_records=int(crowded.sum()),
        top_floor_counts=tuple(int(count) for count in per_floor.head(TOP_FLOORS)),
    )


def _percent(part: int, whole: int) -> str:
    if whole == 0:
        return "—"
    value = Decimal(100 * part) / Decimal(whole)
    return f"{value.quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)}%"


def render_report(summary: Summary, measured_on: date) -> str:
    result = summary.result
    ho_lost = result.ho_records_before - summary.same_ho
    area_lost = result.area_records_before - summary.same_area
    lines = [
        "# 미갱신 의심 표시 (T-017, docs/10 §6, ADR-023)",
        "",
        "`python -m jobs.flag_stale_suspects`가 만든 파일이다. 손으로 고치지 않는다.",
        "",
        f"- 측정일: {measured_on.isoformat()}",
        f"- `license_record` {summary.records:,}건 중 영업 중 {summary.open_records:,}건",
        "- 대상(영업 중이고 층키·개업일이 있으며 고정된 자리가 있는 기록): "
        f"{result.candidates:,}건",
        f"- 같은 층키에서 대상보다 나중에 개업한 기록과의 쌍: {result.later_pairs:,}",
        "",
        "## 근거별 표시 기록",
        "",
        "| 근거 | 컬럼 | 기록 | 대상 대비 | 쓰는 곳 |",
        "|---|---|---|---|---|",
        f"| 같은 호 | `stale_suspect` | **{summary.same_ho:,}** "
        f"| {_percent(summary.same_ho, result.candidates)} | 화면 배지, 민감도 분석 |",
        f"| 같은 면적(±1%) | `stale_area_match` | **{summary.same_area:,}** "
        f"| {_percent(summary.same_area, result.candidates)} | 민감도 분석에만 |",
        "",
        "| 겹침 | 기록 |",
        "|---|---|",
        f"| 같은 호만 | {summary.ho_only:,} |",
        f"| 같은 호이고 면적도 같음 | {summary.both:,} |",
        f"| 면적만 같음 (화면에 내지 않는다) | {summary.area_only:,} |",
        f"| 합계 (하나라도) | {summary.ho_only + summary.both + summary.area_only:,} |",
        "",
        "## 같은 가게로 보아 뺀 쌍",
        "",
        "사업장명을 정규화한 뒤 두 이름이 같거나 한쪽이 다른 쪽을 포함하는 쌍. "
        "한 가게가 같은 자리에 인허가 기록을 여러 개 가진 경우다.",
        "",
        "| 근거 | 쌍 (빼기 전) | 같은 가게로 뺀 쌍 | 기록 (빼기 전) | 기록 (뺀 뒤) "
        "| 표시가 사라진 기록 |",
        "|---|---|---|---|---|---|",
        f"| 같은 호 | {result.ho_pairs:,} | {result.ho_pairs_same_name:,} "
        f"| {result.ho_records_before:,} | {summary.same_ho:,} | {ho_lost:,} |",
        f"| 같은 면적(±1%) | {result.area_pairs:,} | {result.area_pairs_same_name:,} "
        f"| {result.area_records_before:,} | {summary.same_area:,} | {area_lost:,} |",
        "",
        "## 인허가 종류별",
        "",
        "| 종류 | 영업 중 | 같은 호 | 같은 면적(±1%) |",
        "|---|---|---|---|",
    ]
    lines += [
        f"| {LICENSE_LABELS[kind]} | {opened:,} | {ho:,} | {area:,} |"
        for kind, (opened, ho, area) in summary.by_license.items()
    ]
    counts = ", ".join(f"{count:,}" for count in summary.top_floor_counts) or "—"
    lines += [
        "",
        "## 한 층에 몰린 표시 (알려진 한계)",
        "",
        "한 호를 여러 사업자가 나눠 쓰는 곳(공유주방 등)은 서로 다른 가게가 동시에 영업하는데도 "
        "같은 호 근거에 잡힌다(docs/10 §6).",
        "",
        f"- 같은 호 근거 기록이 {CROWDED_FLOOR}건 이상인 층키: {summary.crowded_floors:,}곳, "
        f"기록 {summary.crowded_records:,}건 (같은 호 근거의 "
        f"{_percent(summary.crowded_records, summary.same_ho)})",
        f"- 층키별 같은 호 근거 기록 수 상위 {TOP_FLOORS}: {counts}",
    ]
    return "\n".join(lines) + "\n"


async def flag(engine: AsyncEngine) -> Summary:
    """표시를 다시 계산해 `license_record`에 쓴다 (한 트랜잭션)."""
    async with engine.begin() as conn:
        rows = (await conn.execute(text(_RECORDS))).all()
        records = pd.DataFrame(
            rows,
            columns=[
                "id",
                "license_type",
                "name",
                "status",
                "opened_on",
                "area_m2",
                "pnu",
                "floor",
                "ho_list",
                "no_fixed_place",
            ],
        )
        result = detect_stale(records)
        await conn.execute(text(_STAGING))
        raw_conn = await conn.get_raw_connection()
        await raw_conn.driver_connection.copy_records_to_table(  # type: ignore[union-attr]
            "stale_staging",
            records=[
                (int(row["id"]), bool(row[SAME_HO]), bool(row[SAME_AREA]))
                for row in result.flags.to_dict("records")
            ],
            columns=("id", "same_ho", "same_area"),
        )
        await conn.execute(text(_APPLY))
    return summarize(records, result)


async def run() -> Summary:
    engine = get_engine()
    try:
        return await flag(engine)
    finally:
        await engine.dispose()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="jobs.flag_stale_suspects", description="미갱신 의심 표시와 리포트"
    )
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT, help="리포트 경로")
    args = parser.parse_args(argv)

    summary = asyncio.run(run())
    args.out.parent.mkdir(parents=True, exist_ok=True)
    report = render_report(summary, measured_on=datetime.now(SOURCE_TZ).date())
    args.out.write_text(report, encoding="utf-8")
    line = {
        "job": "flag_stale_suspects",
        "candidates": summary.result.candidates,
        "same_ho": summary.same_ho,
        "same_area": summary.same_area,
        "area_only": summary.area_only,
        "ho_pairs_same_name": summary.result.ho_pairs_same_name,
        "area_pairs_same_name": summary.result.area_pairs_same_name,
        "out": str(args.out),
    }
    print(json.dumps(line, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
