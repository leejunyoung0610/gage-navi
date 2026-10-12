"""PNU 생성 실패율 집계와 리포트 (docs/10 §2.1).

실패율 = (정규식 불일치 + `legal_dong` 조회 실패) ÷ 서울 필터를 통과한 전체 기록.
폐지 코드만 있는 이름으로 만든 PNU는 실패가 아니며 건수만 따로 센다.
"""

import re
from collections import Counter
from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import date
from decimal import ROUND_HALF_UP, Decimal

from app.address.pnu import (
    FAIL_AMBIGUOUS,
    FAIL_DONG_NOT_FOUND,
    FAIL_REGEX_MISMATCH,
    SIDO,
    LegalDongIndex,
    build_pnu,
    parse_jibun,
)

FAILURE_REASONS = (FAIL_REGEX_MISMATCH, FAIL_DONG_NOT_FOUND, FAIL_AMBIGUOUS)
THRESHOLD_PERCENT = Decimal("0.5")
TOP_N = 20
EMPTY_ADDRESS = "(지번주소 없음)"

_WHITESPACE = re.compile(r"\s+")
_DIGITS = re.compile(r"\d+")


@dataclass
class PnuStats:
    total: int = 0  # 서울 필터를 통과한 기록
    non_seoul: int = 0  # 분모에서 뺀 기록
    abolished_only: int = 0
    by_reason: Counter[str] = field(default_factory=Counter)
    # (사유, 묶음 키) → 건수, 예시 주소
    groups: Counter[tuple[str, str]] = field(default_factory=Counter)
    examples: dict[tuple[str, str], str] = field(default_factory=dict)

    @property
    def failed(self) -> int:
        return sum(self.by_reason.values())

    @property
    def failure_percent(self) -> Decimal | None:
        if self.total == 0:
            return None
        return Decimal(self.failed) * 100 / Decimal(self.total)

    @property
    def passed(self) -> bool | None:
        percent = self.failure_percent
        return None if percent is None else percent < THRESHOLD_PERCENT


def is_seoul(jibun_addr: str, road_addr: str) -> bool:
    """서울 필터: 두 주소 중 하나라도 `서울특별시`로 시작한다 (T-010 적재 기준과 같다)."""
    return jibun_addr.startswith(SIDO) or road_addr.startswith(SIDO)


def failure_group(reason: str, jibun_addr: str) -> str:
    """실패 사례를 묶는 키. 조회 실패는 법정동 이름, 정규식 불일치는 숫자를 지운 주소 모양."""
    normalized = _WHITESPACE.sub(" ", jibun_addr).strip()
    if reason == FAIL_REGEX_MISMATCH:
        return _DIGITS.sub("N", normalized) if normalized else EMPTY_ADDRESS
    parts = parse_jibun(normalized)
    return parts.full_name if parts is not None else normalized


def measure(rows: Iterable[tuple[str, str, int]], index: LegalDongIndex) -> PnuStats:
    """`rows`: `(지번주소, 도로명주소, 건수)`."""
    stats = PnuStats()
    for jibun_addr, road_addr, count in rows:
        if not is_seoul(jibun_addr, road_addr):
            stats.non_seoul += count
            continue
        stats.total += count
        result = build_pnu(jibun_addr, index)
        if result.failure is None:
            if result.abolished_only:
                stats.abolished_only += count
            continue
        stats.by_reason[result.failure] += count
        key = (result.failure, failure_group(result.failure, jibun_addr))
        stats.groups[key] += count
        stats.examples.setdefault(key, _WHITESPACE.sub(" ", jibun_addr).strip())
    return stats


def _percent(value: Decimal | None) -> str:
    if value is None:
        return "측정 불가 (기록 0건)"
    return f"{value.quantize(Decimal('0.0001'), rounding=ROUND_HALF_UP)}%"


def _cell(value: str) -> str:
    return value.replace("|", "\\|") or EMPTY_ADDRESS


def render_report(
    stats: PnuStats, *, measured_on: date, snapshots: list[str], legal_dong_rows: int
) -> str:
    verdict = {True: "통과", False: "미달", None: "측정 불가"}[stats.passed]
    lines = [
        "# PNU 생성 실패율 (T-011, docs/10 §2.1)",
        "",
        "`python -m jobs.measure_pnu`가 만든 파일이다. 손으로 고치지 않는다.",
        "",
        f"- 측정일: {measured_on.isoformat()}",
        f"- 대상 스냅샷: {', '.join(snapshots)}",
        f"- `legal_dong` 행 수: {legal_dong_rows:,}",
        f"- 서울 필터를 통과한 기록: {stats.total:,} (서울 밖 주소라 뺀 기록 {stats.non_seoul:,})",
        f"- 실패: {stats.failed:,}",
        f"- **실패율: {_percent(stats.failure_percent)}**"
        f" (기준 < {THRESHOLD_PERCENT}% → {verdict})",
        "",
        "## 사유별",
        "",
        "| 사유 | 건수 |",
        "|---|---|",
    ]
    lines += [f"| `{reason}` | {stats.by_reason[reason]:,} |" for reason in FAILURE_REASONS]
    lines += [
        "",
        "## 폐지 코드로 만든 PNU (실패 아님, 실패율에 넣지 않음)",
        "",
        f"- 현행 코드가 없고 폐지 코드만 있는 이름: {stats.abolished_only:,}건",
        "",
        f"## 실패 상위 {TOP_N}개",
        "",
        "조회 실패는 법정동 이름으로, 정규식 불일치는 숫자를 `N`으로 바꾼 주소 모양으로 묶었다.",
        "",
        "| 순위 | 사유 | 묶음 | 건수 | 예시 지번주소 |",
        "|---|---|---|---|---|",
    ]
    ranked = sorted(stats.groups.items(), key=lambda item: (-item[1], item[0]))[:TOP_N]
    for rank, (key, count) in enumerate(ranked, start=1):
        reason, group = key
        example = _cell(stats.examples[key])
        lines.append(f"| {rank} | `{reason}` | {_cell(group)} | {count:,} | {example} |")
    if not ranked:
        lines.append("| - | - | 실패 없음 | 0 | - |")
    not_found = sorted(
        ((key, count) for key, count in stats.groups.items() if key[0] == FAIL_DONG_NOT_FOUND),
        key=lambda item: (-item[1], item[0]),
    )
    lines += [
        "",
        "## `legal_dong`에 없는 이름 (`dong_not_found`)",
        "",
        "적재한 법정동코드 파일은 현행 코드만 담고 있다. 여기 나온 이름이 폐지된 옛 동명인지,",
        "지번주소 칸에 다른 값이 들어간 것인지는 파일만으로 가릴 수 없어 이름을 그대로 남긴다.",
        f"건수 순 상위 {TOP_N}개. 이름 {len(not_found):,}개, 기록 "
        f"{stats.by_reason[FAIL_DONG_NOT_FOUND]:,}건.",
        "",
        "| 이름 | 건수 | 예시 지번주소 |",
        "|---|---|---|",
    ]
    for key, count in not_found[:TOP_N]:
        lines.append(f"| {_cell(key[1])} | {count:,} | {_cell(stats.examples[key])} |")
    if not not_found:
        lines.append("| 없음 | 0 | - |")
    return "\n".join(lines) + "\n"
