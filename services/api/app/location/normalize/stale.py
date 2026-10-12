"""미갱신 의심 탐지 (docs/10 §6, ADR-023).

영업 중으로 남은 기록 A와, 같은 층키에서 A보다 나중에 개업한 다른 기록 B의 쌍을 본다.
같은 가게로 보이는 쌍(사업장명이 같거나 한쪽이 다른 쪽을 포함)은 빼고, 남은 쌍의 근거를
같은 호 / 같은 면적(±1%)으로 나눠 낸다. 영업 중 기록이 3건 이상인 호(공유 공간 추정)는
같은 호 근거로 세지 않는다 — 틀린 배지보다 놓친 배지가 낫다. 순수 계산만 한다.
"""

import re
from collections import Counter
from dataclasses import dataclass
from typing import Any

import numpy as np
import numpy.typing as npt
import pandas as pd

AREA_TOLERANCE_PERCENT = 1
SHARED_HO_MIN_OPEN = 3  # 한 층키의 같은 호에 영업 중 기록이 이만큼 이상이면 공유 공간으로 본다
_NAME_MIN = 2  # 포함 관계를 볼 때 두 이름의 최소 길이

_CORPORATE = re.compile(r"\(주\)|㈜|주식회사")
_NOT_WORD = re.compile(r"[\W_]+")

# 입력 열
ID, NAME, STATUS, OPENED_ON, AREA, PNU, FLOOR, HO_LIST, NO_FIXED_PLACE = (
    "id",
    "name",
    "status",
    "opened_on",
    "area_m2",
    "pnu",
    "floor",
    "ho_list",
    "no_fixed_place",
)
SAME_HO, SAME_AREA = "same_ho", "same_area"
HO_OPEN_COUNT = "ho_open_count"


@dataclass(frozen=True)
class StaleResult:
    # 근거가 하나라도 있는 기록: `id`, `same_ho`, `same_area`, `ho_open_count`
    # (`ho_open_count`: 같은 호 근거가 된 호의 영업 중 기록 수 — 자신 포함, 근거가 없으면 0)
    flags: pd.DataFrame
    candidates: int  # 대상 A (영업 중, 층키·개업일 있음, 고정된 자리 있음)
    later_pairs: int  # A보다 나중에 개업한 B와의 쌍
    ho_pairs: int  # 같은 호 쌍 (같은 가게 쌍을 빼기 전)
    area_pairs: int
    ho_pairs_same_name: int  # 그중 같은 가게로 보아 뺀 쌍
    area_pairs_same_name: int
    ho_records_before: int  # 같은 가게 쌍을 빼기 전에 근거가 있던 기록
    area_records_before: int
    ho_records_shared_excluded: int  # 공유 공간 추정으로 같은 호 근거가 빠진 기록
    shared_hos: int  # 공유 공간으로 본 (층키, 호) 수


def normalize_name(name: str) -> str:
    """법인 표기·공백·문장부호를 떼고 영문을 소문자로."""
    return _NOT_WORD.sub("", _CORPORATE.sub("", name)).lower()


def same_business(name_a: str, name_b: str) -> bool:
    """정규화한 이름이 같거나 한쪽이 다른 쪽을 포함하면 같은 가게로 본다."""
    a, b = normalize_name(name_a), normalize_name(name_b)
    if not a or not b:
        return False
    if a == b:
        return True
    return min(len(a), len(b)) >= _NAME_MIN and (a in b or b in a)


def _area_x100(values: "pd.Series[Any]") -> npt.NDArray[np.int64]:
    """면적(소수 둘째 자리) × 100. 없으면 0 — 0 이하는 근거로 쓰지 않는다."""
    return np.array(
        [0 if value is None or value != value else int(value * 100) for value in values],
        dtype=np.int64,
    )


