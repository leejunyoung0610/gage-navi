"""기준율·모형 카드 계산 (docs/10 §7.2·§7.3, T-019).

    python -m jobs.compute_base_rates [--method-version {2026.10.1|w0}] [--as-of YYYY-MM-DD]
        [--out PATH]

`license_record`에서 기본 설정의 기준율과 민감도 설정들을 계산한다. 층 이력 빌드
(`jobs.build_history`) 뒤에 실행한다. 모든 설정에서 결론 유지 판정 (a)(b)가 참이면
`base_rate`·`model_card`에 저장하고, 하나라도 깨지면 저장하지 않고 종료 코드 2로 끝난다.
설정별 표는 판정과 상관없이 리포트(`reports/base_rates.md`)에 적는다. `w0`는 W0 재현 모드다
(판정·리포트 없음, docs/10 §7.4). 층 규모별 판정이 깨진 규모는 그 규모의 기준율만 저장하지 않고
무엇이 깨졌는지 출력한다(T-019b, 종료 코드는 0).
"""

import argparse
import asyncio
import json
import sys
import time
from datetime import date
from pathlib import Path

from app.core.db import get_engine
from app.location.history.build import METHOD_VERSION
from app.location.history.job import HistoryBuildError
from app.location.stats.job import METHOD_VERSIONS, BaseRateResult, compute_base_rates
from app.location.stats.report import render, scale_failures

REPO_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_OUT = REPO_ROOT / "reports" / "base_rates.md"
EXIT_NOT_ROBUST = 2


async def run(method_version: str, as_of: date | None) -> BaseRateResult:
    engine = get_engine()
    try:
        return await compute_base_rates(engine, method_version, as_of)
    finally:
        await engine.dispose()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="jobs.compute_base_rates", description="기준율·모형 카드 계산"
    )
    parser.add_argument("--method-version", choices=METHOD_VERSIONS, default=METHOD_VERSION)
    parser.add_argument("--as-of", type=date.fromisoformat, default=None, help="기준일")
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT, help="리포트 경로")
    args = parser.parse_args(argv)
    started = time.perf_counter()
    try:
        result = asyncio.run(run(args.method_version, args.as_of))
    except HistoryBuildError as exc:
        print(f"계산 실패: {exc}", file=sys.stderr)
        return 1
    card = result.computation.card
    if card.robustness is not None:
        args.out.write_text(
            render(card, result.computation.method_version, result.saved), encoding="utf-8"
        )
    line = {
        "job": "compute_base_rates",
        "method_version": result.computation.method_version,
        "as_of": result.as_of.isoformat(),
        "cohort": card.data.n,
        "base_rate_rows": len(result.computation.rates),
        "holds": result.holds,
        "saved": result.saved,
        "floor_scales_held": None
        if card.by_floor_scale is None
        else [name for name, scale in card.by_floor_scale if scale.holds],
        "seconds": round(time.perf_counter() - started, 1),
    }
    print(json.dumps(line, ensure_ascii=False))
    if not result.holds and card.robustness is not None:
        print(
            "결론 유지 판정이 깨졌습니다. base_rate·model_card를 쓰지 않았습니다.", file=sys.stderr
        )
        for failure in card.robustness.failures:
            print(
                f"  {failure.axis} = {failure.value}, ({failure.criterion}): {failure.detail}",
                file=sys.stderr,
            )
        return EXIT_NOT_ROBUST
    # 규모가 깨져도 멈추지 않는다. 그 규모의 기준율만 쓰지 않는다 (docs/10 §7.3)
    if card.by_floor_scale is not None:
        for broken in scale_failures(card.by_floor_scale):
            print(f"층 규모 판정이 깨졌습니다: {broken}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
