"""모형 카드의 로지스틱·판정·payload 구조 (docs/10 §7.3). 기록은 모두 난수로 만든 가상 예시다."""

from datetime import date, timedelta
from decimal import Decimal

import numpy as np
import pandas as pd
import pytest

from app.location.stats.base_rate import Setting, build_cohort, cohort_to
from app.location.stats.card import (
    VARIANTS,
    ModelCardPayload,
    SettingResult,
    compute,
    judge,
    setting_result,
)
from app.location.stats.floor_scale import record_count_range
from app.location.stats.model import auc, fit_logit, model_frame, out_of_time
from app.location.stats.report import render, scale_failures, variants

AS_OF = date(2026, 10, 7)
SIGUNGU = {"11215": "광진구", "11440": "마포구"}


def synthetic(seed: int, effect: float, floors: int = 1500) -> pd.DataFrame:
    """층마다 가게가 차례로 들어선다. 3년 내 폐업 확률 = 0.25 + effect × min(과거 폐업, 4)."""
    rng = np.random.default_rng(seed)
    rows: list[dict[str, object]] = []
    for floor_no in range(floors):
        code = "11215" if floor_no % 2 else "11440"
        pnu = f"{code}10700{floor_no:09d}"
        floor = ("B1", "1", "2")[floor_no % 3]
        opened, closures = date(2005, 1, 1) + timedelta(days=int(rng.integers(0, 2000))), 0
        while opened <= date(2022, 12, 31):
            early = rng.random() < 0.25 + effect * min(closures, 4)
            tenure = int(rng.integers(100, 1000) if early else rng.integers(1200, 2500))
            closed = opened + timedelta(days=tenure)
            still_open = closed > AS_OF
            rows.append(
                {
                    "id": len(rows) + 1,
                    "license_type": "general_restaurant",
                    "pnu": pnu,
                    "floor": floor,
                    "status": "open" if still_open else "closed",
                    "opened_on": opened,
                    "closed_on": None if still_open else closed,
                    "bulk_closure": False,
                    "stale_suspect": False,
                    "stale_area_match": False,
                    "no_fixed_place": False,
                    "biz_category": ("한식", "분식", "카페", "편의점")[int(rng.integers(0, 4))],
                    "area_m2": Decimal(int(rng.integers(15, 200))),
                    "sigungu_code": code,
                    "suppressed": False,
                }
            )
            if still_open:
                break
            closures += 1
            opened = closed + timedelta(days=int(rng.integers(1, 90)))
    return pd.DataFrame(rows)


@pytest.fixture(scope="module")
def strong() -> pd.DataFrame:
    return synthetic(seed=1, effect=0.10)


def frame_of(records: pd.DataFrame) -> pd.DataFrame:
    return model_frame(build_cohort(records, Setting(), cohort_to(AS_OF)))


def test_model_frame_derives_variables(strong: pd.DataFrame) -> None:
    frame = frame_of(strong)
    assert frame["k"].max() <= 5
    assert set(frame["basement"]) == {0.0, 1.0} and set(frame["upper"]) == {0.0, 1.0}
    assert not (frame["basement"].astype(bool) & frame["upper"].astype(bool)).any()
    assert "편의점" not in set(frame["biz"])  # 기본 설정은 편의점을 코호트에서 뺀다


def test_logit_recovers_positive_effect(strong: pd.DataFrame) -> None:
    fit = fit_logit(frame_of(strong))
    assert fit is not None
    assert fit.ci_low > 1 and fit.ci_low < fit.or_per_prior < fit.ci_high
    with_other = fit_logit(frame_of(strong), other_floor=False, cluster=False)
    assert with_other is not None
    assert with_other.or_per_prior == pytest.approx(fit.or_per_prior)  # 점추정은 같다


def test_logit_without_effect_does_not_pass_criterion_b() -> None:
    records = synthetic(seed=2, effect=0.0)
    cohort = build_cohort(records, Setting(), cohort_to(AS_OF))
    fit = fit_logit(model_frame(cohort))
    assert fit is not None and fit.ci_low <= 1
    result = setting_result(cohort, fit, is_default=True)
    assert not result.criterion_b


