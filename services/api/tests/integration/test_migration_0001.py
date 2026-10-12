"""마이그레이션 0001_location: 왕복, CHECK 제약 (docs/04 §2)."""

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

LOCATION_TABLES = {
    "data_snapshot",
    "license_raw",
    "legal_dong",
    "license_record",
    "parcel",
    "floor_summary",
    "record_prior",
    "base_rate",
    "model_card",
    "correction_request",
    "record_suppression",
}
CHECK_VIOLATION = "23514"

SCHEMA_QUERIES = {
    "columns": """
        SELECT table_name, column_name, data_type, udt_name, is_nullable, column_default,
               character_maximum_length, numeric_precision, numeric_scale
        FROM information_schema.columns
        WHERE table_schema = 'public' AND table_name = ANY(:tables)
        ORDER BY table_name, ordinal_position
    """,
    "constraints": """
        SELECT c.conrelid::regclass::text, c.conname, pg_get_constraintdef(c.oid)
        FROM pg_constraint c
        WHERE c.conrelid::regclass::text = ANY(:tables)
        ORDER BY 1, 2
    """,
    "indexes": """
        SELECT tablename, indexname, indexdef FROM pg_indexes
        WHERE schemaname = 'public' AND tablename = ANY(:tables)
        ORDER BY 1, 2
    """,
}


async def _fetch_all(url: str, queries: dict[str, str]) -> dict[str, list[tuple[Any, ...]]]:
    engine = create_async_engine(url, poolclass=NullPool)
    try:
        async with engine.connect() as conn:
            params = {"tables": sorted(LOCATION_TABLES)}
            return {
                key: [tuple(row) for row in await conn.execute(text(sql), params)]
                for key, sql in queries.items()
            }
    finally:
        await engine.dispose()


def _schema(url: str) -> dict[str, list[tuple[Any, ...]]]:
    return asyncio.run(_fetch_all(url, SCHEMA_QUERIES))


def _tables(schema: dict[str, list[tuple[Any, ...]]]) -> set[str]:
    return {row[0] for row in schema["columns"]}


def test_upgrade_downgrade_upgrade_roundtrip(
    empty_db_url: str, make_alembic_config: Callable[[str], Config]
) -> None:
    config = make_alembic_config(empty_db_url)

    command.upgrade(config, "head")
    first = _schema(empty_db_url)
    assert _tables(first) == LOCATION_TABLES

    command.downgrade(config, "base")
    assert _tables(_schema(empty_db_url)) == set()

    command.upgrade(config, "head")
    assert _schema(empty_db_url) == first


async def _run_in_rollback(url: str, statements: list[str]) -> None:
    engine = create_async_engine(url, poolclass=NullPool)
    try:
        async with engine.connect() as conn:
            transaction = await conn.begin()
            try:
                for statement in statements:
                    await conn.execute(text(statement))
            finally:
                await transaction.rollback()
    finally:
        await engine.dispose()


# 테스트용 가상 예시 값 (실제 업소·필지가 아니다)
SNAPSHOT_INSERT = """
    INSERT INTO data_snapshot (source, license_type, row_count, status)
    VALUES ('{source}', '{license_type}', 0, '{status}')
"""
RECORD_INSERT = """
    INSERT INTO license_record
        (license_type, mgmt_no, jurisdiction_code, name, status, status_raw,
         opened_on, closed_on, floor_source, parse_version)
    VALUES ('{license_type}', 'TEST-0001', '0000000', '가상 예시 업소', '{status}', '가상',
            {opened_on}, {closed_on}, {floor_source}, '2026.10.1')
"""
BASE_RATE_INSERT = """
    INSERT INTO base_rate
        (snapshot_label, method_version, scope_code, prior_bucket, n, events,
         rate, ci_low, ci_high, cohort_from, cohort_to)
    VALUES ('2026-10', '2026.10.1', '11', '{prior_bucket}', 10, 1,
            0.1000, 0.0100, 0.4000, DATE '2005-01-01', DATE '2020-12-31')
"""
CORRECTION_INSERT = """
    INSERT INTO correction_request (pnu, kind, message, status)
    VALUES ('0000000000000000000', '{kind}', repeat('가', {length}), '{status}')
"""

VALID: dict[str, dict[str, Any]] = {
    "snapshot": {
        "source": "license_file",
        "license_type": "general_restaurant",
        "status": "loaded",
    },
    "record": {
        "license_type": "bakery",
        "status": "closed",
        "opened_on": "DATE '2020-01-01'",
        "closed_on": "DATE '2021-01-01'",
        "floor_source": "'jibun_tail'",
    },
    "base_rate": {"prior_bucket": "4+"},
    "correction": {"kind": "wrong_info", "length": 1000, "status": "open"},
}
TEMPLATES = {
    "snapshot": SNAPSHOT_INSERT,
    "record": RECORD_INSERT,
    "base_rate": BASE_RATE_INSERT,
    "correction": CORRECTION_INSERT,
}


def _insert(template: str, /, **overrides: Any) -> str:
    return TEMPLATES[template].format(**{**VALID[template], **overrides})


@pytest.mark.parametrize("template", sorted(TEMPLATES))
def test_valid_insert_succeeds(migrated_db_url: str, template: str) -> None:
    """아래 위반 테스트가 CHECK가 아닌 다른 이유로 실패하는 것이 아님을 보인다."""
    asyncio.run(_run_in_rollback(migrated_db_url, [_insert(template)]))


@pytest.mark.parametrize(
    ("template", "overrides"),
    [
        ("snapshot", {"source": "manual"}),
        ("snapshot", {"license_type": "pub"}),
        ("snapshot", {"status": "done"}),
        ("record", {"license_type": "pub"}),
        ("record", {"status": "unknown"}),
        ("record", {"floor_source": "'guess'"}),
        ("record", {"opened_on": "DATE '2021-01-02'"}),  # closed_on < opened_on
        ("base_rate", {"prior_bucket": "5"}),
        ("correction", {"kind": "spam"}),
        ("correction", {"length": 1001}),
        ("correction", {"status": "closed"}),
    ],
    ids=lambda value: (
        value if isinstance(value, str) else ",".join(f"{k}={v}" for k, v in value.items())
    ),
)
def test_check_violation_insert_fails(
    migrated_db_url: str, template: str, overrides: dict[str, Any]
) -> None:
    with pytest.raises(IntegrityError) as excinfo:
        asyncio.run(_run_in_rollback(migrated_db_url, [_insert(template, **overrides)]))
    assert getattr(excinfo.value.orig, "sqlstate", None) == CHECK_VIOLATION


def test_null_dates_pass_date_order_check(migrated_db_url: str) -> None:
    """개업일·폐업일을 모르면 NULL로 두고(ADR-003), 날짜 순서 CHECK는 통과한다."""
    statements = [
        _insert("record", opened_on="NULL", closed_on="DATE '2021-01-01'"),
        _insert("record", opened_on="DATE '2020-01-01'", closed_on="NULL").replace(
            "TEST-0001", "TEST-0002"
        ),
    ]
    asyncio.run(_run_in_rollback(migrated_db_url, statements))
