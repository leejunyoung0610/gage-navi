"""W0 재현 모드의 층키·층 파서 (docs/10 §7.4). 주소는 모두 가상 예시다."""

from datetime import date

import pandas as pd

from app.location.stats import w0
from app.location.stats.card import compute_w0

CASES = [
    # (지번주소, 도로명주소, 건물 키, 층)
    ("서울특별시 광진구 화양동 47-1 지하1층", None, "광진구 화양동 47-1", "B1"),
    ("서울특별시 광진구 화양동 47-0 2층 201호", None, "광진구 화양동 47", "2"),
    ("서울특별시 광진구 화양동 산 21", "서울특별시 광진구 가상로 1, 3층", "광진구 화양동 산21", "3"),  # noqa: E501
    ("서울특별시 광진구 화양동 47 지층", None, "광진구 화양동 47", "B1"),
    ("서울특별시 광진구 화양동 47 B2", None, "광진구 화양동 47", "B2"),
    ("서울특별시 광진구 화양동 47", "서울특별시 광진구 가상로 1, 2F", "광진구 화양동 47", "2"),
    ("서울특별시 광진구 화양동 47", None, "광진구 화양동 47", None),
    ("경기도 가상시 가상동 1 1층", None, None, None),  # 지번을 못 읽으면 꼬리도 없다
    (None, "서울특별시 광진구 가상로 1, 1층", None, "1"),
]  # fmt: skip


def frame(rows: list[dict[str, object]]) -> pd.DataFrame:
    return pd.DataFrame(rows)


def test_prepare_builds_w0_key_and_floor() -> None:
    records = frame(
        [
            {
                "id": number,
                "status": "open",
                "opened_on": date(2010, 1, 1),
                "closed_on": None,
                "area_m2": 30,
                "biz_category": "한식",
                "jibun_addr": jibun,
                "road_addr": road,
            }
            for number, (jibun, road, _, _) in enumerate(CASES)
        ]
    )
    prepared = w0.prepare(records)
    for number, (_, _, key, floor) in enumerate(CASES):
        got_key, got_floor = prepared.at[number, "pnu"], prepared.at[number, "floor"]
        assert (None if pd.isna(got_key) else got_key) == key, CASES[number]
        assert (None if pd.isna(got_floor) else got_floor) == floor, CASES[number]
    assert prepared.at[0, "sigungu_code"] == "광진구"
    assert (prepared["license_type"] == "general_restaurant").all()


def test_compute_w0_uses_fixed_dates_and_no_sensitivity() -> None:
    address = "서울특별시 광진구 화양동 47-1 1층"
    records = frame(
        [
            {"id": 1, "status": "closed", "opened_on": date(2006, 1, 1),
             "closed_on": date(2007, 1, 1), "area_m2": 30, "biz_category": "한식",
             "jibun_addr": address, "road_addr": None},
            {"id": 2, "status": "open", "opened_on": date(2023, 10, 8), "closed_on": None,
             "area_m2": 30, "biz_category": "한식", "jibun_addr": address, "road_addr": None},
            {"id": 3, "status": "open", "opened_on": date(2023, 10, 9), "closed_on": None,
             "area_m2": 30, "biz_category": "한식", "jibun_addr": address, "road_addr": None},
        ]
    )  # fmt: skip
    computation = compute_w0(records)
    card = computation.card
    assert (computation.method_version, computation.license_group) == ("w0", "general_restaurant")
    assert (card.data.as_of, card.data.cohort_to) == (date(2026, 10, 8), date(2023, 10, 8))
    assert card.data.n == 2
    assert [(b.bucket, b.n, b.events) for b in card.base_rates] == [("0", 1, 1), ("1", 1, 0)]
    assert card.sensitivity is None and card.robustness is None and card.default_setting is None
    assert {item.scope_code for item in computation.rates} == {"11"}
