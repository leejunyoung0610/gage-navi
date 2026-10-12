"""층 이력·과거 폐업 횟수 재계산 (docs/10 §7.1·§7.2, T-018).

    python -m jobs.build_history [--as-of YYYY-MM-DD]

`license_record`에서 `parcel`·`floor_summary`·`record_prior`를 전부 다시 만든다. 정규화
(`jobs.normalize_licenses`)와 미갱신 표시(`jobs.flag_stale_suspects`) 뒤에 실행한다.
기준일을 주지 않으면 정규화를 통과한 스냅샷의 데이터 기준일을 쓴다.
"""

import argparse
import asyncio
import json
import sys
import time
from datetime import date

from app.core.db import get_engine
from app.location.history.job import HistoryBuildError, HistoryResult, build_history


async def run(as_of: date | None) -> HistoryResult:
    engine = get_engine()
    try:
        return await build_history(engine, as_of)
    finally:
        await engine.dispose()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="jobs.build_history", description="층 이력·과거 폐업 횟수 재계산"
    )
    parser.add_argument("--as-of", type=date.fromisoformat, default=None, help="기준일")
    args = parser.parse_args(argv)
    started = time.perf_counter()
    try:
        result = asyncio.run(run(args.as_of))
    except HistoryBuildError as exc:
        print(f"빌드 실패: {exc}", file=sys.stderr)
        return 1
    line = {
        "job": "build_history",
        "as_of": result.as_of.isoformat(),
        "records": result.records,
        "parcels": result.parcels,
        "floors": result.floors,
        "floors_with_concurrent": result.floors_with_concurrent,
        "priors": result.priors,
        "priors_changed_by_surge": result.priors_changed_by_surge,
        "seconds": round(time.perf_counter() - started, 1),
    }
    print(json.dumps(line, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
