"""법정동코드 파일 적재 (docs/03 D3).

    python -m jobs.ingest_legal_dong --file PATH

파일의 모든 행을 `legal_dong`에 upsert한다. 다시 실행해도 결과가 같다.
"""

import argparse
import asyncio
import json
import sys
import time
from dataclasses import asdict
from pathlib import Path

from app.address.legal_dong_file import LegalDongFileError, LegalDongIngestResult, ingest_file
from app.core.db import get_engine


async def run(path: Path) -> LegalDongIngestResult:
    engine = get_engine()
    try:
        return await ingest_file(engine, path)
    finally:
        await engine.dispose()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="jobs.ingest_legal_dong", description="법정동코드 적재")
    parser.add_argument("--file", type=Path, required=True, help="법정동코드 CSV 경로")
    args = parser.parse_args(argv)
    if not args.file.is_file():
        print(f"적재 실패: 파일이 없습니다: {args.file}", file=sys.stderr)
        return 1
    started = time.perf_counter()
    try:
        result = asyncio.run(run(args.file))
    except (LegalDongFileError, FileNotFoundError) as exc:
        print(f"적재 실패: {exc}", file=sys.stderr)
        return 1
    line = {
        "job": "ingest_legal_dong",
        **asdict(result),
        "seconds": round(time.perf_counter() - started, 1),
    }
    print(json.dumps(line, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
