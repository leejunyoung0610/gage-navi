"""인허가 원본 행 → `license_record` 정규화 (docs/03 D1, docs/10 §1.1~§5, docs/50 §2).

순수 계산만 한다. DB 읽기·쓰기는 `app.location.normalize.job`.
"""

import re
from dataclasses import dataclass, field
from datetime import date
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation

import numpy as np
import numpy.typing as npt
import pandas as pd

from app.address.pnu import SIDO, LegalDongIndex, parse_jibun
from app.location.ingest.license_file import JIBUN_ADDR, MGMT_NO, ROAD_ADDR, SOURCE_UPDATED_AT
from app.location.normalize.bulk_closure import (
    CLOSED_ON,
    COUNT,
    JURISDICTION,
    MEDIAN,
    detect_bulk_days,
    flag_bulk_closure,
)
from app.location.normalize.coords import to_wgs84_arrays
from app.location.normalize.floor_parser import parse_floor, road_detail
from app.location.normalize.ho_parser import parse_ho

PARSE_VERSION = "2026.10.1"

# 원문 컬럼명 (docs/03 D1 사용 컬럼)
JURISDICTION_COLUMN = "개방자치단체코드"
OPENED_ON_COLUMN = "인허가일자"
STATUS_COLUMN = "영업상태명"
CLOSED_ON_COLUMN = "폐업일자"
AREA_COLUMN = "소재지면적"
NAME_COLUMN = "사업장명"
CATEGORY_COLUMN = "업태구분명"
X_COLUMN = "좌표정보(X)"
Y_COLUMN = "좌표정보(Y)"
SOURCE_COLUMNS = (
    JURISDICTION_COLUMN,
    MGMT_NO,
    OPENED_ON_COLUMN,
    STATUS_COLUMN,
    CLOSED_ON_COLUMN,
    AREA_COLUMN,
    NAME_COLUMN,
    CATEGORY_COLUMN,
    JIBUN_ADDR,
    ROAD_ADDR,
    X_COLUMN,
    Y_COLUMN,
    SOURCE_UPDATED_AT,
)
LICENSE_TYPE = "license_type"
SNAPSHOT_ID = "snapshot_id"

# docs/03 D1 영업상태 매핑. 표에 없는 값은 DV5 실패
STATUS_MAP = {"영업/정상": "open", "폐업": "closed", "휴업": "suspended"}
# docs/10 §1.1 고정된 자리가 없는 업태
NO_FIXED_PLACE_CATEGORIES = frozenset({"푸드트럭", "이동조리"})

FLOOR_RATIO_FROM = date(2005, 1, 1)  # DV7: 2005년 이후 개업
# DV8 서울 경계 상자 (docs/50 §2). TODO(🔎 T-016): 경계 값은 확인 전 — 넉넉히 잡은 값
SEOUL_LAT = (37.40, 37.72)
SEOUL_LNG = (126.73, 127.27)
_AREA_MAX = Decimal("99999999.99")  # NUMERIC(10,2)
_SIGUNGU = re.compile(rf"^{SIDO}\s+(\S+구)")
_DATE = re.compile(r"\d{4}-\d{2}-\d{2}")

PNU_FAILURE_PREFIX = "pnu_"


@dataclass
class TypeStats:
    """인허가 종류 하나(스냅샷 하나)의 집계. DV 판정은 `validation` 모듈."""

    input_rows: int = 0
    duplicate_mgmt_no: int = 0
    non_seoul_excluded: int = 0
    seoul_rows: int = 0  # 서울 필터를 통과한 행 (PNU 실패율의 분모)
    opened_on_parsed: int = 0
    date_inversion: int = 0
    records: int = 0  # license_record에 들어가는 행
    status_counts: dict[str, int] = field(default_factory=dict)
    unknown_status: dict[str, int] = field(default_factory=dict)
    category_counts: dict[str, int] = field(default_factory=dict)
    pnu_failed: int = 0
    pnu_failures: dict[str, int] = field(default_factory=dict)
    pnu_abolished_only: int = 0
    since_2005: int = 0
    since_2005_with_floor: int = 0
    with_coords: int = 0
    coords_outside: int = 0
    closed: int = 0
    closed_without_date: int = 0
    no_fixed_place: int = 0
    floor_conflict: int = 0
    ho_conflict: int = 0
    surge_records: int = 0


