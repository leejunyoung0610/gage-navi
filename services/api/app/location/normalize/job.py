"""정규화 실행: `license_raw` → `license_record`·`closure_surge_day` + 검증 기록 (docs/50 §2).

종류별 최신 스냅샷을 한 번에 읽어 정규화한다. 실패 검사가 하나라도 있으면 `license_record`를
바꾸지 않고 실패한 스냅샷을 `failed`로 둔다 (기존 데이터 유지).
"""

import json
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import Any

import pandas as pd
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine

from app.address.pnu import LegalDongIndex
from app.location.ingest.license_file import parse_source_time
from app.location.normalize.records import (
    LICENSE_TYPE,
    PARSE_VERSION,
    RECORD_COLUMNS,
    SNAPSHOT_ID,
    SOURCE_COLUMNS,
    Normalized,
    normalize,
)
from app.location.normalize.validation import Previous, build_validation


class NormalizeError(RuntimeError):
    """정규화를 시작할 수 없는 상태 (스냅샷·법정동코드 없음)."""


@dataclass(frozen=True)
class SnapshotResult:
    snapshot_id: int
    license_type: str
    status: str  # 'validated' | 'failed' | 'unchanged'(다른 스냅샷의 실패로 반영하지 않음)
    validation: dict[str, Any]


@dataclass(frozen=True)
class NormalizeResult:
    applied: bool  # license_record에 반영했다
    snapshots: tuple[SnapshotResult, ...]
    records: int
    surge_days: int


_LATEST = """
SELECT DISTINCT ON (license_type) id, license_type
FROM data_snapshot
WHERE status IN ('loaded', 'validated')
ORDER BY license_type, id DESC
"""
_PREVIOUS = """
SELECT row_count, validation->'normalize'->'checks'->'DV7'->>'ratio' AS floor_ratio
FROM data_snapshot
WHERE license_type = :license_type AND status = 'validated' AND id < :id
ORDER BY id DESC LIMIT 1
"""
_STAGING = """
CREATE TEMP TABLE license_record_staging (
  license_type TEXT, mgmt_no TEXT, jurisdiction_code TEXT, name TEXT, biz_category TEXT,
  status TEXT, status_raw TEXT, opened_on DATE, closed_on DATE, area_m2 NUMERIC(10,2),
  jibun_addr TEXT, road_addr TEXT, pnu TEXT, sigungu_code TEXT, floor TEXT, floor_source TEXT,
  ho_list TEXT[], geom_ewkt TEXT, bulk_closure BOOLEAN, no_fixed_place BOOLEAN,
  source_updated_at TIMESTAMPTZ, last_snapshot_id BIGINT
) ON COMMIT DROP
"""
# `stale_suspect`는 T-017이 채운다. 여기서는 건드리지 않는다
_UPSERT = """
INSERT INTO license_record (
  license_type, mgmt_no, jurisdiction_code, name, biz_category, status, status_raw,
  opened_on, closed_on, area_m2, jibun_addr, road_addr, pnu, sigungu_code, floor, floor_source,
  ho_list, geom, bulk_closure, no_fixed_place, source_updated_at, last_snapshot_id, parse_version
)
SELECT license_type, mgmt_no, jurisdiction_code, name, biz_category, status, status_raw,
  opened_on, closed_on, area_m2, jibun_addr, road_addr, pnu, sigungu_code, floor, floor_source,
  ho_list, ST_GeomFromEWKT(geom_ewkt), bulk_closure, no_fixed_place, source_updated_at,
  last_snapshot_id, :parse_version
FROM license_record_staging
ON CONFLICT (license_type, mgmt_no) DO UPDATE SET
  jurisdiction_code = EXCLUDED.jurisdiction_code, name = EXCLUDED.name,
  biz_category = EXCLUDED.biz_category, status = EXCLUDED.status,
  status_raw = EXCLUDED.status_raw, opened_on = EXCLUDED.opened_on,
  closed_on = EXCLUDED.closed_on, area_m2 = EXCLUDED.area_m2, jibun_addr = EXCLUDED.jibun_addr,
  road_addr = EXCLUDED.road_addr, pnu = EXCLUDED.pnu, sigungu_code = EXCLUDED.sigungu_code,
  floor = EXCLUDED.floor, floor_source = EXCLUDED.floor_source, ho_list = EXCLUDED.ho_list,
  geom = EXCLUDED.geom, bulk_closure = EXCLUDED.bulk_closure,
  no_fixed_place = EXCLUDED.no_fixed_place, source_updated_at = EXCLUDED.source_updated_at,
  last_snapshot_id = EXCLUDED.last_snapshot_id, parse_version = EXCLUDED.parse_version
"""
_SURGE_INSERT = """
INSERT INTO closure_surge_day
  (jurisdiction_code, closed_on, jurisdiction_label, closure_count, median_daily, parse_version)
VALUES (:jurisdiction_code, :closed_on, :jurisdiction_label, :closure_count, :median, :version)
"""
_SET_VALIDATION = """
UPDATE data_snapshot
SET status = :status,
    validation = validation || jsonb_build_object('normalize', CAST(:validation AS jsonb))
WHERE id = :id
"""


