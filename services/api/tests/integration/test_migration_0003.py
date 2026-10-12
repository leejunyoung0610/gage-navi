"""마이그레이션 0003_normalize: 왕복, `no_fixed_place` 기본값, 급증일 표의 키 (docs/04 §2)."""

import asyncio
from collections.abc import Callable
from typing import Any

import pytest
from alembic.config import Config
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.pool import NullPool

from alembic import command

UNIQUE_VIOLATION = "23505"
COLUMNS = """
    SELECT table_name, column_name, data_type, is_nullable, column_default,
           numeric_precision, numeric_scale
    FROM information_schema.columns
    WHERE table_schema = 'public'
      AND (table_name = 'closure_surge_day'
           OR (table_name = 'license_record' AND column_name = 'no_fixed_place'))
    ORDER BY table_name, ordinal_position
"""
# 가상 예시 값
SURGE_INSERT = """
    INSERT INTO closure_surge_day
      (jurisdiction_code, closed_on, jurisdiction_label, closure_count, median_daily, parse_version)
    VALUES ('3130000', '2020-03-09', {label}, 30, 2.5, '2026.10.1')
"""
RECORD_INSERT = """
    INSERT INTO license_record
      (license_type, mgmt_no, jurisdiction_code, name, status, status_raw, parse_version)
    VALUES ('bakery', '가상-1', '3130000', '가상제과', 'open', '영업/정상', '2026.10.1')
    RETURNING no_fixed_place
"""


def _query(url: str, statements: list[str]) -> list[Any]:
    """문장들을 한 트랜잭션에서 실행하고 되돌린다. 마지막 문장의 결과를 낸다."""

    async def run() -> list[Any]:
        engine = create_async_engine(url, poolclass=NullPool)
        try:
            async with engine.connect() as conn:
                transaction = await conn.begin()
                try:
                    rows: list[Any] = []
                    for statement in statements:
                        result = await conn.execute(text(statement))
                        rows = list(result.all()) if result.returns_rows else []
                    return rows
                finally:
                    await transaction.rollback()
        finally:
            await engine.dispose()

    return asyncio.run(run())


def test_upgrade_downgrade_upgrade_roundtrip(
    empty_db_url: str, make_alembic_config: Callable[[str], Config]
) -> None:
    config = make_alembic_config(empty_db_url)

    command.upgrade(config, "head")
    first = _query(empty_db_url, [COLUMNS])
    assert {(row[0], row[1]) for row in first} == {
        ("license_record", "no_fixed_place"),
        ("closure_surge_day", "jurisdiction_code"),
        ("closure_surge_day", "closed_on"),
        ("closure_surge_day", "jurisdiction_label"),
        ("closure_surge_day", "closure_count"),
        ("closure_surge_day", "median_daily"),
        ("closure_surge_day", "parse_version"),
    }

    command.downgrade(config, "0002_rules")
    assert _query(empty_db_url, [COLUMNS]) == []

    command.upgrade(config, "head")
    assert _query(empty_db_url, [COLUMNS]) == first


def test_no_fixed_place_defaults_to_false(migrated_db_url: str) -> None:
    assert _query(migrated_db_url, [RECORD_INSERT])[0].no_fixed_place is False


def test_surge_day_allows_unknown_label_and_rejects_duplicate_key(migrated_db_url: str) -> None:
    rows = _query(
        migrated_db_url,
        [SURGE_INSERT.format(label="NULL"), "SELECT median_daily::text FROM closure_surge_day"],
    )
    assert [tuple(row) for row in rows] == [("2.5",)]
    with pytest.raises(IntegrityError) as raised:
        _query(migrated_db_url, [SURGE_INSERT.format(label="'마포구'")] * 2)
    assert getattr(raised.value.orig, "sqlstate", None) == UNIQUE_VIOLATION
