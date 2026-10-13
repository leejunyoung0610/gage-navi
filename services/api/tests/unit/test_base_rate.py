"""기준율: Wilson 구간, 설정별 코호트, 버킷, 판정 (a) (docs/10 §7.2·§7.3).

필지·업소·날짜·건수는 모두 가상 예시다.
"""

from datetime import date
from decimal import Decimal

import pandas as pd
import pytest

from app.location.stats.base_rate import (
    BucketRate,
    Setting,
    bucket_rates,
    build_cohort,
    censored_rates,
    cohort_to,
    separated,
    surge_flags,
    wilson_ci,
)

AS_OF = date(2026, 10, 7)
LAST = cohort_to(AS_OF)
P1 = "1121510700100470001"  # 가상
P2 = "1121510700100480000"  # 가상


def record(
    number: int,
    opened: str | None,
    closed: str | None = None,
    *,
    pnu: str | None = P1,
    floor: str | None = "1",
    kind: str = "general_restaurant",
    category: str | None = "한식",
    bulk: bool = False,
    stale: bool = False,
    stale_area: bool = False,
    mobile: bool = False,
    area: str | None = "33.00",
) -> dict[str, object]:
    return {
        "id": number,
        "license_type": kind,
        "pnu": pnu,
        "floor": floor,
        "status": "closed" if closed else "open",
        "opened_on": None if opened is None else date.fromisoformat(opened),
        "closed_on": None if closed is None else date.fromisoformat(closed),
        "bulk_closure": bulk,
        "stale_suspect": stale,
        "stale_area_match": stale_area,
        "no_fixed_place": mobile,
        "biz_category": category,
        "area_m2": None if area is None else Decimal(area),
        "sigungu_code": None if pnu is None else pnu[:5],
        "suppressed": False,
    }


def cohort(rows: list[dict[str, object]], setting: Setting | None = None, **options: bool):
    return build_cohort(pd.DataFrame(rows), setting or Setting(), LAST, **options).set_index("id")


def test_wilson_known_value() -> None:
    low, high = wilson_ci(50, 100)
    assert (round(low, 3), round(high, 3)) == (Decimal("0.404"), Decimal("0.596"))


def test_wilson_edges() -> None:
    low, high = wilson_ci(0, 10)
    assert low == 0 and Decimal("0.27") < high < Decimal("0.28")
    with pytest.raises(ValueError):
        wilson_ci(1, 0)
    with pytest.raises(ValueError):
        wilson_ci(11, 10)


def test_cohort_to_is_1095_days_before_as_of() -> None:
    assert LAST == date(2023, 10, 8)


# 한 층: 평범한 폐업 2건, 급증일 폐업 1건, 그 뒤에 연 가게들
FLOOR = [
    record(1, "2006-01-01", "2008-01-01"),  # 2년 만에 폐업 → 사건
    record(2, "2008-01-01", "2012-06-30"),  # 1의 폐업일에 개업 → 같은 날은 세지 않는다
    record(3, "2009-01-01", "2012-12-31", bulk=True),  # 급증일 폐업
    record(4, "2013-01-01", "2016-12-31"),  # 1,461일 → 사건 아님
    record(5, "2020-01-01"),  # 영업 중
    record(6, "2024-01-01"),  # 3년을 지켜볼 수 없다 → 코호트 밖
    record(7, "2004-12-31", "2005-06-30"),  # 2005년 전 개업 → 코호트 밖, 과거 폐업에는 센다
]


def test_default_cohort_excludes_surge_closures_from_cohort_and_prior() -> None:
    result = cohort(FLOOR)
    assert list(result.index) == [1, 2, 4, 5]
    assert result["prior"].to_dict() == {1: 1, 2: 1, 4: 3, 5: 4}
    assert result["event"].to_dict() == {1: True, 2: False, 4: False, 5: False}


def test_no_exclusion_keeps_surge_closure_in_cohort_and_prior() -> None:
    result = cohort(FLOOR, Setting(bulk_exclusion="none"))
    assert list(result.index) == [1, 2, 3, 4, 5]
    assert result["prior"].to_dict() == {1: 1, 2: 1, 3: 2, 4: 4, 5: 5}


def test_cohort_boundaries_are_inclusive() -> None:
    result = cohort(
        [
            record(1, "2005-01-01"),
            record(2, LAST.isoformat()),
            record(3, "2023-10-09"),
            record(4, None),
        ]
    )
    assert list(result.index) == [1, 2]


def test_event_is_closure_within_1095_days() -> None:
    result = cohort(
        [
            record(1, "2010-01-01", "2012-12-31", pnu=P2),  # 1,095일
            record(2, "2010-01-01", "2013-01-01", pnu=P2),  # 1,096일
        ]
    )
    assert result["event"].to_dict() == {1: True, 2: False}


def test_records_without_floor_or_fixed_place_are_not_in_cohort_or_prior() -> None:
    result = cohort(
        [
            record(1, "2006-01-01", "2007-01-01", floor=None),
            record(2, "2006-01-01", "2007-01-01", mobile=True),
            record(3, "2006-01-01", "2007-01-01", pnu=None),
            record(4, "2010-01-01"),
        ]
    )
    assert list(result.index) == [4]
    assert result.at[4, "prior"] == 0
    # 같은 필지의 층 미상 폐업은 다른 층 통제 변수에는 들어간다 (고정된 자리 없는 기록은 빠진다)
    assert result.at[4, "other_floor"] == 1


