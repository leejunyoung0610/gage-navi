"""검색 일치율 리포트를 건별 결과 파일에서 다시 만든다 (T-021b, docs/50 §7). API를 부르지 않는다.

    cd services/api && uv run --env-file ../../.env python -m jobs.render_search_match \\
        --measured-on 2026-10-13 --criteria-commit "…" --calls 2100 \\
        --commit "기준=b8ec7b4" --commit "결과=e91fe44"

`--commit 구분=해시`로 준 커밋은 `main`(`origin/main`)에 있어야 한다. 없으면(머지 전 브랜치 해시)
리포트를 만들지 않는다(ADR-029). 각 커밋의 작성 시각과 `main`에 들어간 시각을 표로 싣는다.

`jobs.measure_search_match`가 `data/derived/search_match/seed_<seed>.jsonl`에 남긴 건별 결과를
읽는다. 표본은 DB에서 같은 seed로 다시 뽑아 건별 결과와 순서·키가 같은지 확인한다.
"""

import argparse
import asyncio
import json
import subprocess
import sys
from pathlib import Path

from app.address.search_match import (
    REMEASURE_SEED,
    SAMPLE_SIZE,
    SEED,
    CommitTime,
    Outcome,
    ReportContext,
    render_report,
)
from app.core.db import get_engine
from jobs.measure_search_match import DEFAULT_OUT, detail_path, load

MAIN_REF = "origin/main"


def _git(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(["git", *args], capture_output=True, text=True, check=False)


def commit_times(specs: list[str]) -> tuple[CommitTime, ...] | None:
    """`구분=해시` 목록 → `main`에 있는 커밋의 시각. 하나라도 `main`에 없으면 None."""
    rows: list[CommitTime] = []
    for spec in specs:
        label, _, sha = spec.partition("=")
        if _git("merge-base", "--is-ancestor", sha, MAIN_REF).returncode != 0:
            print(f"커밋 {sha}({label})가 {MAIN_REF}에 없습니다. 머지 후 main의 해시를 쓰세요.")
            return None
        out = _git("log", "-1", "--date=format:%Y-%m-%d %H:%M:%S %z", "--format=%h|%ad|%cd", sha)
        short, authored, committed = out.stdout.strip().split("|")
        rows.append(CommitTime(label, short, authored, committed))
    return tuple(rows)


async def run(args: argparse.Namespace) -> int:
    commits = commit_times(args.commit)
    if commits is None:
        return 1
    seed = REMEASURE_SEED if args.remeasure else SEED
    engine = get_engine()
    try:
        sample, facts = await load(engine, seed, args.size)
    finally:
        await engine.dispose()
    lines = detail_path(seed).read_text(encoding="utf-8").splitlines()
    detail = [json.loads(line) for line in lines if line.strip()]
    keys = [(row["license_type"], row["mgmt_no"]) for row in detail]
    if keys != [(record.key.license_type, record.key.mgmt_no) for record in sample]:
        print("건별 결과 파일의 기록이 표본과 다릅니다. 리포트를 만들지 않았습니다.")
        return 1
    outcomes = [
        Outcome(record, row["outcome"], tuple(row["transport_reasons"]))
        for record, row in zip(sample, detail, strict=True)
    ]
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
            calls=args.calls,
            stopped_runs=args.stopped_runs,
            gu_names=gu_names,
            commits=commits,
        ),
    )
    args.out.write_text(report, encoding="utf-8")
    print(f"리포트 {args.out.name} ({len(outcomes)}건)")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=(__doc__ or "").splitlines()[0])
    parser.add_argument("--measured-on", required=True, help="측정일 YYYY-MM-DD")
    parser.add_argument("--criteria-commit", required=True, help="기준을 커밋한 날짜와 커밋 해시")
    parser.add_argument("--calls", type=int, required=True, help="측정 잡이 출력한 호출 수")
    parser.add_argument("--remeasure", action="store_true", help="재측정(seed 20261014)")
    parser.add_argument("--stopped-runs", default="없음")
    parser.add_argument(
        "--commit", action="append", default=[], help="구분=해시 (main에 있는 커밋, 여러 번)"
    )
    parser.add_argument("--size", type=int, default=SAMPLE_SIZE)
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    return asyncio.run(run(parser.parse_args(argv)))


if __name__ == "__main__":
    sys.exit(main())