async def _read_raw(conn: AsyncConnection, snapshot_ids: list[int]) -> pd.DataFrame:
    selects = ", ".join(
        f"coalesce(payload->>:c{number}, '')" for number in range(len(SOURCE_COLUMNS))
    )
    rows = await conn.execute(
        text(
            f"SELECT snapshot_id, license_type, {selects} FROM license_raw "
            "WHERE snapshot_id = ANY(:ids)"
        ),
        {"ids": snapshot_ids} | {f"c{n}": column for n, column in enumerate(SOURCE_COLUMNS)},
    )
    return pd.DataFrame(rows.all(), columns=[SNAPSHOT_ID, LICENSE_TYPE, *SOURCE_COLUMNS])


async def _previous(conn: AsyncConnection, snapshot_id: int, license_type: str) -> Previous | None:
    row = (
        await conn.execute(text(_PREVIOUS), {"license_type": license_type, "id": snapshot_id})
    ).first()
    if row is None:
        return None
    try:
        floor_ratio = None if row.floor_ratio is None else Decimal(row.floor_ratio)
    except InvalidOperation:
        floor_ratio = None
    return Previous(row_count=int(row.row_count), floor_ratio=floor_ratio)


async def _write(conn: AsyncConnection, normalized: Normalized) -> None:
    records = normalized.records.copy()
    records["source_updated_at"] = [
        None if value is None else parse_source_time(value)
        for value in records["source_updated_at"]
    ]
    await conn.execute(text(_STAGING))
    raw_conn = await conn.get_raw_connection()
    await raw_conn.driver_connection.copy_records_to_table(  # type: ignore[union-attr]
        "license_record_staging",
        records=list(records[list(RECORD_COLUMNS)].itertuples(index=False, name=None)),
        columns=RECORD_COLUMNS,
    )
    await conn.execute(text(_UPSERT), {"parse_version": PARSE_VERSION})
    await conn.execute(text("DELETE FROM closure_surge_day"))
    surge = normalized.surge_days.to_dict("records")
    if surge:
        await conn.execute(
            text(_SURGE_INSERT),
            [
                {
                    "jurisdiction_code": row["jurisdiction_code"],
                    "closed_on": row["closed_on"],
                    "jurisdiction_label": row["jurisdiction_label"],
                    "closure_count": row["closure_count"],
                    "median": Decimal(str(row["median"])),
                    "version": PARSE_VERSION,
                }
                for row in surge
            ],
        )


async def run_normalize(engine: AsyncEngine) -> NormalizeResult:
    """종류별 최신 스냅샷을 정규화하고 검증 결과를 스냅샷에 적는다 (한 트랜잭션)."""
    async with engine.begin() as conn:
        snapshots = [
            (int(row.id), str(row.license_type)) for row in await conn.execute(text(_LATEST))
        ]
        if not snapshots:
            raise NormalizeError(
                "적재된 스냅샷이 없습니다. jobs.ingest_licenses를 먼저 실행하세요."
            )
        dongs = [
            (str(code), str(full_name), bool(abolished))
            for code, full_name, abolished in await conn.execute(
                text("SELECT code, full_name, abolished FROM legal_dong")
            )
        ]
        if not dongs:
            raise NormalizeError(
                "legal_dong이 비어 있습니다. jobs.ingest_legal_dong을 먼저 실행하세요."
            )

        raw = await _read_raw(conn, [snapshot_id for snapshot_id, _ in snapshots])
        normalized = normalize(raw, LegalDongIndex.from_rows(dongs))

        validations: dict[int, dict[str, Any]] = {}
        for snapshot_id, license_type in snapshots:
            validations[snapshot_id] = build_validation(
                normalized.stats[license_type],
                await _previous(conn, snapshot_id, license_type),
                normalized.surge_cells,
                normalized.surge_dates,
            )
        applied = all(validation["passed"] for validation in validations.values())
        if applied:
            await _write(conn, normalized)

        results = []
        for snapshot_id, license_type in snapshots:
            validation = validations[snapshot_id]
            validation["applied"] = applied
            if applied:
                status = "validated"
            elif not validation["passed"]:
                status = "failed"
            else:
                # 다른 스냅샷의 실패로 반영하지 못했다. 이 스냅샷의 상태와 기록은 그대로 둔다
                results.append(SnapshotResult(snapshot_id, license_type, "unchanged", validation))
                continue
            await conn.execute(
                text(_SET_VALIDATION),
                {
                    "status": status,
                    "validation": json.dumps(validation, ensure_ascii=False),
                    "id": snapshot_id,
                },
            )
            results.append(SnapshotResult(snapshot_id, license_type, status, validation))
    return NormalizeResult(
        applied=applied,
        snapshots=tuple(results),
        records=len(normalized.records) if applied else 0,
        surge_days=len(normalized.surge_days) if applied else 0,
    )
