"""층 이력 요약과 과거 폐업 횟수 계산 (docs/10 §7.1·§7.2). 순수 계산만 한다.

입력 `records`의 열: `id, pnu, floor, status, opened_on, closed_on, bulk_closure,
no_fixed_place, suppressed, road_addr, geom_ewkt` (`pnu`가 있는 기록).
"""

from datetime import date
from typing import Any

import numpy as np
import numpy.typing as npt
import pandas as pd

from app.location.normalize.floor_parser import floor_sort_key

METHOD_VERSION = "2026.10.1"
SINCE = date(2005, 1, 1)
CONCURRENT_MIN_DAYS = 30  # 이 일수를 넘게 겹치면 동시 영업으로 본다
_EPOCH = pd.Timestamp("1900-01-01")
_BIG = 1_000_000  # 층키 번호와 날짜를 한 정수로 묶는 자릿수 (날짜는 1900-01-01부터의 일수)

PRIOR, PRIOR_EX_SURGE = "prior_closures_floor", "prior_closures_floor_ex_surge"


def _days(values: "pd.Series[Any]") -> "pd.Series[float]":
    """날짜 → 1900-01-01부터의 일수. 없으면 NaN."""
    return (pd.to_datetime(values, errors="coerce") - _EPOCH).dt.days.astype("float64")


def visible(records: pd.DataFrame) -> pd.DataFrame:
    """이력에 보이는 기록 `H`: 고정된 자리가 있고 숨김 처리되지 않은 기록."""
    keep = ~records["no_fixed_place"].astype(bool) & ~records["suppressed"].astype(bool)
    return records[keep]


def statistical(records: pd.DataFrame) -> pd.DataFrame:
    """통계의 층키 기록 집합 `F`: 층이 있고 고정된 자리가 있는 기록 (숨김 기록 포함)."""
    return records[records["floor"].notna() & ~records["no_fixed_place"].astype(bool)]


def prior_closures(
    floor_records: pd.DataFrame, not_counted: "pd.Series[bool] | None" = None
) -> "pd.Series[Any]":
    """기록마다 같은 층키에서 개업일 전에 폐업한 다른 기록 수 (개업일이 없는 기록은 내지 않는다).

    `not_counted`가 참인 폐업은 세지 않는다 (예: 급증일 폐업). 같은 날 폐업·개업은 세지 않는다.
    층키별 정렬 + 이진 탐색 (`analysis/w0_location_signal.py`의 `prior_closures`와 같은 방식).
    """
    code = floor_records.groupby(["pnu", "floor"], sort=False).ngroup().to_numpy(dtype=np.int64)
    opened = _days(floor_records["opened_on"]).to_numpy()
    closed = _days(floor_records["closed_on"]).to_numpy()
    counted = (floor_records["status"] == "closed").to_numpy() & ~np.isnan(closed)
    if not_counted is not None:
        counted &= ~not_counted.to_numpy(dtype=bool)
    ends = np.sort(code[counted] * _BIG + closed[counted].astype(np.int64))

    has_opened = ~np.isnan(opened)
    start = code[has_opened] * _BIG
    query = start + opened[has_opened].astype(np.int64)
    count = np.searchsorted(ends, query, "left") - np.searchsorted(ends, start, "left")
    return pd.Series(count.astype(np.int64), index=floor_records.index[has_opened])


def build_record_prior(records: pd.DataFrame) -> pd.DataFrame:
    """`record_prior` 행: `record_id`, 급증일 폐업을 포함한 값과 뺀 값."""
    floor_records = statistical(records)
    with_surge = prior_closures(floor_records)
    without_surge = prior_closures(floor_records, floor_records["bulk_closure"].astype(bool))
    return pd.DataFrame(
        {
            "record_id": floor_records.loc[with_surge.index, "id"].to_numpy(),
            PRIOR: with_surge.to_numpy(),
            PRIOR_EX_SURGE: without_surge.to_numpy(),
        }
    )


def _has_concurrent(floor_records: pd.DataFrame, as_of: date) -> "pd.Series[bool]":
    """층키마다: 영업 기간이 `CONCURRENT_MIN_DAYS`일 넘게 겹치는 쌍이 있는가."""
    start = _days(floor_records["opened_on"])
    end = _days(floor_records["closed_on"])
    as_of_days = float((pd.Timestamp(as_of) - _EPOCH).days)
    end = end.where(floor_records["status"] != "open", as_of_days)
    known = start.notna() & end.notna()  # 기간을 모르는 기록은 판정에서 뺀다
    spans = pd.DataFrame(
        {"pnu": floor_records["pnu"], "floor": floor_records["floor"], "start": start, "end": end}
    )[known].sort_values(["pnu", "floor", "start"], kind="stable")
    grouped = spans.groupby(["pnu", "floor"], sort=False)["end"]
    # 먼저 시작한 기록들의 끝 중 가장 늦은 값. 그 값과 자기 끝 중 이른 쪽이 겹침의 끝이다
    latest_earlier_end = (
        grouped.cummax().groupby([spans["pnu"], spans["floor"]], sort=False).shift()
    )
    overlap = np.minimum(spans["end"], latest_earlier_end) - spans["start"]
    crowded: pd.Series[bool] = (
        (overlap > CONCURRENT_MIN_DAYS).groupby([spans["pnu"], spans["floor"]]).any()
    )
    return crowded