@dataclass(frozen=True)
class Normalized:
    records: pd.DataFrame  # `RECORD_COLUMNS`
    surge_days: pd.DataFrame  # `SURGE_COLUMNS`
    stats: dict[str, TypeStats]  # license_type →
    surge_cells: int
    surge_dates: int


RECORD_COLUMNS = (
    "license_type",
    "mgmt_no",
    "jurisdiction_code",
    "name",
    "biz_category",
    "status",
    "status_raw",
    "opened_on",
    "closed_on",
    "area_m2",
    "jibun_addr",
    "road_addr",
    "pnu",
    "sigungu_code",
    "floor",
    "floor_source",
    "ho_list",
    "geom_ewkt",
    "bulk_closure",
    "no_fixed_place",
    "source_updated_at",
    "last_snapshot_id",
)
SURGE_COLUMNS = ("jurisdiction_code", "closed_on", "jurisdiction_label", "closure_count", "median")


def parse_date(value: str) -> date | None:
    """`YYYY-MM-DD` → 날짜. 비었거나 형식이 다르거나 없는 날짜면 `None`."""
    text = value.strip()
    if not _DATE.fullmatch(text):
        return None
    try:
        return date.fromisoformat(text)
    except ValueError:
        return None


def parse_area(value: str) -> Decimal | None:
    """`소재지면적` → ㎡ (소수 둘째 자리). 비었거나 숫자가 아니거나 음수·범위 밖이면 `None`."""
    try:
        area = Decimal(value.strip().replace(",", ""))
    except InvalidOperation:
        return None
    if not area.is_finite() or area < 0:
        return None
    area = area.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    return area if area <= _AREA_MAX else None


def _float(values: "pd.Series[str]") -> npt.NDArray[np.float64]:
    return np.asarray(pd.to_numeric(values.str.strip(), errors="coerce"), dtype=np.float64)


def _tally(stats: dict[str, TypeStats], flags: pd.DataFrame, kinds: "pd.Series[str]") -> None:
    """종류별로 `flags`의 참인 행 수를 세어 같은 이름의 `TypeStats` 필드에 넣는다."""
    for license_type, stat in stats.items():
        selected = flags[(kinds == license_type).to_numpy()]
        for column in flags.columns:
            setattr(stat, str(column), int(selected[column].sum()))


def _blank_to_none(values: "pd.Series[str]") -> "pd.Series[str]":
    stripped = values.str.strip()
    return stripped.where(stripped != "", None)


def _sigungu_label(frame: pd.DataFrame) -> "pd.Series[str]":
    """관할 코드 → 그 관할 기록의 주소에 가장 많이 나온 시군구 이름 (docs/10 §5)."""
    name = frame[JIBUN_ADDR].str.extract(_SIGUNGU)[0]
    name = name.fillna(frame[ROAD_ADDR].str.extract(_SIGUNGU)[0])
    counts = (
        pd.DataFrame({JURISDICTION: frame[JURISDICTION_COLUMN].str.strip(), "name": name})
        .dropna()
        .value_counts()
        .reset_index(name="n")
        .sort_values(["n", "name"], ascending=[False, True], kind="stable")
    )
    return counts.drop_duplicates(JURISDICTION).set_index(JURISDICTION)["name"]


