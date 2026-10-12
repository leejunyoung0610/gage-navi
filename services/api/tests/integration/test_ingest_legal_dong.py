"""법정동코드 적재와 PNU 실패율 측정 (T-011). 픽스처의 코드·지명·주소는 모두 가상 예시다."""

import asyncio
import json
from pathlib import Path
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.pool import NullPool

from app.address.legal_dong_file import LegalDongIngestResult, ingest_file
from app.address.pnu import FAIL_DONG_NOT_FOUND, FAIL_REGEX_MISMATCH
from jobs.measure_pnu import collect
from tests.unit.test_legal_dong_file import LINES, write


def run_with_engine(url: str, work: Any) -> Any:
    async def run() -> Any:
        engine = create_async_engine(url, poolclass=NullPool)
        try:
            return await work(engine)
        finally:
            await engine.dispose()

    return asyncio.run(run())


def ingest(url: str, path: Path) -> LegalDongIngestResult:
    result: LegalDongIngestResult = run_with_engine(url, lambda engine: ingest_file(engine, path))
    return result


def execute(url: str, sql: str, params: dict[str, Any] | None = None) -> list[Any]:
    async def work(engine: Any) -> list[Any]:
        async with engine.begin() as conn:
            result = await conn.execute(text(sql), params or {})
            return list(result.all()) if result.returns_rows else []

    rows: list[Any] = run_with_engine(url, work)
    return rows


def test_file_is_loaded_and_reload_changes_nothing(migrated_db_url: str, tmp_path: Path) -> None:
    path = write(tmp_path / "a.csv")

    first = ingest(migrated_db_url, path)
    second = ingest(migrated_db_url, path)

    assert (first.file_rows, first.table_rows) == (4, 4)
    assert second == first
    rows = execute(
        migrated_db_url,
        "SELECT code, sido, sigungu, eupmyeondong, ri, full_name, abolished "
        "FROM legal_dong WHERE code = '9911010100'",
    )
    assert [tuple(row) for row in rows] == [
        ("9911010100", "가상특별시", "가상구", "가상동", None, "가상특별시 가상구 가상동", False)
    ]


def test_rows_missing_from_a_later_file_are_kept(migrated_db_url: str, tmp_path: Path) -> None:
    ingest(migrated_db_url, write(tmp_path / "a.csv"))
    execute(
        migrated_db_url,
        "INSERT INTO legal_dong (code, sido, sigungu, eupmyeondong, full_name, abolished) "
        "VALUES ('9911019900', '가상특별시', '가상구', '옛가상동', "
        "'가상특별시 가상구 옛가상동', true)",
    )

    result = ingest(migrated_db_url, write(tmp_path / "b.csv", LINES[:3]))

    assert (result.file_rows, result.table_rows) == (3, 5)
    kept = execute(migrated_db_url, "SELECT abolished FROM legal_dong WHERE code = '9911019900'")
    assert kept[0][0] is True


def test_measure_reads_latest_snapshot_per_type(migrated_db_url: str) -> None:
    execute(
        migrated_db_url,
        "INSERT INTO legal_dong (code, sido, sigungu, eupmyeondong, full_name) VALUES "
        "('9921010100', '서울특별시', '가상구', '현행동', '서울특별시 가상구 현행동') "
        "ON CONFLICT DO NOTHING",
    )
    road = "서울특별시 가상구 가상로 1"
    addresses = {
        # 옛 스냅샷: 측정에 들어가면 안 된다
        1: ["서울특별시 가상구 없는동 9"] * 5,
        2: ["서울특별시 가상구 현행동 1-1", "서울특별시 가상구 없는동 2", ""],
    }
    for number, jibuns in addresses.items():
        snapshot_id = execute(
            migrated_db_url,
            "INSERT INTO data_snapshot (source, license_type, row_count, file_sha256, status) "
            "VALUES ('license_file', 'bakery', :rows, :sha, 'loaded') RETURNING id",
            {"rows": len(jibuns), "sha": f"{number:064d}"},
        )[0][0]
        for index, jibun in enumerate(jibuns):
            execute(
                migrated_db_url,
                "INSERT INTO license_raw (snapshot_id, license_type, mgmt_no, payload) "
                "VALUES (:id, 'bakery', :mgmt_no, CAST(:payload AS jsonb))",
                {
                    "id": snapshot_id,
                    "mgmt_no": f"가상-{number}-{index}",
                    "payload": json.dumps({"지번주소": jibun, "도로명주소": road}),
                },
            )

    stats, labels, legal_dong_rows = run_with_engine(migrated_db_url, collect)

    assert stats.total == 3
    assert stats.by_reason == {FAIL_DONG_NOT_FOUND: 1, FAIL_REGEX_MISMATCH: 1}
    assert len(labels) == 1
    assert labels[0].startswith("bakery #")
    assert legal_dong_rows >= 1
