"""인허가 파일 적재 (docs/03 D1, §5).

    python -m jobs.ingest_licenses --mode full --type general_restaurant --file PATH

갱신은 월 1회 전체 적재다 (ADR-025). 증분 수집(`--mode incremental`)은 만들지 않는다.
"""

import argparse
import asyncio
import json
import sys
import time
from pathlib import Path

from app.core.db import get_engine
from app.location.ingest.license_file import (
    LICENSE_TYPES,
    SOURCE_TZ,
    IngestResult,
    LicenseFileError,
    ingest_file,
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="jobs.ingest_licenses", description="인허가 파일 적재")
    parser.add_argument("--mode", choices=("full",), required=True)
    parser.add_argument("--type", dest="license_type", choices=LICENSE_TYPES, required=True)
    parser.add_argument("--file", type=Path, required=True, help="원천 CSV 경로")
    return parser


def summary(result: IngestResult, license_type: str, seconds: float) -> dict[str, object]:
    """실행 결과 한 줄(JSON). 행 내용은 넣지 않는다."""
    return {
        "job": "ingest_licenses",
        "license_type": license_type,
        "snapshot_id": result.snapshot_id,
        "skipped": result.skipped,
        "row_count": result.row_count,
        "non_seoul_address_rows": result.non_seoul_address_rows,
        "source_updated_max": result.source_updated_max
        and result.source_updated_max.astimezone(SOURCE_TZ).isoformat(),
        "encoding": result.encoding,
        "file_sha256": result.file_sha256,
        "seconds": round(seconds, 1),
    }


async def run(license_type: str, path: Path) -> IngestResult:
    engine = get_engine()
    try:
        return await ingest_file(engine, license_type, path)
    finally:
        await engine.dispose()


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    started = time.perf_counter()
    try:
        result = asyncio.run(run(args.license_type, args.file))
    except (LicenseFileError, FileNotFoundError) as exc:
        print(f"적재 실패: {exc}", file=sys.stderr)
        return 1
    line = summary(result, args.license_type, time.perf_counter() - started)
    print(json.dumps(line, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
