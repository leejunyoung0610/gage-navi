"""호 파서 기대값 작성용 실제 데이터 20건 추출 (T-013 수용 기준).

    python -m jobs.sample_ho_cases --file PATH [--file PATH ...] [--seed N] [--out PATH]

원천 인허가 파일에서 서로 다른 `(tail, road_detail)` 쌍을 모아 `숫자+호`가 있는 쌍에서 무작위
10건, 호 표기가 까다로운 후보에서 무작위 10건을 뽑는다. 사람이 파서 결과를 보지 않고 기대값을
쓰도록 문자열만 출력하고, 파서는 호출하지 않는다.
"""

import argparse
import json
import random
import re
import sys
from collections.abc import Iterable
from pathlib import Path

from jobs.sample_floor_cases import Pair, read_pairs

DEFAULT_SEED = 20261013
PER_STRATUM = 10
DEFAULT_OUT = Path(__file__).resolve().parents[1] / "tests" / "unit" / "data" / "ho_real_cases.json"

HAS_HO = re.compile(r"\d\s*호")
# 호 표기가 까다로운 후보: N호선, 호 뒤 한글(호일부), 범위·쉼표·가지번호(101~103호, 101,102호,
# 201-5호), 영문 접두·접미(A105호, 101B호), 0으로 시작(B01호), 층 뒤 호 없는 숫자, 숫자 나열
TRICKY = re.compile(
    r"\d\s*호[가-힣]"
    r"|\d\s*[~\-,.]\s*\d+\s*호"
    r"|[A-Za-z]\s*-?\s*\d+\s*호"
    r"|\d\s*-?[A-Za-z]\s*호"
    r"|(?<!\d)0\d+\s*호"
    r"|층\s*\d{3,4}(?!\d)(?!\s*호)"
    r"|\d{3,4}\s*,\s*\d{3,4}"
)


def has_ho(pair: Pair) -> bool:
    return any(HAS_HO.search(text) for text in pair)


def is_tricky(pair: Pair) -> bool:
    return any(TRICKY.search(text) for text in pair)


def sample_cases(
    pairs: Iterable[Pair], seed: int, per_stratum: int = PER_STRATUM
) -> list[dict[str, object]]:
    """`숫자+호`가 있는 쌍 무작위 `per_stratum`건 + 까다로운 후보 무작위 `per_stratum`건.

    입력 순서와 중복에 상관없이 같은 seed면 같은 결과를 낸다.
    """
    population = sorted(set(pairs))
    rng = random.Random(seed)
    plain = rng.sample([pair for pair in population if has_ho(pair)], per_stratum)
    chosen = set(plain)
    candidates = [pair for pair in population if is_tricky(pair) and pair not in chosen]
    tricky = rng.sample(candidates, per_stratum)
    cases = [("random", pair) for pair in plain] + [("tricky", pair) for pair in tricky]
    rng.shuffle(cases)
    return [
        {"no": no, "stratum": stratum, "tail": tail, "road_detail": detail, "expected": None}
        for no, (stratum, (tail, detail)) in enumerate(cases, start=1)
    ]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="jobs.sample_ho_cases", description="호 파서 기대값 작성용 20건 추출"
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
        "ho_candidates": sum(has_ho(pair) for pair in pairs),
        "tricky_candidates": sum(is_tricky(pair) for pair in pairs),
        "cases": cases,
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    for case in cases:
        print(f"{case['no']:>2}. tail={case['tail']!r} | road_detail={case['road_detail']!r}")
    summary = {key: payload[key] for key in ("seed", "population", "ho_candidates")}
    print(json.dumps({"job": "sample_ho_cases", **summary, "out": str(args.out)}), file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
