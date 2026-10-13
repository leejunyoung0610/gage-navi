"""검색 일치율 측정 (docs/50 §7 사전 등록 기준, ADR-028). 여기는 순수 함수만 둔다.

표본을 뽑는 방법·검색어를 만드는 법·실패 유형은 측정 전에 docs/50 §7에 적은 그대로다.
결과를 본 뒤에는 바꾸지 않는다.
"""

import hashlib
import re
from collections.abc import Awaitable, Callable, Iterable, Sequence
from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal
from typing import Any, Protocol

from app.address.juso import (
    JusoKeywordError,
    JusoPage,
    JusoUnavailableError,
    clean_keyword,
    parse_response,
)
from app.address.pnu import parse_jibun
from app.location.stats.base_rate import wilson_ci

SEED = 20261013  # 첫 측정. 재측정은 20261014 (docs/50 §7)
REMEASURE_SEED = 20261014
SAMPLE_SIZE = 2000

_WHITESPACE = re.compile(r"\s+")


@dataclass(frozen=True)
class RecordKey:
    license_type: str
    mgmt_no: str


def sample_rank(seed: int, key: RecordKey) -> str:
    """표본 순위: `sha256("{seed}:{license_type}:{mgmt_no}")`의 16진 문자열."""
    return hashlib.sha256(f"{seed}:{key.license_type}:{key.mgmt_no}".encode()).hexdigest()


def draw_sample(
    population: Iterable[RecordKey], seed: int = SEED, size: int = SAMPLE_SIZE
) -> list[RecordKey]:
    """순위가 작은 것부터 `size`건. 모집단의 순서와 무관하게 같은 결과가 나온다."""
    ranked = sorted({key: sample_rank(seed, key) for key in population}.items(), key=_rank_then_key)
    return [key for key, _ in ranked[:size]]


def _rank_then_key(item: tuple[RecordKey, str]) -> tuple[str, str, str]:
    key, rank = item
    return rank, key.license_type, key.mgmt_no


def keyword_of(road_addr: str) -> str:
    """도로명주소의 기본부: 첫 쉼표 또는 첫 여는 괄호 앞까지, 공백은 하나로."""
    base = re.split(r"[,(]", road_addr, maxsplit=1)[0]
    return _WHITESPACE.sub(" ", base).strip()


# --- 측정 -------------------------------------------------------------------------------

CALL_INTERVAL_SECONDS = 1.0  # 1초에 1건, 순차 호출 (ADR-028)
TRANSPORT_RETRIES = 2  # 통신 오류 재시도 횟수 (모두 3번 호출)
PASS_RATE = Decimal("0.95")
HOLD_RATE = Decimal("0.90")

MATCH = "match"
KEYWORD_ERROR = "keyword_error"
TRANSPORT_ERROR = "transport_error"
NO_RESULT = "no_result"
MULTI_PARCEL = "multi_parcel_building"
JIBUN_CHANGED = "jibun_changed"
OTHER = "other"
# 실패 유형 (docs/50 §7 표의 순서)
FAILURE_OUTCOMES = (KEYWORD_ERROR, TRANSPORT_ERROR, NO_RESULT, MULTI_PARCEL, JIBUN_CHANGED, OTHER)
OUTCOME_LABELS = {
    KEYWORD_ERROR: "검색어 오류",
    TRANSPORT_ERROR: "통신 오류",
    NO_RESULT: "결과 없음",
    MULTI_PARCEL: "여러 필지 건물",
    JIBUN_CHANGED: "지번 변경 (추정)",
    OTHER: "기타",
}
YEAR_BANDS = ("1999년 이전", "2000~2009", "2010~2015", "2016~2020", "2021년 이후", "개업일 없음")

_LOT = re.compile(r"^(?P<san>산)?(?P<main>\d+)(?:-(?P<sub>\d+))?$")
_ERROR_CODE_REASON = "error_code_"
_UNEXPECTED_FORMAT = "unexpected_format"

