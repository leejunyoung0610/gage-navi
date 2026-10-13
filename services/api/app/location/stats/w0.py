"""W0 재현 모드의 입력 준비 (docs/10 §7.4). `analysis/w0_location_signal.py`의 규칙을 그대로 옮겼다.

이 모드의 로직은 "개선"하지 않는다 — 층 파서·층키가 §3의 규칙과 다르다.
입력 `records`의 열: `id, status, opened_on, closed_on, area_m2, biz_category, jibun_addr,
road_addr` (일반음식점). 결과는 `base_rate.build_cohort`가 받는 열을 가진다.
"""

import re
from datetime import date

import pandas as pd

from app.location.stats.base_rate import Setting

METHOD_VERSION = "w0"
LICENSE_GROUP = "general_restaurant"
AS_OF = date(2026, 10, 8)
LAST_OPENED = date(2023, 10, 8)
SETTING = Setting(bulk_exclusion="w0_citywide_100", convenience_store="included")

_JIBUN = r"서울특별시\s+(\S+구)\s+(\S+)\s+(산\s*)?(\d+)(?:-(\d+))?(.*)$"
_FLOOR = [
    (r"지하\s*(\d+)\s*층", "B"),
    (r"(지하층|지층)", "B1"),
    (r"\bB\s*(\d+)\b", "B"),
    (r"(?:지상\s*|제\s*)?(\d+)\s*층", ""),
    (r"(\d+)\s*F\b", ""),
]


def prepare(records: pd.DataFrame) -> pd.DataFrame:
    """W0 문자열 층키(`pnu` 자리에 건물 키, `floor`에 W0 층)를 붙인 기록."""
    jibun = records["jibun_addr"].fillna("").str.strip().str.extract(_JIBUN)
    jibun.columns = pd.Index(["gu", "dong", "san", "main", "sub", "tail"])
    sub = jibun["sub"].where(jibun["sub"].notna() & (jibun["sub"] != "0"), "")
    sub = sub.where(sub == "", "-" + sub)
    building = (
        jibun["gu"] + " " + jibun["dong"] + " " + jibun["san"].notna().map({True: "산", False: ""})
    ) + (jibun["main"] + sub)
    road = records["road_addr"].fillna("").str.strip()
    detail = jibun["tail"].fillna("") + " " + road.str.split(",", n=1).str[1].fillna("")

    floor = pd.Series(None, index=records.index, dtype=object)
    for pattern, prefix in _FLOOR:
        found = detail.str.extract(pattern, flags=re.IGNORECASE)[0]
        value = found.where(found.isna(), "B1") if prefix == "B1" else prefix + found
        floor = floor.fillna(value)

    return pd.DataFrame(
        {
            "id": records["id"],
            "license_type": LICENSE_GROUP,
            "pnu": building.where(jibun["main"].notna()),
            "floor": floor,
            "status": records["status"],
            "opened_on": records["opened_on"],
            "closed_on": records["closed_on"],
            "bulk_closure": False,
            "stale_suspect": False,
            "stale_area_match": False,
            "no_fixed_place": False,
            "biz_category": records["biz_category"],
            "area_m2": records["area_m2"],
            "sigungu_code": jibun["gu"],
        }
    )
