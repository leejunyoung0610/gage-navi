"""층 조회 처리량 측정 (ADR-031 조건, T-081). 운영 VM에서 공개 전에 사람이 실행한다.

    python -m jobs.measure_place_throughput [--base-url http://api:8000] [--seconds 60]
        [--concurrency 4 8 16 32] [--sample 2000]

DB의 `floor_summary`에서 층 `--sample`개를 고정 순서(md5)로 뽑아, 단계마다 동시 접속 수만큼 작업자가
`--seconds`초 동안 `GET /api/v1/places/{pnu}/floors/{floor}`를 쉬지 않고 돌아가며 부른다.
compose 네트워크 안에서 api에 직접 보내고 요청마다 다른 `X-Forwarded-For`를 붙여 IP 한도를 비켜 간다
(`deploy/README.md` 7단계 대조군 C와 같은 원리 — 밖에서는 Caddy가 이 값을 버린다).

판정: 오류율(200이 아닌 응답·통신 오류) < 1%이고 p95 ≤ 500ms인 단계 중 가장 높은 초당 처리량을 지속
처리량으로 본다. 서버 렌더링 공유 한도(분당 600)가 그 절반을 넘으면 절반(분당, 내림)으로 낮출 것을
권고한다. 한도 값은 이 잡이 바꾸지 않는다(ADR-031·docs/30 §1을 고친다).
"""

import argparse
import asyncio
import json
import math
import sys
import time
from dataclasses import asdict, dataclass

import httpx2
from sqlalchemy import text

from app.core.db import get_engine
from app.core.ratelimit import SSR_LOOKUP_LIMIT_PER_MINUTE

MAX_ERROR_RATE = 0.01  # docs/01 §7 경보(5xx 1%)와 같은 선
MAX_P95_MS = 500.0
TIMEOUT_SECONDS = 10.0

_SAMPLE = """
SELECT pnu, floor FROM floor_summary
ORDER BY md5(pnu || ':' || floor)
LIMIT :n
"""


@dataclass(frozen=True)
class Level:
    concurrency: int
    requests: int
    errors: int
    seconds: float
    rps: float
    p50_ms: float
    p95_ms: float
    error_rate: float
    passed: bool


def percentile(values: list[float], q: float) -> float:
    """가장 가까운 순위 방식(nearest-rank). 값이 없으면 `nan`."""
    if not values:
        return math.nan
    ordered = sorted(values)
    rank = max(1, math.ceil(q * len(ordered)))
    return ordered[rank - 1]


def summarize(concurrency: int, latencies_ms: list[float], errors: int, seconds: float) -> Level:
    requests = len(latencies_ms) + errors
    error_rate = errors / requests if requests else 1.0
    p95 = percentile(latencies_ms, 0.95)
    return Level(
        concurrency=concurrency,
        requests=requests,
        errors=errors,
        seconds=round(seconds, 1),
        rps=round(len(latencies_ms) / seconds, 1) if seconds > 0 else 0.0,
        p50_ms=round(percentile(latencies_ms, 0.5), 1),
        p95_ms=round(p95, 1),
        error_rate=round(error_rate, 4),
        passed=error_rate < MAX_ERROR_RATE and p95 <= MAX_P95_MS,
    )


def verdict(
    levels: list[Level], current_limit: int = SSR_LOOKUP_LIMIT_PER_MINUTE
) -> dict[str, object]:
    passing = [level.rps for level in levels if level.passed]
    if not passing:
        return {"sustained_rps": None, "half_per_minute": None, "lower_limit_to": None}
    sustained = max(passing)
    half_per_minute = math.floor(sustained * 60 / 2)
    return {
        "sustained_rps": sustained,
        "half_per_minute": half_per_minute,
        "lower_limit_to": half_per_minute if current_limit > half_per_minute else None,
    }


async def _sample(n: int) -> list[tuple[str, str]]:
    engine = get_engine()
    try:
        async with engine.connect() as conn:
            rows = (await conn.execute(text(_SAMPLE), {"n": n})).all()
    finally:
        await engine.dispose()
    return [(str(pnu), str(floor)) for pnu, floor in rows]


async def run_level(
    base_url: str, floors: list[tuple[str, str]], concurrency: int, seconds: float
) -> Level:
    latencies: list[float] = []
    errors = 0
    counter = 0
    deadline = time.monotonic() + seconds

    async def worker(client: httpx2.AsyncClient) -> None:
        nonlocal errors, counter
        while time.monotonic() < deadline:
            n = counter
            counter += 1
            pnu, floor = floors[n % len(floors)]
            fake_ip = f"10.{(n >> 16) & 255}.{(n >> 8) & 255}.{n & 255}"  # 요청마다 다른 키
            started = time.monotonic()
            try:
                response = await client.get(
                    f"{base_url}/api/v1/places/{pnu}/floors/{floor}",
                    headers={"X-Forwarded-For": fake_ip},
                )
                ok = response.status_code == 200
            except httpx2.HTTPError:
                ok = False
            if ok:
                latencies.append((time.monotonic() - started) * 1000)
            else:
                errors += 1

    started = time.monotonic()
    async with httpx2.AsyncClient(timeout=TIMEOUT_SECONDS) as client:
        await asyncio.gather(*(worker(client) for _ in range(concurrency)))
    return summarize(concurrency, latencies, errors, time.monotonic() - started)


async def run(args: argparse.Namespace) -> int:
    floors = await _sample(args.sample)
    if not floors:
        print("floor_summary가 비어 있습니다. 적재(deploy/README.md 5단계) 뒤에 실행하세요.")
        return 1
    levels: list[Level] = []
    for concurrency in args.concurrency:
        level = await run_level(args.base_url.rstrip("/"), floors, concurrency, args.seconds)
        levels.append(level)
        print(json.dumps(asdict(level)), flush=True)
    print(json.dumps({"floors_sampled": len(floors), **verdict(levels)}))
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=(__doc__ or "").splitlines()[0])
    parser.add_argument("--base-url", default="http://api:8000")
    parser.add_argument("--seconds", type=float, default=60.0)
    parser.add_argument("--concurrency", type=int, nargs="+", default=[4, 8, 16, 32])
    parser.add_argument("--sample", type=int, default=2000)
    return asyncio.run(run(parser.parse_args(argv)))


if __name__ == "__main__":
    sys.exit(main())
