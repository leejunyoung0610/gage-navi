"""장소 API가 읽는 DB 행 (docs/30 §2, docs/04 §2). 쓰기는 없다."""

import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass
from datetime import date, datetime
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from app.core.db import DISPLAY_TZ, get_engine
from app.location.history.build import SINCE
from app.location.places.build import SEOUL_SCOPE, FloorScale, RateRow, Record

QUERY_TIMEOUT_SECONDS = 5.0

# 이력 기준일: 정규화를 통과한 종류별 최신 스냅샷의 데이터 기준 시각 중 가장 이른 값
# (`jobs.build_history`의 기본 기준일, docs/10 §7.1)
_AS_OF = """
SELECT min(source_updated_max) FROM (
  SELECT DISTINCT ON (license_type) source_updated_max
  FROM data_snapshot WHERE status = 'validated'
  ORDER BY license_type, id DESC
) latest
"""

_PARCEL = """
SELECT jibun_label, road_addr, ST_Y(geom) AS lat, ST_X(geom) AS lng, floors
FROM parcel WHERE pnu = :pnu
"""

_FLOOR_COUNTS = """
SELECT floor, record_count, open_now_count FROM floor_summary WHERE pnu = :pnu
"""

_FLOOR_SUMMARY = """
SELECT record_count, records_since_2005, open_now_count, median_closed_tenure_days,
       has_concurrent, max_concurrent
FROM floor_summary WHERE pnu = :pnu AND floor = :floor
"""

# 이력에 보이는 기록 `H`: 고정된 자리가 있고 숨김 처리되지 않은 기록 (docs/10 §7.1)
_VISIBLE = """
SELECT r.id, r.name, r.license_type, r.biz_category, r.opened_on, r.closed_on, r.status,
       r.ho_list, r.bulk_closure, r.stale_suspect, r.floor,
       s.jurisdiction_label, s.closure_count
FROM license_record r
LEFT JOIN closure_surge_day s
  ON r.bulk_closure AND s.jurisdiction_code = r.jurisdiction_code AND s.closed_on = r.closed_on
WHERE r.pnu = :pnu AND NOT r.no_fixed_place
  AND NOT EXISTS (SELECT 1 FROM record_suppression x WHERE x.record_id = r.id)
  AND {floor_condition}
ORDER BY r.opened_on NULLS LAST, r.id
"""

# 화면의 "이 층의 현재 과거 폐업 횟수": `F`에서 급증일 폐업과 숨김 기록을 뺀 폐업 수
# (docs/10 §7.2). 화면 이력과 같은 기록만 센다. 기준율 통계(`F`)는 숨김 기록을 포함한다
_PRIOR_NOW = """
SELECT count(*) FROM license_record r
WHERE r.pnu = :pnu AND r.floor = :floor AND NOT r.no_fixed_place
  AND r.status = 'closed' AND NOT r.bulk_closure AND r.closed_on <= :as_of
  AND NOT EXISTS (SELECT 1 FROM record_suppression x WHERE x.record_id = r.id)
"""

# 알림 `pre_2005_floor_missing`: 같은 필지(`H`)의 층 정보 없는 기록 중 2005년 전 개업
_PRE_2005_FLOORLESS = """
SELECT EXISTS (
  SELECT 1 FROM license_record r
  WHERE r.pnu = :pnu AND r.floor IS NULL AND NOT r.no_fixed_place AND r.opened_on < :since
    AND NOT EXISTS (SELECT 1 FROM record_suppression x WHERE x.record_id = r.id)
)
"""

_LATEST_CARD = """
SELECT snapshot_label, method_version, payload -> 'by_floor_scale'
FROM model_card WHERE method_version <> 'w0' ORDER BY id DESC LIMIT 1
"""

_RATES = """
SELECT scope_code, prior_bucket, n, rate, ci_low, ci_high FROM base_rate
WHERE snapshot_label = :snapshot_label AND method_version = :method_version
  AND license_group = 'food3' AND floor_scale = :floor_scale
  AND scope_code = ANY(:scopes) AND prior_bucket = ANY(:buckets)
"""

_SIGUNGU_LABEL = "SELECT sigungu FROM legal_dong WHERE code = :code"


@dataclass(frozen=True)
class ParcelRow:
    jibun_label: str
    road_addr: str | None
    lat: float | None
    lng: float | None
    floors: list[str]


@dataclass(frozen=True)
class FloorCount:
    floor: str
    record_count: int
    open_now_count: int


