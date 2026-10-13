"""모형 카드: 설정별 계산, 결론 유지 판정, `model_card.payload` 구조 (docs/10 §7.3).

순수 계산만 한다.
"""

from dataclasses import dataclass
from datetime import date
from decimal import ROUND_HALF_UP, Decimal
from typing import Literal

import pandas as pd
from pydantic import BaseModel, ConfigDict, Field

from app.location.history.build import METHOD_VERSION, SINCE
from app.location.stats import w0
from app.location.stats.base_rate import (
    BucketRate,
    Setting,
    bucket_rates,
    build_cohort,
    censored_rates,
    cohort_to,
    separated,
)
from app.location.stats.model import (
    SE,
    SPEC,
    TEST_FROM,
    TEST_UNTIL,
    TRAIN_UNTIL,
    LogitFit,
    fit_by_sigungu,
    fit_logit,
    model_frame,
    out_of_time,
)

SEOUL = "11"
FOOD3 = "food3"
_RATE = Decimal("0.0001")  # base_rate.rate와 같은 자릿수 (docs/04)

Bucket = Literal["0", "1", "2", "3", "4+"]


def quantize(value: Decimal) -> Decimal:
    return value.quantize(_RATE, rounding=ROUND_HALF_UP)


class _Model(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)


class BucketOut(_Model):
    bucket: Bucket
    n: int
    events: int
    rate: Decimal
    ci: tuple[Decimal, Decimal]


class LogitOut(_Model):
    n: int
    or_per_prior: float
    ci: tuple[float, float]
    p: float


class OtherFloorOut(_Model):
    or_per_prior: float
    ci: tuple[float, float]
    or_other_floor: float


class MainLogitOut(LogitOut):
    spec: str
    se: str
    with_other_floor_control: OtherFloorOut | None


class SigunguOut(_Model):
    sigungu: str
    n: int
    # 적합하지 못한 시군구는 값이 없다
    or_: float | None = Field(alias="or")
    ci: tuple[float, float] | None


class OutOfTimeOut(_Model):
    train: str
    test: str
    auc_base: float
    auc_with_prior: float


class DataOut(_Model):
    snapshot_label: str
    license_group: str
    as_of: date
    cohort_from: date
    cohort_to: date
    n: int
    event_rate: Decimal


class SettingOut(_Model):
    bulk_exclusion: Literal["none", "surge_rule", "w0_citywide_100"]
    convenience_store: Literal["excluded", "included"]
    exclude_stale: Literal["none", "same_ho", "same_ho_or_area"]
    floor_unknown: Literal["all", "exclude_parcels_with_floorless_closure"]


class SettingResult(_Model):
    """설정 하나의 결과와 판정 (a)(b)."""

    is_default: bool
    n: int
    event_rate: Decimal
    buckets: list[BucketOut]
    logit: LogitOut | None  # 적합하지 못했으면 없다 → (b)는 거짓
    criterion_a: bool
    criterion_b: bool


class BulkExclusionOut(_Model):
    none: SettingResult
    surge_rule: SettingResult
    w0_citywide_100: SettingResult


class ConvenienceStoreOut(_Model):
    excluded: SettingResult
    included: SettingResult


class ExcludeStaleOut(_Model):
    none: SettingResult
    same_ho: SettingResult
    same_ho_or_area: SettingResult


class FloorUnknownOut(_Model):
    all: SettingResult
    exclude_parcels_with_floorless_closure: SettingResult


class CensoredBucketOut(_Model):
    bucket: Bucket
    n: int
    censored: int
    rate: float
    ci: tuple[float, float]


class CensoredOut(_Model):
    n: int
    buckets: list[CensoredBucketOut]


class SensitivityOut(_Model):
    bulk_exclusion: BulkExclusionOut
    convenience_store: ConvenienceStoreOut
    exclude_stale: ExcludeStaleOut
    floor_unknown: FloorUnknownOut
    bulk_as_censored: CensoredOut


class FailureOut(_Model):
    axis: str
    value: str
    criterion: Literal["a", "b"]
    detail: str


class RobustnessOut(_Model):
    holds: bool
    failures: list[FailureOut]


class ModelCardPayload(_Model):
    """`model_card.payload`. W0 재현 모드에는 설정·민감도·판정이 없다."""

    data: DataOut
    default_setting: SettingOut | None
    base_rates: list[BucketOut]
    logit: MainLogitOut | None
    by_sigungu: list[SigunguOut]
    out_of_time: OutOfTimeOut | None
    sensitivity: SensitivityOut | None
    robustness: RobustnessOut | None


@dataclass(frozen=True)
class ScopeRate:
    """`base_rate` 한 행 (범위 × 버킷)."""

    scope_code: str
    rate: BucketRate


@dataclass(frozen=True)
class Computation:
    method_version: str
    license_group: str
    cohort_from: date
    cohort_to: date
    card: ModelCardPayload
    rates: list[ScopeRate]


