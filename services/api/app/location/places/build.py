"""장소 응답의 판단 부분: 진행 일수, 버킷, 층 규모, 기준율 선택, 알림, 같은 호 묶음.

순수 함수만 둔다. DB 행은 `queries`가 읽어 넘기고, 기준일은 인자로 받는다.
"""

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import Literal

from app.location.history.build import LARGE_FROM, SMALL_FROM
from app.location.stats.base_rate import MIN_DISPLAY_N

SEOUL_SCOPE = "11"
SEOUL_LABEL = "서울"
BASELINE_BUCKET = "0"
TOP_BUCKET = 4  # `4+`

FloorScale = Literal["single", "small", "large"]
HiddenReason = Literal["not_confirmed_for_floor_scale", "insufficient_sample"]


@dataclass(frozen=True)
class Record:
    """이력에 보이는 기록 한 건 (docs/10 §7.1의 `H`)."""

    record_id: int
    name: str
    license_type: str
    biz_category: str | None
    opened_on: date | None
    closed_on: date | None
    status: str
    ho_list: tuple[str, ...]
    bulk_closure: bool
    stale_suspect: bool
    floor: str | None
    surge_label: str | None  # 급증일의 관할 이름 (`closure_surge_day.jurisdiction_label`)
    surge_count: int | None  # 급증일의 관할 폐업 건수. 급증일 기록이 아니면 None


@dataclass(frozen=True)
class RateRow:
    """`base_rate` 한 행 (한 규모·한 범위·한 버킷)."""

    scope_code: str
    bucket: str
    n: int
    rate: Decimal
    ci_low: Decimal
    ci_high: Decimal


@dataclass(frozen=True)
class RateChoice:
    primary: RateRow | None
    baseline: RateRow | None
    secondary: RateRow | None
    hidden_reason: HiddenReason | None

    @property
    def display(self) -> bool:
        return self.hidden_reason is None


def tenure_days(record: Record, as_of: date) -> int | None:
    """(`closed_on` 또는 기준일) − `opened_on`. 개업일이 없거나 폐업인데 폐업일이 없으면 None."""
    if record.opened_on is None:
        return None
    if record.status == "closed":
        return None if record.closed_on is None else (record.closed_on - record.opened_on).days
    end = record.closed_on if record.closed_on is not None else as_of
    return (end - record.opened_on).days


def bucket_of(prior_closures: int) -> str:
    """과거 폐업 횟수 → 버킷 `0`~`3`, `4+` (docs/10 §7.2)."""
    return "4+" if prior_closures >= TOP_BUCKET else str(prior_closures)


def floor_scale(max_concurrent: int) -> FloorScale:
    """동시에 영업한 최대 점포 수 → 층 규모 (docs/10 §7.2, `history.build.scale_of`와 같은 경계)."""
    if max_concurrent >= LARGE_FROM:
        return "large"
    if max_concurrent >= SMALL_FROM:
        return "small"
    return "single"


def scale_holds(by_floor_scale: object, scale: FloorScale) -> bool:
    """모형 카드 `by_floor_scale.{규모}.holds`가 참인가. 값이 없거나 참이 아니면 거짓."""
    if not isinstance(by_floor_scale, Mapping):
        return False
    entry = by_floor_scale.get(scale)
    return isinstance(entry, Mapping) and entry.get("holds") is True


def choose_rates(
    rows: Iterable[RateRow], sigungu_code: str, bucket: str, holds: bool
) -> RateChoice:
    """같은 규모의 `base_rate` 행에서 주·기준선·보조 값을 고른다 (docs/30 §2 `base_rate`).

    `rows`는 이미 그 층의 규모로 거른 행이다. 깨진 규모(`holds` 거짓)는 행이 있어도 쓰지 않는다.
    """
    if not holds:
        return RateChoice(None, None, None, "not_confirmed_for_floor_scale")
    table = {(row.scope_code, row.bucket): row for row in rows}

    def usable(scope: str, wanted: str) -> RateRow | None:
        row = table.get((scope, wanted))
        return row if row is not None and row.n >= MIN_DISPLAY_N else None

    local, seoul = usable(sigungu_code, bucket), usable(SEOUL_SCOPE, bucket)
    if local is None and seoul is None:
        return RateChoice(None, None, None, "insufficient_sample")
    primary = local if local is not None else seoul
    assert primary is not None
    baseline = usable(primary.scope_code, BASELINE_BUCKET) or usable(SEOUL_SCOPE, BASELINE_BUCKET)
    secondary = seoul if local is not None else None
    return RateChoice(primary, baseline, secondary, None)


def notices(has_concurrent: bool, history: Sequence[Record], pre_2005_floorless: bool) -> list[str]:
    """알림 값 (docs/10 §7.1 조건표). 순서는 표의 순서.

    `pre_2005_floorless`: 같은 필지의 층 정보 없는 기록 중 2005-01-01 전에 개업한 기록이 있다.
    """
    found: list[str] = []
    if has_concurrent:
        found.append("multiple_units_possible")
    if any(record.bulk_closure for record in history):
        found.append("bulk_closure_present")
    if any(record.stale_suspect for record in history):
        found.append("stale_suspect_present")
    if pre_2005_floorless:
        found.append("pre_2005_floor_missing")
    return found


def ho_groups(history: Sequence[Record]) -> list[tuple[str, list[int]]]:
    """같은 호를 가진 기록이 2건 이상인 호마다 `(호, 기록 ID 목록)`. 호 문자열 오름차순."""
    by_ho: dict[str, list[int]] = {}
    for record in history:
        for ho in dict.fromkeys(record.ho_list):
            by_ho.setdefault(ho, []).append(record.record_id)
    return [(ho, ids) for ho, ids in sorted(by_ho.items()) if len(ids) >= 2]