@dataclass(frozen=True)
class FloorSummaryRow:
    record_count: int
    records_since_2005: int
    open_now_count: int
    median_closed_tenure_days: int | None
    has_concurrent: bool
    max_concurrent: int


@dataclass(frozen=True)
class ModelCardRef:
    snapshot_label: str
    method_version: str
    by_floor_scale: Any


class PlaceReader:
    """한 요청 동안 연결 하나로 읽는다."""

    def __init__(self, conn: AsyncConnection) -> None:
        self._conn = conn

    async def as_of(self) -> date | None:
        earliest: datetime | None = (await self._conn.execute(text(_AS_OF))).scalar()
        return None if earliest is None else earliest.astimezone(DISPLAY_TZ).date()

    async def parcel(self, pnu: str) -> ParcelRow | None:
        row = (await self._conn.execute(text(_PARCEL), {"pnu": pnu})).one_or_none()
        if row is None:
            return None
        return ParcelRow(str(row[0]), row[1], row[2], row[3], list(row[4]))

    async def floor_counts(self, pnu: str) -> dict[str, FloorCount]:
        rows = await self._conn.execute(text(_FLOOR_COUNTS), {"pnu": pnu})
        return {str(r[0]): FloorCount(str(r[0]), int(r[1]), int(r[2])) for r in rows}

    async def floor_summary(self, pnu: str, floor: str) -> FloorSummaryRow | None:
        params = {"pnu": pnu, "floor": floor}
        row = (await self._conn.execute(text(_FLOOR_SUMMARY), params)).one_or_none()
        if row is None:
            return None
        return FloorSummaryRow(
            int(row[0]), int(row[1]), int(row[2]), row[3], bool(row[4]), int(row[5])
        )

    async def records(self, pnu: str, floor: str | None) -> list[Record]:
        """`floor`가 None이면 층을 알 수 없는 기록, 아니면 그 층의 기록."""
        condition = "r.floor IS NULL" if floor is None else "r.floor = :floor"
        params: dict[str, Any] = {"pnu": pnu} if floor is None else {"pnu": pnu, "floor": floor}
        rows = await self._conn.execute(text(_VISIBLE.format(floor_condition=condition)), params)
        return [
            Record(
                record_id=int(r[0]),
                name=str(r[1]),
                license_type=str(r[2]),
                biz_category=r[3],
                opened_on=r[4],
                closed_on=r[5],
                status=str(r[6]),
                ho_list=tuple(r[7]),
                bulk_closure=bool(r[8]),
                stale_suspect=bool(r[9]),
                floor=r[10],
                surge_label=r[11],
                surge_count=None if r[12] is None else int(r[12]),
            )
            for r in rows
        ]

    async def prior_closures_now(self, pnu: str, floor: str, as_of: date) -> int:
        params = {"pnu": pnu, "floor": floor, "as_of": as_of}
        return int((await self._conn.execute(text(_PRIOR_NOW), params)).scalar_one())

    async def pre_2005_floorless(self, pnu: str) -> bool:
        params = {"pnu": pnu, "since": SINCE}
        return bool((await self._conn.execute(text(_PRE_2005_FLOORLESS), params)).scalar_one())

    async def latest_model_card(self) -> ModelCardRef | None:
        row = (await self._conn.execute(text(_LATEST_CARD))).one_or_none()
        return None if row is None else ModelCardRef(str(row[0]), str(row[1]), row[2])

    async def rates(
        self, card: ModelCardRef, scale: FloorScale, sigungu_code: str, bucket: str
    ) -> list[RateRow]:
        params = {
            "snapshot_label": card.snapshot_label,
            "method_version": card.method_version,
            "floor_scale": scale,
            "scopes": sorted({SEOUL_SCOPE, sigungu_code}),
            "buckets": sorted({bucket, "0"}),
        }
        rows = await self._conn.execute(text(_RATES), params)
        return [RateRow(str(r[0]), str(r[1]), int(r[2]), r[3], r[4], r[5]) for r in rows]

    async def sigungu_label(self, sigungu_code: str) -> str | None:
        params = {"code": f"{sigungu_code}00000"}
        label: str | None = (await self._conn.execute(text(_SIGUNGU_LABEL), params)).scalar()
        return label


@asynccontextmanager
async def reader_session() -> AsyncIterator[PlaceReader]:
    """연결 하나를 열고 시간 제한을 건다."""
    async with asyncio.timeout(QUERY_TIMEOUT_SECONDS):
        async with get_engine().connect() as conn:
            yield PlaceReader(conn)
