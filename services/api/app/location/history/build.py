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
MAX_AT_OPEN = "max_concurrent_at_open"
# 층 규모: 동시에 영업한 최대 점포 수가 이 값 이상이면 소형 복수 / 대형 (docs/10 §7.2)
SMALL_FROM, LARGE_FROM = 2, 10
SCALES = ("single", "small", "large")


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


def _spans(floor_records: pd.DataFrame, as_of: date) -> "tuple[pd.Series[float], pd.Series[float]]":
    """기록의 영업 기간 [시작, 끝] (일수). 영업 중이면 끝은 기준일, 모르면 NaN."""
    start = _days(floor_records["opened_on"])
    end = _days(floor_records["closed_on"])
    as_of_days = float((pd.Timestamp(as_of) - _EPOCH).days)
    return start, end.where(floor_records["status"] != "open", as_of_days)


def _concurrency(
    floor_records: pd.DataFrame, as_of: date
) -> tuple[npt.NDArray[np.int64], npt.NDArray[np.int64], npt.NDArray[np.int64]]:
    """층키별 동시 영업 점포 수의 변화: (기록의 층키 번호, 변화 시점 키, 그때까지의 최댓값).

    기간의 끝을 `CONCURRENT_MIN_DAYS + 1`일 당기면, 기록들이 함께 겹치는 길이가
    `CONCURRENT_MIN_DAYS`일을 넘는 것은 당긴 기간들이 같은 날을 품는 것과 같다. 그래서 날마다
    당긴 기간이 몇 개 걸쳐 있는지를 센다. 기간을 모르는 기록은 세지 않는다.
    """
    code: npt.NDArray[np.int64] = np.asarray(
        floor_records.groupby(["pnu", "floor"], sort=False).ngroup(), dtype=np.int64
    )
    start, end = _spans(floor_records, as_of)
    counted = (start.notna() & end.notna() & (end - start > CONCURRENT_MIN_DAYS)).to_numpy()
    base = code[counted] * _BIG
    enter = base + start.to_numpy()[counted].astype(np.int64)
    leave = base + end.to_numpy()[counted].astype(np.int64) - CONCURRENT_MIN_DAYS
    keys = np.concatenate([enter, leave])
    delta = np.concatenate([np.ones(len(enter), np.int64), -np.ones(len(leave), np.int64)])
    order = np.lexsort((delta, keys))  # 같은 날에는 나가는 쪽을 먼저 센다
    keys, delta = keys[order], delta[order]
    depth = np.cumsum(delta, dtype=np.int64)  # 층키마다 0으로 돌아오므로 전체 누적합으로 충분하다
    running: npt.NDArray[np.int64] = (
        pd.Series(depth).groupby(keys // _BIG, sort=False).cummax().to_numpy(dtype=np.int64)
    )
    return code, keys.astype(np.int64), running


def max_concurrent(floor_records: pd.DataFrame, as_of: date) -> "pd.Series[int]":
    """기록마다: 그 층에서 기준일까지 동시에 영업한 최대 점포 수 (최소 1, docs/10 §7.1)."""
    code, keys, running = _concurrency(floor_records, as_of)
    peak = pd.Series(running).groupby(keys // _BIG).max()
    values = pd.Series(code).map(peak).fillna(0).to_numpy(dtype=np.int64)
    return pd.Series(np.maximum(values, 1).astype(int), index=floor_records.index, dtype=int)


def max_concurrent_at_open(floor_records: pd.DataFrame, as_of: date) -> "pd.Series[int]":
    """기록마다: 개업일까지의 이력으로 센 동시 영업 최대 점포 수 (최소 1, docs/10 §7.2).

    개업일에서 기간을 자르면 개업일 `CONCURRENT_MIN_DAYS + 1`일 전까지의 최댓값과 같다.
    개업일이 없는 기록은 내지 않는다.
    """
    code, keys, running = _concurrency(floor_records, as_of)
    opened = _days(floor_records["opened_on"]).to_numpy()
    has_opened = ~np.isnan(opened)
    code = code[has_opened]
    query = code * _BIG + opened[has_opened].astype(np.int64) - (CONCURRENT_MIN_DAYS + 1)
    last = np.searchsorted(keys, query, "right") - 1
    values = np.zeros(len(query), dtype=np.int64)
    if len(keys):
        found = (last >= 0) & (keys[np.maximum(last, 0)] // _BIG == code)
        values[found] = running[last[found]]
    return pd.Series(
        np.maximum(values, 1).astype(int), index=floor_records.index[has_opened], dtype=int
    )


def scale_of(count: "pd.Series[int]") -> "pd.Series[str]":
    """동시에 영업한 최대 점포 수 → 층 규모 `single`(1) / `small`(2~9) / `large`(10 이상)."""
    scale = np.where(count >= LARGE_FROM, "large", np.where(count >= SMALL_FROM, "small", "single"))
    return pd.Series(scale, index=count.index, dtype=object)


def build_record_prior(records: pd.DataFrame, as_of: date) -> pd.DataFrame:
    """`record_prior` 행: `record_id`, 과거 폐업 횟수 두 값, 개업일까지의 동시 영업 최대 점포 수."""
    floor_records = statistical(records)
    with_surge = prior_closures(floor_records)
    without_surge = prior_closures(floor_records, floor_records["bulk_closure"].astype(bool))
    return pd.DataFrame(
        {
            "record_id": floor_records.loc[with_surge.index, "id"].to_numpy(),
            PRIOR: with_surge.to_numpy(),
            PRIOR_EX_SURGE: without_surge.to_numpy(),
            MAX_AT_OPEN: max_concurrent_at_open(floor_records, as_of)[with_surge.index].to_numpy(),
        }
    )


def _has_concurrent(floor_records: pd.DataFrame, as_of: date) -> "pd.Series[bool]":
    """층키마다: 영업 기간이 `CONCURRENT_MIN_DAYS`일 넘게 겹치는 쌍이 있는가."""
    start, end = _spans(floor_records, as_of)
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
    summary["max_concurrent"] = max_concurrent(floor_records, as_of).groupby(keys).first()
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