Lot = tuple[str, bool, int, int]  # (법정동 이름, 산 여부, 본번, 부번)


@dataclass(frozen=True)
class SampleRecord:
    key: RecordKey
    road_addr: str
    jibun_addr: str
    pnu: str
    sigungu_code: str | None
    opened_year: int | None


@dataclass(frozen=True)
class Outcome:
    record: SampleRecord
    outcome: str


class AccessProblemError(Exception):
    """접근 문제 오류코드 — 측정을 멈춘다. 메시지에 승인키·검색어를 넣지 않는다."""

    def __init__(self, reason: str, call_no: int) -> None:
        super().__init__(f"access problem ({reason}) at call {call_no}")
        self.reason = reason
        self.call_no = call_no


class Fetch(Protocol):
    async def __call__(self, keyword: str, page: int, *, add_info: bool = False) -> Any: ...


def parse_rel_jibun(text: str | None) -> set[Lot]:
    """관련지번 `서울특별시 광진구 자양동 225-79,화양동 4-1,4-3` → 지번 집합.

    법정동 이름은 바뀔 때만 적혀 있어 앞 항목의 이름을 이어 쓴다. 읽을 수 없는 항목은 건너뛴다.
    """
    lots: set[Lot] = set()
    dong: str | None = None
    for entry in (text or "").split(","):
        words = entry.split()
        if not words:
            continue
        match = _LOT.match(words[-1])
        if match is None:
            continue
        if len(words) > 1:
            dong = words[-2]
        if dong is None:
            continue
        lots.add((dong, match["san"] is not None, int(match["main"]), int(match["sub"] or 0)))
    return lots


def lot_of(jibun_addr: str) -> Lot | None:
    parts = parse_jibun(jibun_addr)
    return None if parts is None else (parts.dong, parts.is_san, parts.main, parts.sub)


def _rows(payload: Any) -> list[dict[str, Any]]:
    rows = payload["results"].get("juso") or []
    return [row for row in rows if isinstance(row, dict)]


def classify_mismatch(record: SampleRecord, keyword: str, first: Any, add_info: Any | None) -> str:
    """후보는 있으나 같은 PNU가 없는 건의 유형. `add_info`는 다시 조회한 응답(실패했으면 `None`)."""
    if add_info is None:
        return OTHER
    lot = lot_of(record.jibun_addr)
    if lot is not None and any(
        lot in parse_rel_jibun(row.get("relJibun")) for row in _rows(add_info)
    ):
        return MULTI_PARCEL
    if any(clean_keyword(str(row.get("roadAddrPart1", ""))) == keyword for row in _rows(first)):
        return JIBUN_CHANGED
    return OTHER


class Pacer:
    """호출 시작 사이를 `interval`초 이상 띄운다. 시계와 잠들기는 밖에서 넣는다."""

    def __init__(
        self,
        clock: Callable[[], float],
        sleep: Callable[[float], Awaitable[None]],
        interval: float = CALL_INTERVAL_SECONDS,
    ) -> None:
        self._clock = clock
        self._sleep = sleep
        self._interval = interval
        self._last: float | None = None
        self.calls = 0

    async def wait(self) -> None:
        if self._last is not None:
            remaining = self._last + self._interval - self._clock()
            if remaining > 0:
                await self._sleep(remaining)
        self._last = self._clock()
        self.calls += 1


async def _call(
    fetch: Fetch, pacer: Pacer, keyword: str, *, add_info: bool
) -> tuple[JusoPage, Any] | str:
    """한 건 조회. (결과, 원래 응답) 또는 실패 유형(`KEYWORD_ERROR`, `TRANSPORT_ERROR`).

    접근 문제면 `AccessProblemError`.
    """
    for _ in range(TRANSPORT_RETRIES + 1):
        await pacer.wait()
        try:
            payload = await fetch(keyword, 1, add_info=add_info)
            return parse_response(payload, 1), payload
        except JusoKeywordError:
            return KEYWORD_ERROR
        except JusoUnavailableError as exc:
            if exc.reason.startswith(_ERROR_CODE_REASON) or exc.reason == _UNEXPECTED_FORMAT:
                raise AccessProblemError(exc.reason, pacer.calls) from None
    return TRANSPORT_ERROR


