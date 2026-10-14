"""검색 일치율 측정 (T-021b, docs/50 §7 사전 등록 기준, ADR-028).

    cd services/api && caffeinate -ims uv run --env-file ../../.env \\
        python -m jobs.measure_search_match

- 도로명주소 API를 실제로 부른다(1초에 1건, 순차, 요청마다 10초 제한). 2,000건이면 30분이 넘는다
- 접근 문제(오류코드, HTTP 429·5xx·연결 오류 연속 3번, 5분 동안 진행 없음)면 멈춘다(종료 코드 3).
  그때까지의 일치율은 계산·출력하지 않는다
- 진행 상황은 "시각, 몇 건째, 호출 몇 번"만 출력한다. 검색어·승인키·건별 결과는 출력하지 않는다
- 건별 결과는 한 건이 끝날 때마다 `data/derived/search_match/seed_<seed>.jsonl`
  (gitignore)에 덧붙인다. 리포트는 `jobs.render_search_match`가 이 파일에서 집계만 싣는다
- 덮개를 닫으면(배터리 전원) `caffeinate`로도 잠드는 것을 막지 못한다.
  전원을 연결하고 덮개를 연 채로 돈다
"""

import argparse
import asyncio
import json
import os
import sys
import time
from datetime import datetime
from pathlib import Path

import httpx2
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from app.address.juso import JusoClient
from app.address.search_match import (
    REMEASURE_SEED,
    REQUEST_TIMEOUT_SECONDS,
    SAMPLE_SIZE,
    SEED,
    AccessProblemError,
    Outcome,
    Pacer,
    RecordKey,
    SampleRecord,
    draw_sample,
    measure,
)
from app.core.db import get_engine

REPO_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_OUT = REPO_ROOT / "reports" / "search_match.md"  # jobs.render_search_match가 쓴다
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


def _now() -> str:
    return datetime.now().astimezone().strftime("%Y-%m-%d %H:%M:%S")


def _progress(done: int, calls: int) -> None:
    if done % PROGRESS_EVERY == 0:
        print(f"{_now()} 진행: {done}건, 호출 {calls}번", flush=True)


def detail_path(seed: int) -> Path:
    return DETAIL_DIR / f"seed_{seed}.jsonl"


def detail_line(outcome: Outcome) -> str:
    row = {
        "license_type": outcome.record.key.license_type,
        "mgmt_no": outcome.record.key.mgmt_no,
        "outcome": outcome.outcome,
        "transport_reasons": list(outcome.transport_reasons),
    }
    return json.dumps(row, ensure_ascii=False) + "\n"


async def run(args: argparse.Namespace, secret: str) -> int:
    seed = REMEASURE_SEED if args.remeasure else SEED
    engine = get_engine()
    try:
        sample, facts = await load(engine, seed, args.size)
    finally:
        await engine.dispose()
    path = detail_path(seed)
    if path.exists():
        print(f"{path.name}이 이미 있습니다. 앞 실행의 파일을 옮긴 뒤 다시 실행하세요.")
        return 2
    path.parent.mkdir(parents=True, exist_ok=True)
    print(f"{_now()} 시작: 표본 {len(sample)}건 (seed {seed}, 모집단 {facts['population']}건)")
    pacer = Pacer(time.monotonic, asyncio.sleep)
    with path.open("w", encoding="utf-8") as detail:

        def write(outcome: Outcome) -> None:
            detail.write(detail_line(outcome))
            detail.flush()

        async with httpx2.AsyncClient() as http:
            client = JusoClient(secret, http, timeout=REQUEST_TIMEOUT_SECONDS)
            try:
                outcomes = await measure(sample, client.fetch, pacer, _progress, time.time, write)
            except AccessProblemError as exc:
                print(
                    f"{_now()} 중단: 접근 문제 ({exc.reason}), {exc.call_no}번째 호출", flush=True
                )
                return 3
    print(
        f"{_now()} 완료: {len(outcomes)}건, 호출 {pacer.calls}번. 건별 결과 {path.name}", flush=True
    )
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=(__doc__ or "").splitlines()[0])
    parser.add_argument("--remeasure", action="store_true", help="재측정(seed 20261014)")
    parser.add_argument("--size", type=int, default=SAMPLE_SIZE)
    args = parser.parse_args(argv)
    secret = os.environ.get("JUSO_CONFM_KEY", "")
    if not secret:
        print("JUSO_CONFM_KEY가 없습니다. .env에 넣은 뒤 --env-file로 실행하세요.")
        return 2
    return asyncio.run(run(args, secret))


if __name__ == "__main__":
    sys.exit(main())
