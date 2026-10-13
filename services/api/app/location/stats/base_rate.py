"""기준율: 설정별 코호트, 버킷별 3년 내 폐업률, Wilson 신뢰구간 (docs/10 §7.2·§7.3).

순수 계산만 한다.

입력 `records`의 열: `id, license_type, pnu, floor, status, opened_on, closed_on, bulk_closure,
stale_suspect, stale_area_match, no_fixed_place, biz_category, area_m2, sigungu_code`
(`license_record` 전체 — W0 정의의 급증일은 `pnu`가 없는 기록도 센다).
"""

from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal
from typing import Any, Literal

import numpy as np
import pandas as pd

from app.location.history.build import SINCE, prior_closures

BUCKETS = ("0", "1", "2", "3", "4+")
FOLLOW_UP_DAYS = 1095
MIN_DISPLAY_N = 200  # 이보다 작은 버킷은 화면에 내지 않는다 (docs/10 §7.2)
W0_MIN_DAILY = 100  # W0 정의: 서울 전체 일반음식점 폐업이 하루 이 건수 이상인 날
CONVENIENCE_STORE = "편의점"
_Z = Decimal("1.96")

BulkExclusion = Literal["none", "surge_rule", "w0_citywide_100"]
ConvenienceStore = Literal["excluded", "included"]
ExcludeStale = Literal["none", "same_ho", "same_ho_or_area"]
FloorUnknown = Literal["all", "exclude_parcels_with_floorless_closure"]


@dataclass(frozen=True)
class Setting:
    """코호트 설정. 기본값이 기본 설정이다 (docs/10 §7.2)."""

    bulk_exclusion: BulkExclusion = "surge_rule"
    convenience_store: ConvenienceStore = "excluded"
    exclude_stale: ExcludeStale = "none"
    floor_unknown: FloorUnknown = "all"


@dataclass(frozen=True)
class BucketRate:
    bucket: str
    n: int
    events: int
    rate: Decimal
    ci_low: Decimal
    ci_high: Decimal


def wilson_ci(events: int, n: int) -> tuple[Decimal, Decimal]:
    """Wilson 95% 신뢰구간 (docs/10 §7.2의 식 그대로, 반올림하지 않는다)."""
    if n <= 0 or not 0 <= events <= n:
        raise ValueError(f"events={events}, n={n}: 0 <= events <= n, n > 0 이어야 합니다")
    size = Decimal(n)
    p = Decimal(events) / size
    denominator = 1 + _Z * _Z / size
    center = (p + _Z * _Z / (2 * size)) / denominator
    half = _Z * (p * (1 - p) / size + _Z * _Z / (4 * size * size)).sqrt() / denominator
    return center - half, center + half


def cohort_to(as_of: date) -> date:
    """코호트의 마지막 개업일: 기준일까지 3년을 지켜볼 수 있는 날."""
    return as_of - timedelta(days=FOLLOW_UP_DAYS)


def surge_flags(records: pd.DataFrame, definition: BulkExclusion) -> "pd.Series[bool]":
    """급증일 폐업으로 보는 기록 (docs/10 §7.3 `bulk_exclusion`)."""
    if definition == "none":
        return pd.Series(False, index=records.index)
    if definition == "surge_rule":
        return records["bulk_closure"].astype(bool)
    general = (
        (records["license_type"] == "general_restaurant")
        & (records["status"] == "closed")
        & records["closed_on"].notna()
    )
    daily = records.loc[general, "closed_on"].value_counts()
    return general & records["closed_on"].isin(daily[daily >= W0_MIN_DAILY].index)


