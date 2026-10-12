"""인허가 정규화와 데이터 검증 (docs/50 §2, T-016).

    python -m jobs.normalize_licenses

종류별 최신 스냅샷의 `license_raw`를 `license_record`로 정규화하고 DV1~DV10 결과를
`data_snapshot.validation.normalize`에 적는다. 실패 검사가 있으면 기존 데이터를 그대로 두고
종료 코드 1. 같은 스냅샷으로 다시 실행하면 같은 결과가 된다.
"""

import argparse
import asyncio
import json
import sys
import time

from app.core.db import get_engine
from app.location.normalize.job import NormalizeError, NormalizeResult, run_normalize


def summary(result: NormalizeResult, seconds: float) -> dict[str, object]:
    """실행 결과 한 줄(JSON). 행 내용은 넣지 않는다."""
    return {
        "job": "normalize_licenses",
        "applied": result.applied,
        "records": result.records,
        "surge_days": result.surge_days,
        "snapshots": [
            {
                "snapshot_id": snapshot.snapshot_id,
                "license_type": snapshot.license_type,
                "status": snapshot.status,
                "failed": snapshot.validation["failed"],
                "warnings": snapshot.validation["warnings"],
                "records": snapshot.validation["records"],
                "non_seoul_excluded": snapshot.validation["non_seoul_excluded"],
                "no_fixed_place": snapshot.validation["no_fixed_place"],
                "floor_conflict": snapshot.validation["floor_conflict"],
                "ho_conflict": snapshot.validation["ho_conflict"],
            }
            for snapshot in result.snapshots
        ],
        "seconds": round(seconds, 1),
    }


async def run() -> NormalizeResult:
    engine = get_engine()
    try:
        return await run_normalize(engine)
    finally:
        await engine.dispose()


def main(argv: list[str] | None = None) -> int:
    argparse.ArgumentParser(
        prog="jobs.normalize_licenses", description="인허가 정규화와 데이터 검증"
    ).parse_args(argv)
    started = time.perf_counter()
    try:
        result = asyncio.run(run())
    except NormalizeError as exc:
        print(f"정규화 실패: {exc}", file=sys.stderr)
        return 1
    print(json.dumps(summary(result, time.perf_counter() - started), ensure_ascii=False))
    return 0 if result.applied else 1


if __name__ == "__main__":
    raise SystemExit(main())
