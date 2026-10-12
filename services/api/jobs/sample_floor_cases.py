"""층 파서 기대값 작성용 실제 데이터 40건 추출 (T-012 수용 기준).

    python -m jobs.sample_floor_cases --file PATH [--file PATH ...] [--seed N] [--out PATH]

원천 인허가 파일에서 서로 다른 `(tail, road_detail)` 쌍을 모아 전체에서 무작위 20건, 층 표기가
까다로운 후보에서 무작위 20건을 뽑는다. 사람이 파서 결과를 보지 않고 기대값을 쓰도록 문자열만
출력하고, 파서는 호출하지 않는다.
"""

import argparse
import json
import random
import re
import sys
from collections.abc import Iterable
from pathlib import Path

from app.address.pnu import parse_jibun
from app.location.ingest.license_file import (
    JIBUN_ADDR,
    ROAD_ADDR,
    has_seoul_address,
    inspect_file,
    iter_rows,
)
from app.location.normalize.floor_parser import road_detail

DEFAULT_SEED = 20261012
PER_STRATUM = 20
DEFAULT_OUT = (
    Path(__file__).resolve().parents[1] / "tests" / "unit" / "data" / "floor_real_cases.json"
)

# 층 표기가 까다로운 후보: 지하·지층, B숫자, 숫자F, 숫자 사이 ~/쉼표, 옥탑·옥상, 호수 숫자
TRICKY = re.compile(r"지하|지층|B\s*\d|\d\s*F|\d\s*[~,]\s*\d|옥탑|옥상|\d\s*호", re.I)

Pair = tuple[str, str]


def is_tricky(pair: Pair) -> bool:
    return any(TRICKY.search(text) for text in pair)


def sample_cases(
    pairs: Iterable[Pair], seed: int, per_stratum: int = PER_STRATUM
) -> list[dict[str, object]]:
    """전체 무작위 `per_stratum`건 + 까다로운 후보 무작위 `per_stratum`건을 섞어 번호를 붙인다.

    입력 순서와 중복에 상관없이 같은 seed면 같은 결과를 낸다.
    """
    population = sorted(set(pairs))
    rng = random.Random(seed)
    plain = rng.sample(population, per_stratum)
    chosen = set(plain)
    candidates = [pair for pair in population if is_tricky(pair) and pair not in chosen]
    tricky = rng.sample(candidates, per_stratum)
    cases = [("random", pair) for pair in plain] + [("tricky", pair) for pair in tricky]
    rng.shuffle(cases)
    return [
        {"no": no, "stratum": stratum, "tail": tail, "road_detail": detail, "expected": None}
        for no, (stratum, (tail, detail)) in enumerate(cases, start=1)
    ]


def read_pairs(path: Path) -> Iterable[Pair]:
    for row in iter_rows(path, inspect_file(path).encoding):
        if not has_seoul_address(row):
            continue
        parts = parse_jibun(row[JIBUN_ADDR])
        yield ("" if parts is None else parts.tail, road_detail(row[ROAD_ADDR]))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="jobs.sample_floor_cases", description="층 파서 기대값 작성용 40건 추출"
    )
    parser.add_argument("--file", type=Path, action="append", required=True, help="인허가 원천 CSV")
    parser.add_argument("--seed", type=int, default=DEFAULT_SEED)
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT, help="표본 JSON 경로")
    args = parser.parse_args(argv)

    pairs: set[Pair] = set()
    for path in args.file:
        pairs.update(read_pairs(path))
    cases = sample_cases(pairs, args.seed)
    payload = {
        "seed": args.seed,
        "files": sorted(path.name for path in args.file),
        "population": len(pairs),
        "tricky_candidates": sum(is_tricky(pair) for pair in pairs),
        "cases": cases,
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    for case in cases:
        print(f"{case['no']:>2}. tail={case['tail']!r} | road_detail={case['road_detail']!r}")
    summary = {key: payload[key] for key in ("seed", "population", "tricky_candidates")}
    print(
        json.dumps({"job": "sample_floor_cases", **summary, "out": str(args.out)}), file=sys.stderr
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
