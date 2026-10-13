"""층 이력 빌드: `license_record` → `parcel`·`floor_summary`·`record_prior` (docs/10 §7.1·§7.2).

세 테이블을 한 트랜잭션에서 전부 다시 만든다. 같은 입력이면 같은 결과가 된다.
"""

from dataclasses import dataclass
from datetime import date, datetime

import pandas as pd
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine

from app.core.db import DISPLAY_TZ
from app.location.history.build import (
    METHOD_VERSION,
    PRIOR,
    PRIOR_EX_SURGE,
    build_floor_summary,
    build_parcels,
    build_record_prior,
)


class HistoryBuildError(RuntimeError):
    """빌드를 시작할 수 없는 상태 (기준일을 정할 스냅샷이 없음)."""


@dataclass(frozen=True)
class HistoryResult:
    as_of: date
    records: int  # 읽은 기록 (`pnu`가 있는 `license_record`)
    parcels: int
    floors: int
    floors_with_concurrent: int
    priors: int
    priors_changed_by_surge: int  # 급증일 폐업을 빼면 과거 폐업 횟수가 달라지는 기록


_COLUMNS = (
    "id",
    "pnu",
    "floor",
    "status",
    "opened_on",
    "closed_on",
    "bulk_closure",
    "no_fixed_place",
    "suppressed",
    "road_addr",
    "geom_ewkt",
)
_RECORDS = """
SELECT r.id, r.pnu, r.floor, r.status, r.opened_on, r.closed_on, r.bulk_closure,
       r.no_fixed_place, s.record_id IS NOT NULL, r.road_addr, ST_AsEWKT(r.geom)
FROM license_record r
LEFT JOIN record_suppression s ON s.record_id = r.id
WHERE r.pnu IS NOT NULL
"""
# 정규화까지 통과한 종류별 최신 스냅샷의 데이터 기준 시각 중 가장 이른 값 (docs/10 §7.1)
_AS_OF = """
SELECT min(source_updated_max) FROM (
  SELECT DISTINCT ON (license_type) source_updated_max
  FROM data_snapshot WHERE status = 'validated'
  ORDER BY license_type, id DESC
) latest
"""
_PARCEL_STAGING = """
CREATE TEMP TABLE parcel_staging (
  pnu TEXT, legal_dong_code TEXT, jibun_label TEXT, road_addr TEXT, geom_ewkt TEXT,
  floors TEXT[], record_count INT
) ON COMMIT DROP
"""
_PARCEL_INSERT = """
INSERT INTO parcel (pnu, legal_dong_code, jibun_label, road_addr, geom, floors, record_count)
SELECT pnu, legal_dong_code, jibun_label, road_addr, ST_GeomFromEWKT(geom_ewkt), floors,
       record_count
FROM parcel_staging
"""


async def default_as_of(conn: AsyncConnection) -> date:
    earliest: datetime | None = (await conn.execute(text(_AS_OF))).scalar()
    if earliest is None:
        raise HistoryBuildError(
            "정규화를 통과한 스냅샷이 없어 기준일을 정할 수 없습니다. "
            "jobs.normalize_licenses를 먼저 실행하거나 --as-of를 주세요."
        )
    return earliest.astimezone(DISPLAY_TZ).date()


async def _copy(conn: AsyncConnection, table: str, frame: pd.DataFrame) -> None:
    raw_conn = await conn.get_raw_connection()
    await raw_conn.driver_connection.copy_records_to_table(  # type: ignore[union-attr]
        table,
        records=list(frame.itertuples(index=False, name=None)),
        columns=list(frame.columns),
    )


async def build_history(engine: AsyncEngine, as_of: date | None = None) -> HistoryResult:
    """세 테이블을 다시 만든다. `as_of`를 주지 않으면 스냅샷의 데이터 기준일을 쓴다."""
    async with engine.begin() as conn:
        if as_of is None:
            as_of = await default_as_of(conn)
        records = pd.DataFrame((await conn.execute(text(_RECORDS))).all(), columns=list(_COLUMNS))
        dong_names = {
            str(code): str(full_name)
            for code, full_name in await conn.execute(
                text("SELECT code, full_name FROM legal_dong")
            )
        }

        parcels = build_parcels(records, dong_names)
        floors = build_floor_summary(records, as_of)
        priors = build_record_prior(records, as_of)
        priors["method_version"] = METHOD_VERSION
        floors = floors.astype(object).where(floors.notna(), None)

        for table in ("floor_summary", "parcel", "record_prior"):
            await conn.execute(text(f"DELETE FROM {table}"))
        await conn.execute(text(_PARCEL_STAGING))
        await _copy(conn, "parcel_staging", parcels)
        await conn.execute(text(_PARCEL_INSERT))
        await _copy(conn, "floor_summary", floors)
        await _copy(conn, "record_prior", priors)
    return HistoryResult(
        as_of=as_of,
        records=len(records),
        parcels=len(parcels),
        floors=len(floors),
        floors_with_concurrent=int(floors["has_concurrent"].astype(bool).sum()),
        priors=len(priors),
        priors_changed_by_surge=int((priors[PRIOR] != priors[PRIOR_EX_SURGE]).sum()),
    )
