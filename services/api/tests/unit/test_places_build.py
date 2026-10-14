"""장소 응답의 판단 부분 (T-022, docs/30 §2, docs/10 §7). 기록·기준율은 모두 가상 예시다."""

from dataclasses import replace
from datetime import date
from decimal import Decimal

import pytest

from app.location.places.build import (
    RateRow,
    Record,
    bucket_of,
    choose_rates,
    floor_scale,
    ho_groups,
    notices,
    scale_holds,
    tenure_days,
)

AS_OF = date(2026, 10, 7)
GU = "11215"
BASE = Record(
    record_id=1,
    name="가상업소",
    license_type="general_restaurant",
    biz_category="한식",
    opened_on=date(2011, 3, 2),
    closed_on=date(2013, 8, 30),
    status="closed",
    ho_list=(),
    bulk_closure=False,
    stale_suspect=False,
    floor="1",
    surge_label=None,
    surge_count=None,
)


def rate(scope: str, bucket: str, n: int) -> RateRow:
    return RateRow(scope, bucket, n, Decimal("0.4310"), Decimal("0.3920"), Decimal("0.4710"))


@pytest.mark.parametrize(
    ("changes", "expected"),
    [
        ({}, 912),
        ({"status": "open", "closed_on": None}, 5698),  # 영업 중: 기준일까지
        ({"status": "suspended", "closed_on": None}, 5698),
        ({"opened_on": None}, None),  # 개업일을 모르면 모른다
        ({"closed_on": None}, None),  # 폐업인데 폐업일이 없으면 기준일로 채우지 않는다
    ],
)
def test_tenure_days(changes: dict[str, object], expected: int | None) -> None:
    assert tenure_days(replace(BASE, **changes), AS_OF) == expected


@pytest.mark.parametrize(("count", "bucket"), [(0, "0"), (1, "1"), (3, "3"), (4, "4+"), (40, "4+")])
def test_bucket_of(count: int, bucket: str) -> None:
    assert bucket_of(count) == bucket


@pytest.mark.parametrize(
    ("count", "scale"), [(1, "single"), (2, "small"), (9, "small"), (10, "large"), (194, "large")]
)
def test_floor_scale_boundaries(count: int, scale: str) -> None:
    assert floor_scale(count) == scale


def test_scale_holds_only_when_true() -> None:
    card = {"single": {"holds": True}, "small": {"holds": "true"}, "large": {"holds": False}}
    assert scale_holds(card, "single") is True
    assert scale_holds(card, "small") is False  # 참(true)이 아닌 값은 유지로 보지 않는다
    assert scale_holds(card, "large") is False
    assert scale_holds({}, "single") is False
    assert scale_holds(None, "single") is False


def test_sigungu_is_primary_when_n_is_at_least_200() -> None:
    rows = [rate(GU, "2", 200), rate(GU, "0", 900), rate("11", "2", 9000), rate("11", "0", 9)]
    choice = choose_rates(rows, GU, "2", holds=True)
    assert choice.display
    assert choice.primary == rows[0] and choice.secondary == rows[2] and choice.baseline == rows[1]


def test_seoul_is_primary_when_sigungu_n_is_below_200() -> None:
    rows = [rate(GU, "2", 199), rate(GU, "0", 900), rate("11", "2", 9000), rate("11", "0", 9000)]
    choice = choose_rates(rows, GU, "2", holds=True)
    # 기준선도 주 값과 같은 범위(서울)에서 고른다
    assert choice.primary == rows[2] and choice.secondary is None and choice.baseline == rows[3]


def test_baseline_falls_back_to_seoul() -> None:
    rows = [rate(GU, "4+", 300), rate(GU, "0", 150), rate("11", "4+", 9000), rate("11", "0", 9000)]
    choice = choose_rates(rows, GU, "4+", holds=True)
    assert choice.primary == rows[0] and choice.baseline == rows[3]


def test_insufficient_sample_when_both_below_200() -> None:
    choice = choose_rates([rate(GU, "4+", 199), rate("11", "4+", 150)], GU, "4+", holds=True)
    assert not choice.display and choice.hidden_reason == "insufficient_sample"
    assert choice.primary is None and choice.baseline is None and choice.secondary is None
    assert choose_rates([], GU, "0", holds=True).hidden_reason == "insufficient_sample"


def test_broken_scale_is_hidden_even_with_rows() -> None:
    choice = choose_rates([rate("11", "0", 9000)], GU, "0", holds=False)
    assert not choice.display and choice.hidden_reason == "not_confirmed_for_floor_scale"
    assert choice.primary is None


def test_notices_follow_condition_table() -> None:
    bulk, stale = replace(BASE, bulk_closure=True), replace(BASE, stale_suspect=True)
    assert notices(False, [BASE], False) == []
    assert notices(True, [bulk, stale], True) == [
        "multiple_units_possible",
        "bulk_closure_present",
        "stale_suspect_present",
        "pre_2005_floor_missing",
    ]


def test_ho_groups_need_two_records() -> None:
    history = [
        replace(BASE, record_id=1, ho_list=("101", "101")),  # 한 기록 안의 중복은 한 번
        replace(BASE, record_id=2, ho_list=("102", "101")),
        replace(BASE, record_id=3, ho_list=("B1",)),
        replace(BASE, record_id=4, ho_list=("102",)),
    ]
    assert ho_groups(history) == [("101", [1, 2]), ("102", [2, 4])]