def detect_stale(records: pd.DataFrame) -> StaleResult:
    """`records`: `id, name, status, opened_on, area_m2, pnu, floor, ho_list, no_fixed_place`."""
    keyed = records[
        records[PNU].notna()
        & records[FLOOR].notna()
        & records[OPENED_ON].notna()
        & ~records[NO_FIXED_PLACE].astype(bool)
    ].copy()
    keyed["area"] = _area_x100(keyed[AREA])
    columns = [ID, NAME, OPENED_ON, "area", PNU, FLOOR, HO_LIST]
    open_now = keyed.loc[keyed[STATUS] == "open", columns]
    pairs = open_now.merge(keyed[columns], on=[PNU, FLOOR], suffixes=("_a", "_b"))
    pairs = pairs[pairs[f"{OPENED_ON}_b"] > pairs[f"{OPENED_ON}_a"]].reset_index(drop=True)

    area_a = pairs["area_a"].to_numpy(dtype=np.int64)
    area_b = pairs["area_b"].to_numpy(dtype=np.int64)
    gap = np.abs(area_a - area_b) * 100
    same_area = (
        (area_a > 0) & (area_b > 0) & (gap <= AREA_TOLERANCE_PERCENT * np.maximum(area_a, area_b))
    )
    # 층키의 호마다 영업 중 기록 수. 3건 이상이면 공유 공간으로 보고 그 호의 겹침은 세지 않는다
    open_rows = keyed[keyed[STATUS] == "open"]
    open_counts: Counter[tuple[str, str, str]] = Counter(
        (str(pnu), str(floor), str(ho))
        for pnu, floor, hos in zip(
            open_rows[PNU], open_rows[FLOOR], open_rows[HO_LIST], strict=True
        )
        for ho in set(hos)
    )
    same_ho_raw = np.zeros(len(pairs), dtype=bool)  # 호가 하나라도 겹침 (공유 공간 포함)
    same_ho = np.zeros(len(pairs), dtype=bool)
    ho_open = np.zeros(len(pairs), dtype=np.int64)
    rows = zip(pairs[PNU], pairs[FLOOR], pairs[f"{HO_LIST}_a"], pairs[f"{HO_LIST}_b"], strict=True)
    for position, (pnu, floor, ho_a, ho_b) in enumerate(rows):
        if not ho_a or not ho_b:
            continue
        overlap = set(ho_a).intersection(ho_b)
        if not overlap:
            continue
        same_ho_raw[position] = True
        counts = [open_counts.get((pnu, floor, ho), 0) for ho in overlap]
        private = [count for count in counts if count < SHARED_HO_MIN_OPEN]
        if private:
            same_ho[position] = True
            ho_open[position] = max(private)

    any_basis = same_ho_raw | same_area
    matched = pairs[any_basis].assign(
        **{
            SAME_HO: same_ho[any_basis],
            SAME_AREA: same_area[any_basis],
            "raw_ho": same_ho_raw[any_basis],
            HO_OPEN_COUNT: ho_open[any_basis],
        }
    )
    same_name = np.fromiter(
        (
            same_business(a, b)
            for a, b in zip(matched[f"{NAME}_a"], matched[f"{NAME}_b"], strict=True)
        ),
        dtype=bool,
        count=len(matched),
    )
    kept = matched[~same_name]
    grouped = kept.groupby(f"{ID}_a")
    flags = (
        grouped[[SAME_HO, SAME_AREA, "raw_ho"]]
        .any()
        .assign(**{HO_OPEN_COUNT: grouped[HO_OPEN_COUNT].max()})
        .reset_index()
        .rename(columns={f"{ID}_a": ID})
    )
    shared_excluded = int((flags["raw_ho"] & ~flags[SAME_HO]).sum())
    flags = flags[flags[SAME_HO] | flags[SAME_AREA]].drop(columns="raw_ho").reset_index(drop=True)
    return StaleResult(
        flags=flags,
        candidates=len(open_now),
        later_pairs=len(pairs),
        ho_pairs=int(matched["raw_ho"].sum()),
        area_pairs=int(matched[SAME_AREA].sum()),
        ho_pairs_same_name=int((matched["raw_ho"] & same_name).sum()),
        area_pairs_same_name=int((matched[SAME_AREA] & same_name).sum()),
        ho_records_before=int(matched.loc[matched["raw_ho"], f"{ID}_a"].nunique()),
        area_records_before=int(matched.loc[matched[SAME_AREA], f"{ID}_a"].nunique()),
        ho_records_shared_excluded=shared_excluded,
        shared_hos=sum(count >= SHARED_HO_MIN_OPEN for count in open_counts.values()),
    )