async def measure_one(record: SampleRecord, fetch: Fetch, pacer: Pacer) -> str:
    keyword = clean_keyword(keyword_of(record.road_addr))
    if len(keyword) < 2:
        return KEYWORD_ERROR  # 프록시가 422로 돌려보내는 검색어 (docs/30 §2)
    first = await _call(fetch, pacer, keyword, add_info=False)
    if isinstance(first, str):
        return first
    page, payload = first
    if record.pnu in {item.pnu for item in page.items}:
        return MATCH
    if not page.items:
        return NO_RESULT
    second = await _call(fetch, pacer, keyword, add_info=True)
    return classify_mismatch(
        record, keyword, payload, None if isinstance(second, str) else second[1]
    )


async def measure(
    sample: Sequence[SampleRecord],
    fetch: Fetch,
    pacer: Pacer,
    progress: Callable[[int, int], None] | None = None,
) -> list[Outcome]:
    """표본을 순서대로 한 건씩 잰다. 접근 문제면 `AccessProblemError`로 멈춘다."""
    outcomes: list[Outcome] = []
    for done, record in enumerate(sample, start=1):
        outcomes.append(Outcome(record, await measure_one(record, fetch, pacer)))
        if progress is not None:
            progress(done, pacer.calls)
    return outcomes


# --- 집계·리포트 --------------------------------------------------------------------------


def year_band(opened_year: int | None) -> str:
    if opened_year is None:
        return YEAR_BANDS[5]
    for limit, band in ((1999, 0), (2009, 1), (2015, 2), (2020, 3)):
        if opened_year <= limit:
            return YEAR_BANDS[band]
    return YEAR_BANDS[4]


def verdict(matched: int, total: int, *, remeasure: bool) -> str:
    """docs/50 §7 판정표. 판정은 점추정으로 한다."""
    rate = Decimal(matched) / Decimal(total)
    if rate >= PASS_RATE:
        return "통과"
    if rate < HOLD_RATE:
        return "Gate 1 보류"
    if remeasure:
        return (
            "Gate 1은 진행하되 조건 두 가지: ① 주소 검색이 안 될 때 지도에서 직접 고르는 길(T-032) "
            "② 방법론 페이지에 일치율 공개"
        )
    return "실패 유형을 분류해 고친 뒤 다시 측정한다 (한 번만, 새 seed 20261014로 새 표본 2,000건)"


def _percent(value: Decimal) -> str:
    return f"{(value * 100).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)}%"


def _rate_cells(matched: int, total: int) -> str:
    low, high = wilson_ci(matched, total)
    rate = _percent(Decimal(matched) / total)
    return f"{total:,} | {matched:,} | {rate} | {_percent(low)} ~ {_percent(high)}"


def _group_table(title: str, groups: dict[str, list[Outcome]], order: Sequence[str]) -> list[str]:
    lines = [f"| {title} | 표본 | 일치 | 일치율 | Wilson 95% |", "|---|---|---|---|---|"]
    for name in order:
        rows = groups.get(name, [])
        if rows:
            matched = sum(1 for row in rows if row.outcome == MATCH)
            lines.append(f"| {name} | {_rate_cells(matched, len(rows))} |")
    return lines


@dataclass(frozen=True)
class ReportContext:
    measured_on: str
    criteria_commit: str
    seed: int
    remeasure: bool
    population: int
    snapshots: str
    records_total: int
    records_with_pnu: int
    calls: int
    stopped_runs: str
    gu_names: dict[str, str]


