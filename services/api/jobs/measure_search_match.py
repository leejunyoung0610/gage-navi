"""검색 일치율 측정 (T-021b, docs/50 §7 사전 등록 기준, ADR-028).

    cd services/api && caffeinate -i uv run --env-file ../../.env \\
        python -m jobs.measure_search_match \\
        --measured-on 2026-10-13 --criteria-commit "2026-10-13 (abc1234)"

- 도로명주소 API를 실제로 부른다(1초에 1건, 순차). 표본 2,000건이면 30분이 넘는다
- 접근 문제 오류코드가 나오면 멈춘다(종료 코드 3). 그때까지의 일치율은 계산·출력하지 않는다
- 진행 상황은 "몇 건째, 호출 몇 번"만 출력한다. 검색어·승인키·건별 결과는 출력하지 않는다
- 건별 결과는 `data/derived/search_match/`(gitignore)에만 쓰고, 리포트에는 집계만 싣는다
"""

import argparse
import asyncio
import json
import os
import sys
import time
from pathlib import Path

import httpx2
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from app.address.juso import JusoClient
from app.address.search_match import (
    REMEASURE_SEED,
    SAMPLE_SIZE,
    SEED,
    AccessProblemError,
    Outcome,
    Pacer,
    RecordKey,
    ReportContext,
    SampleRecord,
    draw_sample,
    measure,
    render_report,
)
from app.core.db import get_engine

REPO_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_OUT = REPO_ROOT / "reports" / "search_match.md"
DETAIL_DIR = REPO_ROOT / "data" / "derived" / "search_match"
PROGRESS_EVERY = 100

_POPULATION = """
SELECT license_type, mgmt_no FROM license_record
WHERE pnu IS NOT NULL AND btrim(coalesce(road_addr, '')) <> ''
  AND btrim(coalesce(jibun_addr, '')) <> ''
"""
_RECORDS = """
SELECT license_type, mgmt_no, road_addr, jibun_addr, pnu, sigungu_code,
       extract(year FROM opened_on)::int
FROM license_record WHERE license_type = :license_type AND mgmt_no = ANY(:mgmt_nos)
"""
_SNAPSHOTS = """
SELECT DISTINCT ON (license_type) license_type, id FROM data_snapshot
WHERE status = 'validated' ORDER BY license_type, id DESC
"""


async def load(
    engine: AsyncEngine, seed: int, size: int
) -> tuple[list[SampleRecord], dict[str, object]]:
    async with engine.connect() as conn:
        population = [RecordKey(str(t), str(m)) for t, m in await conn.execute(text(_POPULATION))]
        keys = draw_sample(population, seed=seed, size=size)
        by_key: dict[RecordKey, SampleRecord] = {}
        for license_type in sorted({key.license_type for key in keys}):
            mgmt_nos = [key.mgmt_no for key in keys if key.license_type == license_type]
            rows = await conn.execute(
                text(_RECORDS), {"license_type": license_type, "mgmt_nos": mgmt_nos}
            )
            for t, m, road, jibun, pnu, sigungu, year in rows:
                key = RecordKey(str(t), str(m))
                by_key[key] = SampleRecord(
                    key, str(road), str(jibun), str(pnu), sigungu and str(sigungu), year
                )
        total, with_pnu = (
            await conn.execute(text("SELECT count(*), count(pnu) FROM license_record"))
        ).one()
        snapshots = ", ".join(f"{t} #{i}" for t, i in await conn.execute(text(_SNAPSHOTS)))
        gu_names = {
            str(code): str(name)
            for code, name in await conn.execute(
                text(
                    "SELECT DISTINCT left(code, 5), sigungu FROM legal_dong "
                    "WHERE sigungu IS NOT NULL AND NOT abolished"
                )
            )
        }
    facts: dict[str, object] = {
        "population": len(population),
        "records_total": int(total),
        "records_with_pnu": int(with_pnu),
        "snapshots": snapshots,
        "gu_names": gu_names,
    }
    return [by_key[key] for key in keys], facts


def _progress(done: int, calls: int) -> None:
    if done % PROGRESS_EVERY == 0:
        print(f"진행: {done}건, 호출 {calls}번", flush=True)


def write_detail(outcomes: list[Outcome], seed: int) -> Path:
    DETAIL_DIR.mkdir(parents=True, exist_ok=True)
    path = DETAIL_DIR / f"seed_{seed}.json"
    rows = [
        {
            "license_type": row.record.key.license_type,
            "mgmt_no": row.record.key.mgmt_no,
            "outcome": row.outcome,
        }
        for row in outcomes
    ]
    path.write_text(json.dumps(rows, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    return path


async def run(args: argparse.Namespace, secret: str) -> int:
    seed = REMEASURE_SEED if args.remeasure else SEED
    engine = get_engine()
    try:
        sample, facts = await load(engine, seed, args.size)
    finally:
        await engine.dispose()
    print(f"표본 {len(sample)}건 (seed {seed}, 모집단 {facts['population']}건)", flush=True)
    pacer = Pacer(time.monotonic, asyncio.sleep)
    async with httpx2.AsyncClient() as http:
        try:
            outcomes = await measure(sample, JusoClient(secret, http).fetch, pacer, _progress)
        except AccessProblemError as exc:
            print(f"중단: 접근 문제 ({exc.reason}), {exc.call_no}번째 호출", flush=True)
            return 3
    detail = write_detail(outcomes, seed)
    gu_names = facts["gu_names"]
    assert isinstance(gu_names, dict)
    report = render_report(
        outcomes,
        ReportContext(
            measured_on=args.measured_on,
            criteria_commit=args.criteria_commit,
            seed=seed,
            remeasure=args.remeasure,
            population=int(str(facts["population"])),
            snapshots=str(facts["snapshots"]),
            records_total=int(str(facts["records_total"])),
            records_with_pnu=int(str(facts["records_with_pnu"])),
            calls=pacer.calls,
            stopped_runs=args.stopped_runs,
            gu_names=gu_names,
        ),
    )
    args.out.write_text(report, encoding="utf-8")
    print(
        f"완료: {len(outcomes)}건, 호출 {pacer.calls}번. 리포트 {args.out.name}, 건별 {detail.name}"
    )
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=(__doc__ or "").splitlines()[0])
    parser.add_argument("--measured-on", required=True, help="측정일 YYYY-MM-DD")
    parser.add_argument("--criteria-commit", required=True, help="기준을 커밋한 날짜와 커밋 해시")
    parser.add_argument("--remeasure", action="store_true", help="재측정(seed 20261014)")
    parser.add_argument(
        "--stopped-runs", default="없음", help="접근 문제로 멈춘 실행의 횟수·오류코드"
    )
    parser.add_argument("--size", type=int, default=SAMPLE_SIZE)
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    args = parser.parse_args(argv)
    secret = os.environ.get("JUSO_CONFM_KEY", "")
    if not secret:
        print("JUSO_CONFM_KEY가 없습니다. .env에 넣은 뒤 --env-file로 실행하세요.")
        return 2
    return asyncio.run(run(args, secret))


if __name__ == "__main__":
    sys.exit(main())