# 기본 설정에서 한 번에 한 항목만 바꾼다 (docs/10 §7.3)
VARIANTS: list[tuple[str, str, Setting]] = [
    ("bulk_exclusion", "none", Setting(bulk_exclusion="none")),
    ("bulk_exclusion", "surge_rule", Setting()),
    ("bulk_exclusion", "w0_citywide_100", Setting(bulk_exclusion="w0_citywide_100")),
    ("convenience_store", "excluded", Setting()),
    ("convenience_store", "included", Setting(convenience_store="included")),
    ("exclude_stale", "none", Setting()),
    ("exclude_stale", "same_ho", Setting(exclude_stale="same_ho")),
    ("exclude_stale", "same_ho_or_area", Setting(exclude_stale="same_ho_or_area")),
    ("floor_unknown", "all", Setting()),
    (
        "floor_unknown",
        "exclude_parcels_with_floorless_closure",
        Setting(floor_unknown="exclude_parcels_with_floorless_closure"),
    ),
]


def bucket_out(rate: BucketRate) -> BucketOut:
    return BucketOut(
        bucket=rate.bucket,
        n=rate.n,
        events=rate.events,
        rate=quantize(rate.rate),
        ci=(quantize(rate.ci_low), quantize(rate.ci_high)),
    )


def _event_rate(cohort: pd.DataFrame) -> Decimal:
    if cohort.empty:
        return Decimal(0)
    return quantize(Decimal(int(cohort["event"].sum())) / Decimal(len(cohort)))


def _logit_out(fit: LogitFit) -> LogitOut:
    return LogitOut(n=fit.n, or_per_prior=fit.or_per_prior, ci=(fit.ci_low, fit.ci_high), p=fit.p)


def setting_result(
    cohort: pd.DataFrame, fit: LogitFit | None, *, is_default: bool
) -> SettingResult:
    """판정 (a): 4+와 0의 Wilson 구간이 겹치지 않음. (b): OR 95% 구간 하한 > 1."""
    rates = bucket_rates(cohort)
    return SettingResult(
        is_default=is_default,
        n=len(cohort),
        event_rate=_event_rate(cohort),
        buckets=[bucket_out(rate) for rate in rates],
        logit=None if fit is None else _logit_out(fit),
        criterion_a=separated(rates),
        criterion_b=fit is not None and fit.ci_low > 1,
    )


def _failure_detail(result: SettingResult, criterion: str) -> str:
    if criterion == "a":
        by_bucket = {bucket.bucket: bucket for bucket in result.buckets}
        parts = [
            f"{name}: {b.rate} ({b.ci[0]}~{b.ci[1]}, n={b.n})" if b else f"{name}: 기록 없음"
            for name, b in (("0", by_bucket.get("0")), ("4+", by_bucket.get("4+")))
        ]
        return ", ".join(parts)
    if result.logit is None:
        return "로지스틱 적합 실패(수렴하지 않음 또는 적합 불가)"
    low, high = result.logit.ci
    return f"OR {result.logit.or_per_prior:.4f} ({low:.4f}~{high:.4f}), n={result.logit.n}"


def judge(results: dict[tuple[str, str], SettingResult]) -> RobustnessOut:
    """모든 설정에서 (a)(b)가 참이어야 결론이 유지된다."""
    failures: list[FailureOut] = []
    default_seen = False
    for (axis, value), result in results.items():
        # 기본 설정은 축마다 한 번씩 들어 있다 — 실패는 한 번만 적는다
        if result.is_default and default_seen:
            continue
        default_seen = default_seen or result.is_default
        for name, passed in (("a", result.criterion_a), ("b", result.criterion_b)):
            if not passed:
                failures.append(
                    FailureOut(
                        axis="default" if result.is_default else axis,
                        value="default" if result.is_default else value,
                        criterion=name,
                        detail=_failure_detail(result, name),
                    )
                )
    return RobustnessOut(holds=not failures, failures=failures)


def _main_logit(frame: pd.DataFrame, fit: LogitFit | None) -> MainLogitOut | None:
    if fit is None:
        return None
    other = fit_logit(frame, other_floor=True)
    return MainLogitOut(
        **_logit_out(fit).model_dump(),
        spec=SPEC,
        se=SE,
        with_other_floor_control=None
        if other is None or other.or_other_floor is None
        else OtherFloorOut(
            or_per_prior=other.or_per_prior,
            ci=(other.ci_low, other.ci_high),
            or_other_floor=other.or_other_floor,
        ),
    )


def _by_sigungu(frame: pd.DataFrame, labels: dict[str, str], *, cluster: bool) -> list[SigunguOut]:
    return [
        SigunguOut(
            sigungu=labels.get(item.sigungu, item.sigungu),
            n=item.n,
            or_=None if item.fit is None else item.fit.or_per_prior,
            ci=None if item.fit is None else (item.fit.ci_low, item.fit.ci_high),
        )
        for item in fit_by_sigungu(frame, cluster=cluster)
    ]