def test_convenience_store_is_excluded_from_cohort_only() -> None:
    rows = [
        record(1, "2006-01-01", "2007-01-01", category="편의점"),
        record(2, "2010-01-01"),
    ]
    assert cohort(rows)["prior"].to_dict() == {2: 1}
    included = cohort(rows, Setting(convenience_store="included"))
    assert list(included.index) == [1, 2]


def test_stale_exclusion_by_ground() -> None:
    rows = [
        record(1, "2010-01-01", stale=True),
        record(2, "2011-01-01", stale_area=True),
        record(3, "2012-01-01"),
    ]
    assert list(cohort(rows).index) == [1, 2, 3]
    assert list(cohort(rows, Setting(exclude_stale="same_ho")).index) == [2, 3]
    assert list(cohort(rows, Setting(exclude_stale="same_ho_or_area")).index) == [3]


def test_floor_unknown_excludes_parcels_with_floorless_closure() -> None:
    rows = [
        record(1, "1999-01-01", "2001-01-01", floor=None),  # 층 미상 폐업
        record(2, "2010-01-01"),
        record(3, "2010-01-01", pnu=P2),
        record(4, "2001-01-01", floor=None, pnu=P2),  # 층 미상이지만 영업 중
        record(5, "1999-01-01", "2001-01-01", floor=None, pnu=P2, mobile=True),
    ]
    setting = Setting(floor_unknown="exclude_parcels_with_floorless_closure")
    assert list(cohort(rows).index) == [2, 3]
    assert list(cohort(rows, setting).index) == [3]


def test_w0_definition_flags_general_restaurant_closures_on_citywide_100_days() -> None:
    busy, quiet = "2015-12-31", "2015-12-30"
    rows = [record(n, "2010-01-01", busy, pnu=None, floor=None) for n in range(100)]
    # 조용한 날은 아래 301번까지 99건이다
    rows += [record(100 + n, "2010-01-01", quiet, pnu=None, floor=None) for n in range(98)]
    rows += [
        record(300, "2010-01-01", busy, kind="rest_restaurant"),  # 일반음식점이 아니다
        record(301, "2010-01-01", quiet),
        record(302, "2016-06-01", pnu=P1),
    ]
    frame = pd.DataFrame(rows)
    flags = surge_flags(frame, "w0_citywide_100")
    assert int(flags.sum()) == 100
    assert not flags[frame["id"] >= 100].any()
    assert not surge_flags(frame, "none").any()

    # 급증일로 본 폐업은 코호트에서 빠지고 과거 폐업 횟수에도 세지 않는다
    rows.append(record(303, "2010-01-01", busy))
    result = cohort(rows, Setting(bulk_exclusion="w0_citywide_100"))
    assert 303 not in result.index
    assert result.at[302, "prior"] == 2  # 300, 301


def test_w0_mode_counts_surge_closures_in_prior_and_requires_area() -> None:
    rows = [
        record(1, "2006-01-01", "2008-01-01", bulk=True),
        record(2, "2010-01-01"),
        record(3, "2010-01-01", area=None),
        record(4, "2010-01-01", area="0"),
    ]
    result = cohort(rows, Setting(), w0=True)
    assert list(result.index) == [2]
    assert result.at[2, "prior"] == 1


def test_bucket_rates_and_caps_at_four_plus() -> None:
    frame = pd.DataFrame(
        {"prior": [0, 0, 0, 0, 1, 4, 9], "event": [True, False, False, False, True, True, False]}
    )
    rates = {rate.bucket: rate for rate in bucket_rates(frame)}
    assert set(rates) == {"0", "1", "4+"}
    assert (rates["0"].n, rates["0"].events, rates["0"].rate) == (4, 1, Decimal("0.25"))
    assert (rates["4+"].n, rates["4+"].events) == (2, 1)
    assert rates["0"].ci_low < rates["0"].rate < rates["0"].ci_high


def rate(bucket: str, events: int, n: int) -> BucketRate:
    low, high = wilson_ci(events, n)
    return BucketRate(bucket, n, events, Decimal(events) / n, low, high)


def test_criterion_a_requires_non_overlapping_intervals() -> None:
    assert separated([rate("0", 300, 1000), rate("4+", 450, 1000)])
    # 비율은 높지만 구간이 겹친다
    assert not separated([rate("0", 300, 1000), rate("4+", 33, 100)])
    # 겹치지 않지만 방향이 반대다
    assert not separated([rate("0", 450, 1000), rate("4+", 300, 1000)])
    # 버킷이 없으면 유지되지 않은 것으로 본다
    assert not separated([rate("0", 300, 1000)])


def test_censored_rates_without_surge_equal_plain_rates() -> None:
    result = cohort(FLOOR, Setting(bulk_exclusion="none"))
    result["surge"] = False
    plain = {rate.bucket: float(rate.rate) for rate in bucket_rates(result)}
    for item in censored_rates(result):
        assert item.rate == pytest.approx(plain[item.bucket])
        assert item.censored == 0


def test_censored_rates_treat_surge_closure_as_censoring() -> None:
    # 4건: 100일에 폐업(사건), 200일에 급증일 폐업(중도절단), 300일에 폐업(사건), 영업 중
    frame = pd.DataFrame(
        {
            "prior": [0, 0, 0, 0],
            "tenure_days": [100.0, 200.0, 300.0, float("nan")],
            "surge": [False, True, False, False],
        }
    )
    (item,) = censored_rates(frame)
    # 생존: (1 − 1/4) × (1 − 1/2) = 0.375
    assert (item.n, item.censored) == (4, 1)
    assert item.rate == pytest.approx(0.625)
    assert 0 <= item.ci_low < item.rate < item.ci_high <= 1