def render_report(outcomes: Sequence[Outcome], ctx: ReportContext) -> str:
    total = len(outcomes)
    matched = sum(1 for row in outcomes if row.outcome == MATCH)
    rate = Decimal(matched) / Decimal(total)
    low, high = wilson_ci(matched, total)
    pnu_rate = Decimal(ctx.records_with_pnu) / Decimal(ctx.records_total)
    by_gu: dict[str, list[Outcome]] = {}
    by_band: dict[str, list[Outcome]] = {}
    for row in outcomes:
        code = row.record.sigungu_code or ""
        by_gu.setdefault(ctx.gu_names.get(code, code or "(구 코드 없음)"), []).append(row)
        by_band.setdefault(year_band(row.record.opened_year), []).append(row)
    lines = [
        "# 검색 일치율 (T-021b, docs/50 §7 사전 등록 기준)",
        "",
        "`python -m jobs.measure_search_match`가 만든 파일이다. 손으로 고치지 않는다.",
        "",
        f"- 측정일: {ctx.measured_on}",
        f"- 기준을 커밋한 날짜(커밋): {ctx.criteria_commit}",
        f"- 대상 스냅샷: {ctx.snapshots}",
        f"- 모집단(도로명주소·지번주소·지번 PNU가 모두 있는 기록): {ctx.population:,}",
        f"- 표본: {total:,}건, seed {ctx.seed}"
        + (" (재측정)" if ctx.remeasure else "")
        + ' — `sha256("{seed}:{license_type}:{mgmt_no}")` 16진 문자열 오름차순으로 앞에서부터',
        "- 검색어: 도로명주소의 첫 쉼표 또는 첫 여는 괄호 앞까지 → 프록시와 같은 검색어 정제. "
        "첫 페이지 10건의 후보 PNU 중 기록의 PNU가 있으면 일치",
        f"- 호출: 1초에 1건 순차, 통신 오류 재시도 {TRANSPORT_RETRIES}번. "
        f"도로명주소 API 호출 {ctx.calls:,}번(불일치 분류용 다시 조회 포함)",
        f"- 접근 문제로 멈춘 실행: {ctx.stopped_runs}",
        "",
        "## 결과",
        "",
        f"- **검색 일치율: {_percent(rate)}** ({matched:,} / {total:,})",
        f"- Wilson 95% 신뢰구간: {_percent(low)} ~ {_percent(high)}",
        f"- PNU 성공률: {_percent(pnu_rate)} ({ctx.records_with_pnu:,} / {ctx.records_total:,}, "
        "`license_record` 전체 중 PNU가 있는 기록)",
        f"- 종단 값(PNU 성공률 × 검색 일치율): {_percent(pnu_rate * rate)}",
        f"- **판정: {verdict(matched, total, remeasure=ctx.remeasure)}**"
        " (95% 이상 통과 / 90% 이상 95% 미만 / 90% 미만, 점추정 기준)",
        "",
        "## 실패 유형별",
        "",
        "유형의 정의는 docs/50 §7. 위에서부터 처음 맞는 유형 하나로 센다.",
        "",
        "| 유형 | 건수 | 표본 대비 |",
        "|---|---|---|",
    ]
    for name in FAILURE_OUTCOMES:
        count = sum(1 for row in outcomes if row.outcome == name)
        lines.append(f"| {OUTCOME_LABELS[name]} | {count:,} | {_percent(Decimal(count) / total)} |")
    lines += [f"| 합계 | {total - matched:,} | {_percent(Decimal(total - matched) / total)} |", ""]
    lines += ["## 구별 (참고 — 판정은 전체 값)", ""]
    lines += _group_table("구", by_gu, sorted(by_gu))
    lines += ["", "## 개업연도별 (참고 — 판정은 전체 값)", ""]
    lines += _group_table("개업연도", by_band, YEAR_BANDS)
    return "\n".join(lines) + "\n"