def normalize(raw: pd.DataFrame, index: LegalDongIndex) -> Normalized:
    """`raw`: `SOURCE_COLUMNS` + `license_type` + `snapshot_id`, 값은 모두 원문 문자열."""
    stats = {str(kind): TypeStats() for kind in raw[LICENSE_TYPE].unique()}
    raw = raw.reset_index(drop=True)
    for license_type, stat in stats.items():
        group = raw[raw[LICENSE_TYPE] == license_type]
        stat.input_rows = len(group)
        stat.duplicate_mgmt_no = int(group[MGMT_NO].duplicated().sum())
        status_counts = group[STATUS_COLUMN].str.strip().value_counts()
        stat.status_counts = {str(k): int(v) for k, v in status_counts.to_dict().items()}
        stat.unknown_status = {k: v for k, v in stat.status_counts.items() if k not in STATUS_MAP}
        category_counts = group[CATEGORY_COLUMN].str.strip().value_counts()
        stat.category_counts = {str(k): int(v) for k, v in category_counts.to_dict().items()}

    # ---- 서울 밖 주소 행 제외 (docs/10 §1.1)
    seoul = raw[JIBUN_ADDR].str.startswith(SIDO) | raw[ROAD_ADDR].str.startswith(SIDO)
    _tally(stats, pd.DataFrame({"non_seoul_excluded": ~seoul}), raw[LICENSE_TYPE])
    frame = raw[seoul].reset_index(drop=True)
    kind = frame[LICENSE_TYPE]

    opened = frame[OPENED_ON_COLUMN].map(parse_date)
    closed_on = frame[CLOSED_ON_COLUMN].map(parse_date)
    status_raw = frame[STATUS_COLUMN].str.strip()
    status = status_raw.map(STATUS_MAP)
    category = frame[CATEGORY_COLUMN].str.strip()

    # ---- 주소 → PNU·층·호
    pnus: list[str | None] = []
    floors: list[str | None] = []
    floor_sources: list[str | None] = []
    hos: list[list[str]] = []
    pnu_failure: list[str | None] = []
    abolished_only: list[bool] = []
    floor_conflict: list[bool] = []
    ho_conflict: list[bool] = []
    for jibun, road in zip(frame[JIBUN_ADDR], frame[ROAD_ADDR], strict=True):
        parts = parse_jibun(jibun)
        failure: str | None = None
        pnu: str | None = None
        only_abolished = False
        if parts is None:
            failure = "regex_mismatch"
        else:
            found = index.lookup(parts.full_name)
            if found.code is None:
                failure = found.failure
            else:
                suffix = f"{'2' if parts.is_san else '1'}{parts.main:04d}{parts.sub:04d}"
                pnu = found.code + suffix
                only_abolished = found.abolished_only
        tail = None if parts is None else parts.tail
        detail = road_detail(road)
        floor = parse_floor(tail, detail)
        ho = parse_ho(tail, detail)
        pnus.append(pnu)
        pnu_failure.append(failure)
        abolished_only.append(only_abolished)
        floors.append(floor.floor)
        floor_sources.append(floor.source)
        floor_conflict.append(floor.conflict)
        hos.append(ho.ho_list)
        ho_conflict.append(ho.conflict)

    # ---- 좌표
    lat, lng = to_wgs84_arrays(_float(frame[X_COLUMN]), _float(frame[Y_COLUMN]))
    has_coords = np.isfinite(lat)
    outside = has_coords & ~(
        (lat >= SEOUL_LAT[0])
        & (lat <= SEOUL_LAT[1])
        & (lng >= SEOUL_LNG[0])
        & (lng <= SEOUL_LNG[1])
    )
    geom = [
        f"SRID=4326;POINT({x:.7f} {y:.7f})" if ok else None
        for ok, x, y in zip(has_coords, lng, lat, strict=True)
    ]

    records = pd.DataFrame(
        {
            "license_type": kind,
            "mgmt_no": frame[MGMT_NO],
            "jurisdiction_code": frame[JURISDICTION_COLUMN].str.strip(),
            "name": frame[NAME_COLUMN].str.strip(),
            "biz_category": category.where(category != "", None),
            "status": status,
            "status_raw": status_raw,
            "opened_on": opened,
            "closed_on": closed_on,
            "area_m2": frame[AREA_COLUMN].map(parse_area),
            "jibun_addr": _blank_to_none(frame[JIBUN_ADDR]),
            "road_addr": _blank_to_none(frame[ROAD_ADDR]),
            "pnu": pnus,
            "sigungu_code": [None if pnu is None else pnu[:5] for pnu in pnus],
            "floor": floors,
            "floor_source": floor_sources,
            "ho_list": hos,
            "geom_ewkt": geom,
            "bulk_closure": False,
            "no_fixed_place": category.isin(NO_FIXED_PLACE_CATEGORIES),
            "source_updated_at": frame[SOURCE_UPDATED_AT].str.strip(),
            "last_snapshot_id": frame[SNAPSHOT_ID],
        }
    )
    inversion = pd.Series(
        [c is not None and o is not None and c < o for o, c in zip(opened, closed_on, strict=True)]
    )
    is_closed = status == "closed"
    since_2005 = pd.Series([o is not None and o >= FLOOR_RATIO_FROM for o in opened])
    has_floor = records["floor"].notna()
    checks = pd.DataFrame(
        {
            "seoul_rows": True,
            "opened_on_parsed": opened.notna(),
            "date_inversion": inversion,
            "pnu_failed": pd.Series(pnu_failure).notna(),
            "pnu_abolished_only": abolished_only,
            "since_2005": since_2005,
            "since_2005_with_floor": since_2005 & has_floor,
            "with_coords": has_coords,
            "coords_outside": outside,
            "closed": is_closed,
            "closed_without_date": is_closed & closed_on.isna(),
        }
    )
    _tally(stats, checks, kind)
    reasons = pd.DataFrame({LICENSE_TYPE: kind, "reason": pnu_failure}).dropna()
    for license_type, stat in stats.items():
        counts = reasons.loc[reasons[LICENSE_TYPE] == license_type, "reason"].value_counts()
        stat.pnu_failures = {str(k): int(v) for k, v in counts.to_dict().items()}

    # ---- DV4 격리: 날짜가 역전된 행은 넣지 않는다 (테이블 CHECK와 같다)
    keep = ~inversion
    records = records[keep].reset_index(drop=True)
    kept = pd.DataFrame(
        {
            "records": True,
            "no_fixed_place": records["no_fixed_place"],
            "floor_conflict": pd.Series(floor_conflict)[keep].reset_index(drop=True),
            "ho_conflict": pd.Series(ho_conflict)[keep].reset_index(drop=True),
        }
    )

    # ---- 폐업 처리 급증일 (docs/10 §5): 식품 3종 합산
    closures = pd.DataFrame(
        {
            JURISDICTION: records["jurisdiction_code"],
            CLOSED_ON: records["closed_on"].where(records["status"] == "closed", None),
        }
    )
    days = detect_bulk_days(closures)
    records["bulk_closure"] = flag_bulk_closure(closures, days).to_numpy()
    kept["surge_records"] = records["bulk_closure"]
    _tally(stats, kept, records["license_type"])

    labels = _sigungu_label(frame)
    surge_days = pd.DataFrame(
        {
            "jurisdiction_code": days[JURISDICTION],
            "closed_on": days[CLOSED_ON],
            "jurisdiction_label": days[JURISDICTION].map(labels).astype(object),
            "closure_count": days[COUNT].astype(int),
            "median": days[MEDIAN].astype(float),
        }
    )
    surge_days["jurisdiction_label"] = surge_days["jurisdiction_label"].where(
        surge_days["jurisdiction_label"].notna(), None
    )
    # 빈 값은 열 종류와 상관없이 `None`으로 통일한다 (DB의 NULL)
    records = records.astype(object).where(records.notna(), None)
    return Normalized(
        records=records,
        surge_days=surge_days,
        stats=stats,
        surge_cells=len(days),
        surge_dates=int(days[CLOSED_ON].nunique()),
    )
