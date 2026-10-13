"""층 규모와 층 기록 수: 코호트 기록에 붙이는 값 (docs/10 §7.2·§7.3). 순수 계산만 한다.

입력 `records`는 `base_rate.build_cohort`가 받는 열에 `suppressed`를 더한 것.
"""

from datetime import date

import pandas as pd

from app.location.history.build import (
    max_concurrent,
    max_concurrent_at_open,
    scale_of,
    statistical,
    visible,
)

RECORD_COUNT_RANGES = (("1-10", 10), ("11-20", 20), ("21-50", 50), ("51+", None))


def _floor_records(records: pd.DataFrame) -> pd.DataFrame:
    """통계의 층키 기록 집합 `F`."""
    return statistical(records[records["pnu"].notna()])


def scale_at_open(records: pd.DataFrame, as_of: date) -> "pd.Series[str]":
    """기록마다: 개업일까지의 이력으로 센 층 규모 (통계의 기본)."""
    return scale_of(max_concurrent_at_open(_floor_records(records), as_of))


def scale_full_history(records: pd.DataFrame, as_of: date) -> "pd.Series[str]":
    """기록마다: 기준일까지의 전체 이력으로 센 층 규모 (비교용 — 개업일 뒤의 일이 들어간다)."""
    return scale_of(max_concurrent(_floor_records(records), as_of))


def floor_record_count(records: pd.DataFrame) -> "pd.Series[int]":
    """기록마다: 그 층키의 이력에 보이는 기록 수 (`floor_summary.record_count`와 같은 셈)."""
    floor_records = _floor_records(records)
    shown = visible(floor_records)
    counts = shown.groupby(["pnu", "floor"]).size().rename("count")
    joined = floor_records[["pnu", "floor"]].join(counts, on=["pnu", "floor"])
    return joined["count"].fillna(0).astype(int)


def record_count_range(count: "pd.Series[int]") -> "pd.Series[str]":
    labels = pd.Series(RECORD_COUNT_RANGES[-1][0], index=count.index, dtype=object)
    for label, upper in reversed(RECORD_COUNT_RANGES[:-1]):
        labels = labels.where(count > upper, label)
    return labels
