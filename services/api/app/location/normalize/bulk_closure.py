"""행정 일괄 폐업일 탐지 (docs/10 §5, ADR-020).

    c(j, d) = 관할 j, 날짜 d의 폐업 건수 (식품 3종 합산)
    m(j)    = 관할 j에서 폐업이 1건 이상 있었던 날들의 c(j, d) 중앙값
    bulk(j, d) = c(j, d) >= 30 AND c(j, d) >= 10 * m(j)

대상(`status='closed' AND closed_on IS NOT NULL`)을 고르는 일은 호출하는 쪽이 한다.
"""

import pandas as pd

MIN_COUNT = 30
MEDIAN_MULTIPLE = 10

JURISDICTION = "jurisdiction"
CLOSED_ON = "closed_on"
COUNT = "count"
MEDIAN = "median"


def is_bulk(count: int, median: float) -> bool:
    """`bulk(j, d)` 조건. `median`은 정수이거나 .5로 끝나므로 곱셈이 정확하다."""
    return count >= MIN_COUNT and count >= MEDIAN_MULTIPLE * median


def daily_counts(closures: pd.DataFrame) -> pd.DataFrame:
    """폐업 기록(`jurisdiction`, `closed_on`) → 관할·날짜별 `count`와 관할의 `median`.

    `closed_on`이 빈 행은 세지 않는다.
    """
    rows = closures.dropna(subset=[CLOSED_ON])
    counts = rows.groupby([JURISDICTION, CLOSED_ON], sort=True).size().rename(COUNT).reset_index()
    counts[MEDIAN] = counts.groupby(JURISDICTION)[COUNT].transform("median")
    return counts


def detect_bulk_days(
    closures: pd.DataFrame, min_count: int = MIN_COUNT, median_multiple: int = MEDIAN_MULTIPLE
) -> pd.DataFrame:
    """일괄 폐업일로 판정된 (`jurisdiction`, `closed_on`)과 그 `count`, `median`.

    임계값 인자는 민감도 측정용이다. 서비스 값은 기본값(문서 값)만 쓴다.
    """
    counts = daily_counts(closures)
    bulk = (counts[COUNT] >= min_count) & (counts[COUNT] >= median_multiple * counts[MEDIAN])
    return counts[bulk].reset_index(drop=True)


def flag_bulk_closure(closures: pd.DataFrame, bulk_days: pd.DataFrame) -> "pd.Series[bool]":
    """기록마다 `bulk_closure` 값. 해당 (관할, 날짜)의 기록 전체가 `True`."""
    keys = pd.MultiIndex.from_frame(bulk_days[[JURISDICTION, CLOSED_ON]])
    rows = pd.MultiIndex.from_frame(closures[[JURISDICTION, CLOSED_ON]])
    return pd.Series(rows.isin(keys), index=closures.index, name="bulk_closure")