def _round_half_up(values: "pd.Series[float]") -> npt.NDArray[np.float64]:
    return np.floor(values.to_numpy(dtype=np.float64) + 0.5)


def build_floor_summary(records: pd.DataFrame, as_of: date) -> pd.DataFrame:
    """`floor_summary` 행. 이력에 보이는 기록 중 층이 있는 것으로 만든다."""
    floor_records = visible(records)
    floor_records = floor_records[floor_records["floor"].notna()]
    keys = [floor_records["pnu"], floor_records["floor"]]
    opened = pd.to_datetime(floor_records["opened_on"], errors="coerce")
    closed = pd.to_datetime(floor_records["closed_on"], errors="coerce")
    is_closed = floor_records["status"] == "closed"
    tenure = (closed - opened).dt.days.where(
        is_closed & ~floor_records["bulk_closure"].astype(bool)
    )
    summary = pd.DataFrame(
        {
            "record_count": floor_records["id"].groupby(keys).size(),
            "records_since_2005": (opened >= pd.Timestamp(SINCE)).groupby(keys).sum(),
            "open_now_count": (floor_records["status"] == "open").groupby(keys).sum(),
            "median_closed_tenure_days": tenure.groupby(keys).median(),
        }
    )
    summary["median_closed_tenure_days"] = _round_half_up(summary["median_closed_tenure_days"])
    concurrent = _has_concurrent(floor_records, as_of)
    summary["has_concurrent"] = concurrent.reindex(summary.index, fill_value=False)
    summary["method_version"] = METHOD_VERSION
    return summary.rename_axis(["pnu", "floor"]).reset_index()


def jibun_label(pnu: str, dong_name: str) -> str:
    """PNU와 법정동 이름 → `'서울특별시 광진구 화양동 47-1'`."""
    main, sub = int(pnu[11:15]), int(pnu[15:19])
    number = f"{main}-{sub}" if sub else str(main)
    return f"{dong_name} {'산 ' if pnu[10] == '2' else ''}{number}"


def _latest(history: pd.DataFrame, column: str) -> "pd.Series[str]":
    """필지마다 `column` 값이 있는 기록 중 가장 최근에 개업한 기록의 값."""
    having = history[history[column].notna()]
    ordered = having.assign(
        _opened=pd.to_datetime(having["opened_on"], errors="coerce")
    ).sort_values(["_opened", "id"], na_position="first", kind="stable")
    return ordered.groupby("pnu")[column].last()


def build_parcels(records: pd.DataFrame, dong_names: dict[str, str]) -> pd.DataFrame:
    """`parcel` 행 (`geom`은 EWKT 문자열 `geom_ewkt`)."""
    history = visible(records)
    parcels = pd.DataFrame({"record_count": history.groupby("pnu").size()})
    floors = history[history["floor"].notna()].groupby("pnu")["floor"].unique()
    parcels["floors"] = [
        sorted(floors[pnu], key=floor_sort_key) if pnu in floors.index else []
        for pnu in parcels.index
    ]
    road = _latest(history, "road_addr").map(lambda value: value.partition(",")[0].strip())
    parcels["road_addr"] = road.reindex(parcels.index).astype(object)
    parcels["geom_ewkt"] = _latest(history, "geom_ewkt").reindex(parcels.index).astype(object)
    parcels = parcels.rename_axis("pnu").reset_index()
    parcels["legal_dong_code"] = parcels["pnu"].str[:10]
    unknown = sorted(set(parcels["legal_dong_code"]) - set(dong_names))
    if unknown:
        raise ValueError(f"legal_dong에 없는 법정동코드: {', '.join(unknown[:5])}")
    parcels["jibun_label"] = [
        jibun_label(pnu, dong_names[code])
        for pnu, code in zip(parcels["pnu"], parcels["legal_dong_code"], strict=True)
    ]
    parcels = parcels.astype(object).where(parcels.notna(), None)
    return parcels[
        [
            "pnu",
            "legal_dong_code",
            "jibun_label",
            "road_addr",
            "geom_ewkt",
            "floors",
            "record_count",
        ]
    ]
