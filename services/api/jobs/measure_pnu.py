"""PNU 생성 실패율 측정 (docs/10 §2.1, T-011 수용 기준).

    python -m jobs.measure_pnu [--out reports/pnu_failures.md]

종류별 최신 스냅샷(`failed` 제외)의 `license_raw`와 `legal_dong`을 읽어 실패율을 재고 리포트를 쓴다.
기준(< 0.5%)에 못 미치면 종료 코드 1.
"""

import argparse
import asyncio
import json
import sys
from datetime import datetime
from pathlib import Path

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from app.address.pnu import LegalDongIndex
from app.address.pnu_report import FAILURE_REASONS, PnuStats, measure, render_report
from app.core.db import get_engine
from app.location.ingest.license_file import JIBUN_ADDR, ROAD_ADDR, SOURCE_TZ

REPO_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_OUT = REPO_ROOT / "reports" / "pnu_failures.md"

_SNAPSHOTS = """
SELECT DISTINCT ON (license_type) id, license_type, source_updated_max
FROM data_snapshot
WHERE status IN ('loaded', 'validated')
ORDER BY license_type, id DESC
"""
_ADDRESSES = """
SELECT coalesce(payload->>:jibun, ''), coalesce(payload->>:road, ''), count(*)
FROM license_raw
WHERE snapshot_id = ANY(:ids)
GROUP BY 1, 2
"""


async def collect(engine: AsyncEngine) -> tuple[PnuStats, list[str], int]:
    async with engine.connect() as conn:
        dongs = [
            (str(code), str(full_name), bool(abolished))
            for code, full_name, abolished in await conn.execute(
                text("SELECT code, full_name, abolished FROM legal_dong")
            )
        ]
        snapshots = list(await conn.execute(text(_SNAPSHOTS)))
        rows = await conn.execute(
            text(_ADDRESSES),
            {"jibun": JIBUN_ADDR, "road": ROAD_ADDR, "ids": [row[0] for row in snapshots]},
        )
        stats = measure(
            ((str(jibun), str(road), int(count)) for jibun, road, count in rows),
            LegalDongIndex.from_rows(dongs),
        )
    labels = [f"{license_type} #{snapshot_id}" for snapshot_id, license_type, _ in snapshots]
    return stats, labels, len(dongs)


async def run() -> tuple[PnuStats, list[str], int]:
    engine = get_engine()
    try:
        return await collect(engine)
    finally:
        await engine.dispose()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="jobs.measure_pnu", description="PNU 생성 실패율 측정")
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT, help="리포트 경로")
    args = parser.parse_args(argv)

    stats, snapshots, legal_dong_rows = asyncio.run(run())
    if legal_dong_rows == 0:
        print(
            "legal_dong이 비어 있습니다. jobs.ingest_legal_dong을 먼저 실행하세요.", file=sys.stderr
        )
        return 1
    report = render_report(
        stats,
        measured_on=datetime.now(SOURCE_TZ).date(),
        snapshots=snapshots,
        legal_dong_rows=legal_dong_rows,
    )
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(report, encoding="utf-8")
    percent = stats.failure_percent
    line = {
        "job": "measure_pnu",
        "total": stats.total,
        "failed": stats.failed,
        "failure_percent": None if percent is None else str(round(percent, 4)),
        "abolished_only": stats.abolished_only,
        **{reason: stats.by_reason[reason] for reason in FAILURE_REASONS},
        "out": str(args.out),
    }
    print(json.dumps(line, ensure_ascii=False))
    return 0 if stats.passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
