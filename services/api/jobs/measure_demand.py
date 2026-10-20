"""수요 검증 측정값·일별 분포 (docs/70 §5, T-104). DB의 `measure_daily_count`만 읽는다.

    python -m jobs.measure_demand --start 2026-11-01            # 1일차부터 28일 판정용 측정값
    python -m jobs.measure_demand --start 2026-11-01 --days 28
    python -m jobs.measure_demand --start 2026-10-25 --end 2026-10-31 --daily-only  # 일별 합계만

판정(계속·방향 수정·연장·중단)은 하지 않는다. 사람이 docs/70 §5 표와 비교하고, 일별 분포에서
급증한 날을 확인해 판정 기록에 함께 적는다(빼지 않는다).
"""

import argparse
import asyncio
import json
from dataclasses import asdict
from datetime import date
from typing import Any

from app.core.db import get_engine
from app.measure import store
from app.measure.report import Counts, daily_rows, demand_report, period_end

DEFAULT_DAYS = 28  # docs/70 §5 기간


async def load(start: date, end: date) -> Counts:
    engine = get_engine()
    try:
        async with engine.connect() as conn:
            return await store.counts_between(conn, start, end)
    finally:
        await engine.dispose()


def build(counts: Counts, start: date, days: int, end: date | None, daily_only: bool) -> Any:
    if daily_only:
        last = end if end is not None else period_end(start, days)
        return {"daily": [asdict(row) for row in daily_rows(counts, start, last)]}
    return asdict(demand_report(counts, start, days))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="jobs.measure_demand", description="수요 검증 측정값·일별 분포 (docs/70 §5)"
    )
    parser.add_argument("--start", type=date.fromisoformat, required=True, help="1일차 (KST)")
    parser.add_argument("--days", type=int, default=DEFAULT_DAYS)
    parser.add_argument("--end", type=date.fromisoformat, help="--daily-only의 마지막 날")
    parser.add_argument("--daily-only", action="store_true", help="일별 합계만")
    args = parser.parse_args(argv)
    last = args.end if args.daily_only and args.end else period_end(args.start, args.days)
    counts = asyncio.run(load(args.start, last))
    result = build(counts, args.start, args.days, args.end, args.daily_only)
    print(json.dumps(result, ensure_ascii=False, indent=2, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