def build_cohort(
    records: pd.DataFrame,
    setting: Setting,
    last_opened: date,
    *,
    keep_surge: bool = False,
    w0: bool = False,
) -> pd.DataFrame:
    """설정에 맞는 코호트. 행마다 `prior`(과거 폐업 횟수), `other_floor`, `event`, `surge` 등.

    `keep_surge`: 급증일 폐업 기록을 코호트에 남긴다 (중도절단 민감도용).
    `w0`: W0 재현 방식 — 급증일 폐업도 과거 폐업 횟수에 세고, 면적이 0보다 큰 기록만 둔다.
    """
    surge = surge_flags(records, setting.bulk_exclusion)
    fixed = records[records["pnu"].notna() & ~records["no_fixed_place"].astype(bool)]
    floor_records = fixed[fixed["floor"].notna()]

    not_counted = None if w0 else surge
    prior = prior_closures(
        floor_records, None if not_counted is None else not_counted[floor_records.index]
    )
    in_building = prior_closures(
        fixed.assign(floor=""), None if not_counted is None else not_counted[fixed.index]
    )

    rows = floor_records.loc[prior.index]
    opened = pd.to_datetime(rows["opened_on"])
    closed = pd.to_datetime(rows["closed_on"], errors="coerce")
    tenure = (closed - opened).dt.days
    area = pd.to_numeric(rows["area_m2"], errors="coerce").astype("float64")

    keep = (opened >= pd.Timestamp(SINCE)) & (opened <= pd.Timestamp(last_opened))
    if not keep_surge:
        keep &= ~surge[rows.index]
    if setting.convenience_store == "excluded":
        keep &= ~(rows["biz_category"] == CONVENIENCE_STORE)
    if setting.exclude_stale != "none":
        stale = rows["stale_suspect"].astype(bool)
        if setting.exclude_stale == "same_ho_or_area":
            stale |= rows["stale_area_match"].astype(bool)
        keep &= ~stale
    if setting.floor_unknown == "exclude_parcels_with_floorless_closure":
        floorless = fixed[fixed["floor"].isna() & (fixed["status"] == "closed")]
        keep &= ~rows["pnu"].isin(floorless["pnu"])
    if w0:
        keep &= area > 0

    result = pd.DataFrame(
        {
            "id": rows["id"],
            "pnu": rows["pnu"],
            "floor": rows["floor"],
            "sigungu_code": rows["sigungu_code"],
            "biz_category": rows["biz_category"],
            "area_m2": area,
            "opened_on": opened,
            "tenure_days": tenure,
            "prior": prior,
            "other_floor": (in_building[prior.index] - prior).clip(lower=0, upper=20),
            "event": (rows["status"] == "closed") & (tenure <= FOLLOW_UP_DAYS),
            "surge": surge[rows.index],
        }
    )
    return result[keep]


def bucket_of(prior: "pd.Series[Any]") -> "pd.Series[str]":
    labels = prior.clip(upper=4).astype(int).astype(str)
    return labels.where(prior < 4, "4+")


def bucket_rates(cohort: pd.DataFrame) -> list[BucketRate]:
    """버킷별 n·사건 수·비율·Wilson 구간. 기록이 없는 버킷은 내지 않는다."""
    grouped = cohort["event"].astype(int).groupby(bucket_of(cohort["prior"]))
    sizes = {str(bucket): int(n) for bucket, n in grouped.size().items()}
    sums = {str(bucket): int(n) for bucket, n in grouped.sum().items()}
    rates = []
    for bucket in BUCKETS:
        if bucket not in sizes:
            continue
        n, events = sizes[bucket], sums[bucket]
        low, high = wilson_ci(events, n)
        rates.append(BucketRate(bucket, n, events, Decimal(events) / Decimal(n), low, high))
    return rates


def separated(rates: list[BucketRate]) -> bool:
    """판정 (a): `4+`의 비율이 `0`보다 높고 두 Wilson 구간이 겹치지 않는가 (docs/10 §7.3)."""
    by_bucket = {rate.bucket: rate for rate in rates}
    if "0" not in by_bucket or "4+" not in by_bucket:
        return False
    return by_bucket["4+"].ci_low > by_bucket["0"].ci_high


@dataclass(frozen=True)
class CensoredRate:
    bucket: str
    n: int
    censored: int  # 1,095일 안에 급증일 폐업으로 중도절단된 기록
    rate: float
    ci_low: float
    ci_high: float


def censored_rates(cohort: pd.DataFrame) -> list[CensoredRate]:
    """급증일 폐업을 중도절단으로 본 버킷별 1,095일 내 폐업 비율 (Kaplan–Meier, Greenwood).

    `cohort`는 `keep_surge=True`로 만든 것. 같은 날의 사건은 중도절단보다 먼저 센다.
    """
    result = []
    buckets = bucket_of(cohort["prior"])
    for bucket in BUCKETS:
        rows = cohort[buckets == bucket]
        if rows.empty:
            continue
        closed_early = (rows["tenure_days"] <= FOLLOW_UP_DAYS).to_numpy(dtype=bool)
        surge = rows["surge"].to_numpy(dtype=bool)
        # 3년 넘게 지켜본 기록은 끝까지 위험 집합에 남는다
        time = np.where(closed_early, rows["tenure_days"].to_numpy(dtype=np.float64), np.inf)
        event = closed_early & ~surge
        ordered = np.sort(time)
        at, deaths = np.unique(time[event], return_counts=True)
        at_risk = len(time) - np.searchsorted(ordered, at, "left")
        survival = float(np.prod(1 - deaths / at_risk))
        still = at_risk > deaths
        variance = survival**2 * float(
            np.sum(deaths[still] / (at_risk[still] * (at_risk[still] - deaths[still])))
        )
        half = 1.96 * variance**0.5
        rate = 1 - survival
        result.append(
            CensoredRate(
                bucket,
                len(rows),
                int((closed_early & surge).sum()),
                rate,
                max(0.0, rate - half),
                min(1.0, rate + half),
            )
        )
    return result