def test_logit_returns_none_when_it_cannot_be_fitted(strong: pd.DataFrame) -> None:
    frame = frame_of(strong)
    constant = frame.assign(k=1.0)
    assert fit_logit(constant) is None
    cohort = build_cohort(strong, Setting(), cohort_to(AS_OF))
    assert not setting_result(cohort, None, is_default=True).criterion_b


def test_auc_known_values() -> None:
    outcome = np.array([0, 0, 1, 1])
    assert auc(outcome, np.array([0.1, 0.2, 0.8, 0.9])) == 1.0
    assert auc(outcome, np.array([0.9, 0.8, 0.2, 0.1])) == 0.0
    assert auc(outcome, np.array([0.1, 0.8, 0.2, 0.9])) == 0.75


def test_out_of_time_prior_improves_auc_when_effect_exists(strong: pd.DataFrame) -> None:
    result = out_of_time(frame_of(strong))
    assert result is not None
    assert result.auc_with_prior > result.auc_base


def result_with(a: bool, b: bool, *, default: bool = False) -> SettingResult:
    return SettingResult(
        is_default=default,
        n=10,
        event_rate=Decimal("0.3"),
        buckets=[],
        logit=None,
        criterion_a=a,
        criterion_b=b,
    )


def results_with(broken: dict[tuple[str, str], tuple[bool, bool]]):
    return {
        (axis, value): result_with(*broken.get((axis, value), (True, True)), default=s == Setting())
        for axis, value, s in VARIANTS
    }


def test_judge_holds_only_when_every_setting_passes_both() -> None:
    assert judge(results_with({})).holds
    one = judge(results_with({("exclude_stale", "same_ho"): (True, False)}))
    assert not one.holds
    assert [(f.axis, f.value, f.criterion) for f in one.failures] == [
        ("exclude_stale", "same_ho", "b")
    ]


def test_judge_reports_default_setting_failure_once() -> None:
    default_keys = {(axis, value): (False, True) for axis, value, s in VARIANTS if s == Setting()}
    verdict = judge(results_with(default_keys))
    assert [(f.axis, f.criterion) for f in verdict.failures] == [("default", "a")]


def test_variants_change_one_item_at_a_time() -> None:
    default = Setting()
    changed = [s for _, _, s in VARIANTS if s != default]
    assert len(changed) == 6 and len(set(changed)) == 6
    for setting in changed:
        differing = [
            name
            for name in ("bulk_exclusion", "convenience_store", "exclude_stale", "floor_unknown")
            if getattr(setting, name) != getattr(default, name)
        ]
        assert len(differing) == 1


def test_compute_payload_matches_documented_structure(strong: pd.DataFrame) -> None:
    computation = compute(strong, AS_OF, SIGUNGU)
    payload = computation.card.model_dump(mode="json", by_alias=True)
    card = ModelCardPayload.model_validate(payload)  # docs/10 §7.3 구조
    assert set(payload) == {
        "data", "default_setting", "base_rates", "logit", "by_sigungu", "out_of_time",
        "sensitivity", "robustness", "by_floor_scale", "by_floor_scale_full_history",
        "floor_record_count",
    }  # fmt: skip
    assert set(payload["sensitivity"]) == {
        "bulk_exclusion", "convenience_store", "exclude_stale", "floor_unknown", "bulk_as_censored",
        "license_type",
    }  # fmt: skip
    assert set(payload["by_floor_scale"]) == {"single", "small", "large"}
    assert set(payload["by_floor_scale"]["single"]) == {
        "n", "event_rate", "buckets", "logit", "criterion_a", "criterion_b", "holds",
    }  # fmt: skip
    assert set(payload["sensitivity"]["bulk_exclusion"]) == {
        "none",
        "surge_rule",
        "w0_citywide_100",
    }
    assert payload["data"]["cohort_to"] == "2023-10-08"
    assert payload["default_setting"]["bulk_exclusion"] == "surge_rule"
    assert {item["sigungu"] for item in payload["by_sigungu"]} == {"광진구", "마포구"}
    assert "or" in payload["by_sigungu"][0]
    assert isinstance(payload["base_rates"][0]["rate"], str)  # 비율은 Decimal 문자열

    assert card.sensitivity is not None and card.robustness is not None
    assert card.sensitivity.bulk_exclusion.surge_rule.is_default
    assert not card.sensitivity.convenience_store.included.is_default
    assert card.sensitivity.convenience_store.included.n > card.data.n
    assert card.robustness.holds  # 효과를 넣어 만든 데이터
    # 기본 설정의 서울 기준율이 base_rate 행과 같다
    seoul = [
        item.rate
        for item in computation.rates
        if item.scope_code == "11" and item.floor_scale == "all"
    ]
    assert [rate.n for rate in seoul] == [bucket.n for bucket in card.base_rates]
    assert {item.scope_code for item in computation.rates} == {"11", "11215", "11440"}

    rows = variants(card)
    assert [axis for axis, _, _ in rows] == [
        "기본", "급증일", "급증일", "편의점", "신고 지연", "신고 지연", "층 미상",
    ]  # fmt: skip
    assert rows[0][2].is_default and not any(result.is_default for _, _, result in rows[1:])
    report = render(card, computation.method_version, saved=True)
    assert "| 기본 | (기본 설정) |" in report
    assert "4+ 버킷 폐업률이 설정마다 움직인 폭" in report
    assert "모든 설정에서 (a)(b)가 유지됐다" in report


