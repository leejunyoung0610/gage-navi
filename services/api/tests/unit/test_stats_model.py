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
from app.location.stats.model import auc, fit_logit, model_frame, out_of_time
from app.location.stats.report import render, variants

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
        "sensitivity", "robustness",
    }  # fmt: skip
    assert set(payload["sensitivity"]) == {
        "bulk_exclusion", "convenience_store", "exclude_stale", "floor_unknown", "bulk_as_censored",
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
    seoul = [item.rate for item in computation.rates if item.scope_code == "11"]
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