def _out_of_time(frame: pd.DataFrame) -> OutOfTimeOut | None:
    result = out_of_time(frame)
    if result is None:
        return None
    return OutOfTimeOut(
        train=f"{SINCE.year}-{TRAIN_UNTIL}",
        test=f"{TEST_FROM}-{TEST_UNTIL}",
        auc_base=result.auc_base,
        auc_with_prior=result.auc_with_prior,
    )


def _scope_rates(cohort: pd.DataFrame, *, by_sigungu: bool) -> list[ScopeRate]:
    rates = [ScopeRate(SEOUL, rate) for rate in bucket_rates(cohort)]
    if by_sigungu:
        for code, rows in cohort[cohort["sigungu_code"].notna()].groupby("sigungu_code", sort=True):
            rates += [ScopeRate(str(code), rate) for rate in bucket_rates(rows)]
    return rates


def compute(records: pd.DataFrame, as_of: date, sigungu_labels: dict[str, str]) -> Computation:
    """method_version `2026.10.1`: 기본 설정의 기준율·모형과 민감도 설정들, 판정."""
    last_opened = cohort_to(as_of)
    default = Setting()
    cohorts: dict[Setting, pd.DataFrame] = {}
    frames: dict[Setting, pd.DataFrame] = {}
    fits: dict[Setting, LogitFit | None] = {}
    results: dict[tuple[str, str], SettingResult] = {}
    for axis, value, setting in VARIANTS:
        if setting not in cohorts:
            cohorts[setting] = build_cohort(records, setting, last_opened)
            frames[setting] = model_frame(cohorts[setting])
            fits[setting] = fit_logit(frames[setting])
        results[(axis, value)] = setting_result(
            cohorts[setting], fits[setting], is_default=setting == default
        )

    cohort, frame = cohorts[default], frames[default]
    censored_cohort = build_cohort(records, default, last_opened, keep_surge=True)
    by_axis: dict[str, dict[str, SettingResult]] = {}
    for (axis, value), result in results.items():
        by_axis.setdefault(axis, {})[value] = result
    sensitivity = SensitivityOut.model_validate(
        {
            **by_axis,
            "bulk_as_censored": {
                "n": len(censored_cohort),
                "buckets": [
                    {
                        "bucket": rate.bucket,
                        "n": rate.n,
                        "censored": rate.censored,
                        "rate": rate.rate,
                        "ci": (rate.ci_low, rate.ci_high),
                    }
                    for rate in censored_rates(censored_cohort)
                ],
            },
        }
    )
    card = ModelCardPayload(
        data=DataOut(
            snapshot_label=as_of.strftime("%Y-%m"),
            license_group=FOOD3,
            as_of=as_of,
            cohort_from=SINCE,
            cohort_to=last_opened,
            n=len(cohort),
            event_rate=_event_rate(cohort),
        ),
        default_setting=SettingOut(
            bulk_exclusion=default.bulk_exclusion,
            convenience_store=default.convenience_store,
            exclude_stale=default.exclude_stale,
            floor_unknown=default.floor_unknown,
        ),
        base_rates=[bucket_out(rate) for rate in bucket_rates(cohort)],
        logit=_main_logit(frame, fits[default]),
        by_sigungu=_by_sigungu(frame, sigungu_labels, cluster=True),
        out_of_time=_out_of_time(frame),
        sensitivity=sensitivity,
        robustness=judge(results),
    )
    return Computation(
        METHOD_VERSION, FOOD3, SINCE, last_opened, card, _scope_rates(cohort, by_sigungu=True)
    )


def compute_w0(general_records: pd.DataFrame) -> Computation:
    """method_version `w0`: 일반음식점, W0 층키·층 파서·일괄 폐업 정의 (docs/10 §7.4)."""
    cohort = build_cohort(w0.prepare(general_records), w0.SETTING, w0.LAST_OPENED, w0=True)
    frame = model_frame(cohort)
    card = ModelCardPayload(
        data=DataOut(
            snapshot_label=w0.AS_OF.strftime("%Y-%m"),
            license_group=w0.LICENSE_GROUP,
            as_of=w0.AS_OF,
            cohort_from=SINCE,
            cohort_to=w0.LAST_OPENED,
            n=len(cohort),
            event_rate=_event_rate(cohort),
        ),
        default_setting=None,
        base_rates=[bucket_out(rate) for rate in bucket_rates(cohort)],
        logit=_main_logit(frame, fit_logit(frame)),
        by_sigungu=_by_sigungu(frame, {}, cluster=False),
        out_of_time=_out_of_time(frame),
        sensitivity=None,
        robustness=None,
    )
    return Computation(
        w0.METHOD_VERSION,
        w0.LICENSE_GROUP,
        SINCE,
        w0.LAST_OPENED,
        card,
        _scope_rates(cohort, by_sigungu=False),
    )
