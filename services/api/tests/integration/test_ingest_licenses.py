"""인허가 파일 적재 (T-010). 픽스처의 업소·주소·관리번호는 모두 가상 예시다."""

import asyncio
import os
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.pool import NullPool

from app.location.ingest.license_file import IngestResult, LicenseFileError, ingest_file
from tests.license_csv import COLUMNS, ROWS, write_csv

REPO_ROOT = Path(__file__).resolve().parents[4]
# 실제 원천 파일 (gitignore). 없으면 해당 테스트는 건너뛴다.
GENERAL_RESTAURANT_FILE = Path(
    os.environ.get("LICENSE_GENERAL_CSV") or REPO_ROOT / "data" / "식품_일반음식점_서울특별시.csv"
)


def ingest(url: str, license_type: str, path: Path) -> IngestResult:
    async def run() -> IngestResult:
        engine = create_async_engine(url, poolclass=NullPool)
        try:
            return await ingest_file(engine, license_type, path)
        finally:
            await engine.dispose()

    return asyncio.run(run())


def fetch_all(url: str, sql: str) -> list[Any]:
    async def run() -> list[Any]:
        engine = create_async_engine(url, poolclass=NullPool)
        try:
            async with engine.connect() as conn:
                return list((await conn.execute(text(sql))).all())
        finally:
            await engine.dispose()

    return asyncio.run(run())


def test_file_is_loaded_into_snapshot_and_raw(migrated_db_url: str, tmp_path: Path) -> None:
    result = ingest(migrated_db_url, "general_restaurant", write_csv(tmp_path / "a.csv"))

    assert (result.row_count, result.non_seoul_address_rows, result.skipped) == (3, 1, False)
    snapshot = fetch_all(
        migrated_db_url,
        "SELECT source, license_type, row_count, file_sha256, status, validation, "
        "source_updated_max AT TIME ZONE 'Asia/Seoul' AS updated "
        f"FROM data_snapshot WHERE id = {result.snapshot_id}",
    )[0]
    assert (snapshot.source, snapshot.license_type, snapshot.status) == (
        "license_file",
        "general_restaurant",
        "loaded",
    )
    assert snapshot.row_count == 3
    assert snapshot.file_sha256 == result.file_sha256
    assert str(snapshot.updated) == "2026-10-07 22:47:53"
    assert snapshot.validation["ingest"] == {
        "file_rows": 3,
        "non_seoul_address_rows": 1,
        "source_time_unparsed_rows": 1,
        "encoding": "cp949",
    }

    raw = fetch_all(
        migrated_db_url,
        "SELECT license_type, mgmt_no, payload FROM license_raw "
        f"WHERE snapshot_id = {result.snapshot_id} ORDER BY mgmt_no",
    )
    assert [row.mgmt_no for row in raw] == [
        "3040000-101-2020-00001",
        "3040000-101-2020-00002",
        "3040000-101-2021-00003",
    ]
    assert {row.license_type for row in raw} == {"general_restaurant"}
    # 원문 컬럼명 그대로(JSONB라 키 순서는 보존되지 않는다), 줄바꿈 포함 주소도 한 행으로
    assert set(raw[1].payload) == set(COLUMNS)
    assert raw[1].payload["지번주소"] == "서울특별시 광진구 화양동 2-2\n지하1층"
    # 서울 밖 주소 행도 빼지 않는다
    assert raw[2].payload["지번주소"].startswith("경기도")


def test_same_file_again_is_skipped(migrated_db_url: str, tmp_path: Path) -> None:
    path = write_csv(tmp_path / "b.csv", ROWS[:2])
    first = ingest(migrated_db_url, "bakery", path)
    second = ingest(migrated_db_url, "bakery", path)

    assert second.skipped and not first.skipped
    assert second.snapshot_id == first.snapshot_id
    assert (second.row_count, second.non_seoul_address_rows) == (2, 0)
    count = fetch_all(
        migrated_db_url, "SELECT count(*) AS n FROM data_snapshot WHERE license_type = 'bakery'"
    )[0]
    assert count.n == 1


def test_same_file_for_another_type_is_a_new_snapshot(migrated_db_url: str, tmp_path: Path) -> None:
    path = write_csv(tmp_path / "c.csv", ROWS[:1])
    first = ingest(migrated_db_url, "rest_restaurant", path)
    other = ingest(migrated_db_url, "general_restaurant", path)
    assert other.snapshot_id != first.snapshot_id and not other.skipped


def test_duplicate_mgmt_no_loads_nothing(migrated_db_url: str, tmp_path: Path) -> None:
    before = fetch_all(migrated_db_url, "SELECT count(*) AS n FROM data_snapshot")[0].n
    path = write_csv(
        tmp_path / "d.csv", [ROWS[0], ROWS[2], [*ROWS[0][:4], "가상식당2", *ROWS[0][5:]]]
    )
    with pytest.raises(LicenseFileError, match="중복"):
        ingest(migrated_db_url, "general_restaurant", path)

    assert fetch_all(migrated_db_url, "SELECT count(*) AS n FROM data_snapshot")[0].n == before
    orphan = fetch_all(
        migrated_db_url,
        "SELECT count(*) AS n FROM license_raw r "
        "WHERE NOT EXISTS (SELECT 1 FROM data_snapshot s WHERE s.id = r.snapshot_id)",
    )[0]
    assert orphan.n == 0


def test_unknown_license_type_is_rejected(migrated_db_url: str, tmp_path: Path) -> None:
    with pytest.raises(LicenseFileError, match="인허가 종류"):
        ingest(migrated_db_url, "hotel", write_csv(tmp_path / "e.csv"))


def test_seoul_general_restaurant_file_loads_539589_rows(migrated_db_url: str) -> None:
    """T-010 수용 기준: 2026-10-08 서울 일반음식점 파일 적재 행 수 = 539,589."""
    if not GENERAL_RESTAURANT_FILE.exists():
        pytest.skip(f"원천 파일이 없어 건너뜀: {GENERAL_RESTAURANT_FILE} (data/README.md 참고)")
    result = ingest(migrated_db_url, "general_restaurant", GENERAL_RESTAURANT_FILE)

    assert result.row_count == 539_589
    loaded = fetch_all(
        migrated_db_url,
        f"SELECT count(*) AS n FROM license_raw WHERE snapshot_id = {result.snapshot_id}",
    )[0]
    assert loaded.n == 539_589