def test_compute_reports_failure_when_there_is_no_effect() -> None:
    computation = compute(synthetic(seed=3, effect=0.0), AS_OF, SIGUNGU)
    robustness = computation.card.robustness
    assert robustness is not None and not robustness.holds
    assert robustness.failures
    report = render(computation.card, computation.method_version, saved=False)
    assert "`base_rate`·`model_card`를 쓰지 않았다" in report


def crowded(seed: int, effect: float, floors: int) -> pd.DataFrame:
    """`synthetic`과 같되, 층마다 2000년부터 영업 중인 가게 두 곳이 함께 있다 (소형 복수)."""
    records = synthetic(seed, effect, floors)
    records["pnu"] = "9" + records["pnu"].str[1:]  # 다른 필지(가상)
    anchors = records.drop_duplicates(["pnu", "floor"]).assign(
        status="open", opened_on=date(2000, 1, 1), closed_on=None
    )
    both = pd.concat([records, anchors, anchors], ignore_index=True)
    both["id"] = range(1_000_000, 1_000_000 + len(both))
    return both


@pytest.fixture(scope="module")
def mixed(strong: pd.DataFrame) -> pd.DataFrame:
    """단독 층에는 효과가 있고, 소형 복수 층에는 효과가 없는 데이터."""
    return pd.concat([strong, crowded(seed=5, effect=0.0, floors=1500)], ignore_index=True)


def test_floor_scale_results_and_judgement(mixed: pd.DataFrame) -> None:
    computation = compute(mixed, AS_OF, SIGUNGU)
    card = ModelCardPayload.model_validate(computation.card.model_dump(mode="json", by_alias=True))
    scales = card.by_floor_scale
    assert scales is not None
    # 규모별 n의 합 = 코호트
    assert scales.single.n + scales.small.n + scales.large.n == card.data.n
    assert scales.single.n > 0 and scales.small.n > 0 and scales.large.n == 0
    # 단독: 효과가 있어 (a)(b) 유지
    assert scales.single.criterion_a and scales.single.criterion_b and scales.single.holds
    assert scales.single.logit is not None and scales.single.logit.ci[0] > 1
    assert [bucket.bucket for bucket in scales.single.buckets] == ["0", "1", "2", "3", "4+"]
    for bucket in scales.single.buckets:
        assert bucket.ci[0] <= bucket.rate <= bucket.ci[1]
    # 소형 복수: 효과가 없어 깨진다. 대형: 기록이 없어 (a)(b) 모두 거짓
    assert not scales.small.criterion_b and not scales.small.holds
    assert not scales.large.holds and scales.large.buckets == []


def test_broken_scale_is_not_written_to_base_rates(mixed: pd.DataFrame) -> None:
    computation = compute(mixed, AS_OF, SIGUNGU)
    # 깨진 규모(소형 복수·대형)의 기준율 행은 없다 → 화면 카드가 쓸 값이 없다
    assert {item.floor_scale for item in computation.rates} == {"all", "single"}
    single = [
        item.rate
        for item in computation.rates
        if item.floor_scale == "single" and item.scope_code == "11"
    ]
    assert computation.card.by_floor_scale is not None
    assert [(rate.bucket, rate.n) for rate in single] == [
        (bucket.bucket, bucket.n) for bucket in computation.card.by_floor_scale.single.buckets
    ]
    # 깨진 규모의 값은 모형 카드에 그대로 있다
    assert computation.card.by_floor_scale.small.buckets

    report = render(computation.card, computation.method_version, saved=True)
    assert "깨진 규모가 있다" in report
    assert "이 규모의 자리에서는 차이가 확인되지 않았어요" in report
    failures = scale_failures(computation.card.by_floor_scale)
    assert any(line.startswith("소형 복수(2~9), (b): OR ") for line in failures)
    assert "대형(10+), (a): 0: 기록 없음, 4+: 기록 없음" in failures


def test_scale_failure_does_not_change_the_overall_judgement(strong: pd.DataFrame) -> None:
    computation = compute(strong, AS_OF, SIGUNGU)
    card = computation.card
    # 소형 복수·대형 기록이 없어 두 규모는 깨지지만, 7개 설정의 판정은 그대로 유지다
    assert card.robustness is not None and card.robustness.holds
    assert card.by_floor_scale is not None and not card.by_floor_scale.small.holds


def test_full_history_scale_lets_future_information_in(strong: pd.DataFrame) -> None:
    # 층마다 2025년에 가게 두 곳이 더 열린다: 코호트(2023-10-08까지 개업) 기록에게는 미래의 일
    late = strong.drop_duplicates(["pnu", "floor"]).assign(
        status="open", opened_on=date(2025, 1, 1), closed_on=None
    )
    records = pd.concat([strong, late, late], ignore_index=True)
    records["id"] = range(1, len(records) + 1)
    card = compute(records, AS_OF, SIGUNGU).card
    assert card.by_floor_scale is not None and card.by_floor_scale_full_history is not None
    assert card.by_floor_scale.single.n == card.data.n  # 개업일까지의 이력으로는 모두 단독
    assert card.by_floor_scale_full_history.single.n == 0
    assert card.by_floor_scale_full_history.small.n == card.data.n
    assert "비교: 전체 이력 기준 층 규모" in render(card, "2026.10.1", saved=True)


def test_license_type_results_are_outside_the_judgement(strong: pd.DataFrame) -> None:
    records = strong.copy()
    # 휴게음식점에는 효과가 없는 기록을 넣는다
    flat = synthetic(seed=3, effect=0.0, floors=400).assign(license_type="rest_restaurant")
    flat["pnu"] = "8" + flat["pnu"].str[1:]
    records = pd.concat([records, flat], ignore_index=True)
    records["id"] = range(1, len(records) + 1)
    card = compute(records, AS_OF, SIGUNGU).card
    assert card.sensitivity is not None and card.robustness is not None
    kinds = card.sensitivity.license_type
    assert kinds.general_restaurant.n + kinds.rest_restaurant.n + kinds.bakery.n == card.data.n
    assert kinds.general_restaurant.criterion_a and kinds.general_restaurant.criterion_b
    assert not kinds.rest_restaurant.criterion_b and kinds.bakery.n == 0
    # 종류별로 깨져도 판정의 실패 목록에는 들어가지 않는다
    assert all(failure.axis != "license_type" for failure in card.robustness.failures)
    report = render(card, "2026.10.1", saved=True)
    assert "참고: 인허가 종류별 (판정에 넣지 않는다)" in report and "| 휴게음식점 |" in report


def test_four_plus_by_floor_record_count(strong: pd.DataFrame) -> None:
    card = compute(strong, AS_OF, SIGUNGU).card
    assert card.floor_record_count is not None
    rows = card.floor_record_count.four_plus
    four_plus = next(bucket for bucket in card.base_rates if bucket.bucket == "4+")
    assert sum(row.n for row in rows) == four_plus.n
    assert sum(row.events for row in rows) == four_plus.events
    assert {row.range for row in rows} <= {"1-10", "11-20", "21-50", "51+"}
    assert "4+ 버킷을 층의 기록 수로 나누면" in render(card, "2026.10.1", saved=True)


def test_record_count_ranges() -> None:
    counts = pd.Series([1, 10, 11, 20, 21, 50, 51, 400])
    assert list(record_count_range(counts)) == [
        "1-10", "1-10", "11-20", "11-20", "21-50", "21-50", "51+", "51+",
    ]  # fmt: skip
