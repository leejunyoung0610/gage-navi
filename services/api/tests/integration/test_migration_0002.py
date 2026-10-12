"""마이그레이션 0002_rules: 왕복, 승인 규칙 1개 인덱스, review_log CHECK (docs/04 §3)."""

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

RULES_TABLES = {
    "source_site",
    "announcement",
    "document",
    "program",
    "extraction",
    "extraction_item",
    "rule",
    "evidence",
    "change_event",
    "review_log",
    "rate_base",
    "eval_case",
    "eval_run",
    "admin_user",
}
UNIQUE_VIOLATION = "23505"
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
PUBLIC_TABLES_QUERY = """
    SELECT table_name FROM information_schema.tables
    WHERE table_schema = 'public' AND table_type = 'BASE TABLE' AND table_name = ANY(:tables)
"""


async def _fetch_all(
    url: str, queries: dict[str, str], tables: set[str]
) -> dict[str, list[tuple[Any, ...]]]:
    engine = create_async_engine(url, poolclass=NullPool)
    try:
        async with engine.connect() as conn:
            params = {"tables": sorted(tables)}
            return {
                key: [tuple(row) for row in await conn.execute(text(sql), params)]
                for key, sql in queries.items()
            }
    finally:
        await engine.dispose()


def _schema(url: str) -> dict[str, list[tuple[Any, ...]]]:
    return asyncio.run(_fetch_all(url, SCHEMA_QUERIES, RULES_TABLES))


def _existing(url: str, tables: set[str]) -> set[str]:
    rows = asyncio.run(_fetch_all(url, {"tables": PUBLIC_TABLES_QUERY}, tables))["tables"]
    return {row[0] for row in rows}


def test_upgrade_downgrade_upgrade_roundtrip(
    empty_db_url: str, make_alembic_config: Callable[[str], Config]
) -> None:
    config = make_alembic_config(empty_db_url)

    command.upgrade(config, "0002_rules")
    first = _schema(empty_db_url)
    assert {row[0] for row in first["columns"]} == RULES_TABLES
    assert ("rule", "rule_one_approved") in {(row[0], row[1]) for row in first["indexes"]}

    command.downgrade(config, "0001_location")
    assert _existing(empty_db_url, RULES_TABLES) == set()
    # 0002를 내려도 0001의 테이블은 남는다
    assert _existing(empty_db_url, {"data_snapshot", "license_record"}) == {
        "data_snapshot",
        "license_record",
    }

    command.upgrade(config, "0002_rules")
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


# 아래는 전부 테스트용 가상 예시 값이다 (실제 지원사업·공고·규칙·URL이 아니다).
PROGRAM_INSERT = """
    INSERT INTO program (id, module, name, agency, level)
    VALUES ('{id}', 'funding', '가상 예시 사업', '가상 예시 기관', 'national')
"""
RULE_INSERT = """
    INSERT INTO rule (id, program_id, version, dsl_version, body, status, approved_by, approved_at)
    VALUES ({id}, '{program_id}', {version}, '가상', '{{}}'::jsonb, '{status}',
            {approved_by}, {approved_at})
"""
# review_log가 참조하는 extraction_item(id=1)과 rule(id=1)까지의 사슬
REVIEW_SETUP = [
    PROGRAM_INSERT.format(id="example.virtual_a"),
    """
    INSERT INTO source_site (id, name, kind, url)
    VALUES (1, '가상 예시 사이트', 'page', 'https://example.invalid/')
    """,
    """
    INSERT INTO announcement (id, source_site_id, external_id, title, url, content_hash)
    VALUES (1, 1, 'VIRTUAL-1', '가상 예시 공고', 'https://example.invalid/1', 'virtual-hash')
    """,
    """
    INSERT INTO extraction (id, announcement_id, model, prompt_version, dsl_version)
    VALUES (1, 1, '가상', '가상', '가상')
    """,
    """
    INSERT INTO extraction_item (id, extraction_id, proposed_program_key, output)
    VALUES (1, 1, 'example.virtual_a', '{}'::jsonb)
    """,
    RULE_INSERT.format(
        id=1,
        program_id="example.virtual_a",
        version=1,
        status="draft",
        approved_by="NULL",
        approved_at="NULL",
    ),
]
REVIEW_INSERT = """
    INSERT INTO review_log
        (review_kind, extraction_item_id, rule_id, field_path, reviewer, seconds_spent)
    VALUES ('{review_kind}', {extraction_item_id}, {rule_id}, {field_path}, '가상 검수자', 1)
"""


def _rule(rule_id: int, version: int, status: str, program_id: str = "example.virtual_a") -> str:
    approved = status == "approved"
    return RULE_INSERT.format(
        id=rule_id,
        program_id=program_id,
        version=version,
        status=status,
        approved_by="'가상 검수자'" if approved else "NULL",
        approved_at="now()" if approved else "NULL",
    )


def _review(**values: str) -> str:
    defaults = {"extraction_item_id": "NULL", "rule_id": "NULL", "field_path": "NULL"}
    return REVIEW_INSERT.format(**{**defaults, **values})


def _sqlstate(excinfo: pytest.ExceptionInfo[IntegrityError]) -> str | None:
    return getattr(excinfo.value.orig, "sqlstate", None)


def test_second_approved_rule_for_same_program_fails(migrated_db_url: str) -> None:
    statements = [
        PROGRAM_INSERT.format(id="example.virtual_a"),
        _rule(1, 1, "approved"),
        _rule(2, 2, "approved"),
    ]
    with pytest.raises(IntegrityError) as excinfo:
        asyncio.run(_run_in_rollback(migrated_db_url, statements))
    assert _sqlstate(excinfo) == UNIQUE_VIOLATION
    assert "rule_one_approved" in str(excinfo.value)


def test_one_approved_rule_per_program_allows_other_statuses(migrated_db_url: str) -> None:
    """위 실패가 인덱스 조건(같은 프로그램 + approved) 때문임을 보인다."""
    statements = [
        PROGRAM_INSERT.format(id="example.virtual_a"),
        PROGRAM_INSERT.format(id="example.virtual_b"),
        _rule(1, 1, "retired"),
        _rule(2, 2, "retired"),
        _rule(3, 3, "approved"),
        _rule(4, 4, "draft"),
        _rule(5, 1, "approved", program_id="example.virtual_b"),
    ]
    asyncio.run(_run_in_rollback(migrated_db_url, statements))


def test_approved_rule_without_approver_fails(migrated_db_url: str) -> None:
    statements = [
        PROGRAM_INSERT.format(id="example.virtual_a"),
        RULE_INSERT.format(
            id=1,
            program_id="example.virtual_a",
            version=1,
            status="approved",
            approved_by="NULL",
            approved_at="now()",
        ),
    ]
    with pytest.raises(IntegrityError) as excinfo:
        asyncio.run(_run_in_rollback(migrated_db_url, statements))
    assert _sqlstate(excinfo) == CHECK_VIOLATION


@pytest.mark.parametrize(
    "values",
    [
        {"review_kind": "field_edit", "extraction_item_id": "1", "field_path": "'/benefit'"},
        {"review_kind": "approve", "extraction_item_id": "1"},
        {"review_kind": "reject", "extraction_item_id": "1"},
        {"review_kind": "second_review", "rule_id": "1"},
    ],
    ids=lambda values: values["review_kind"],
)
def test_valid_review_log_insert_succeeds(migrated_db_url: str, values: dict[str, str]) -> None:
    """아래 위반 테스트가 CHECK가 아닌 다른 이유로 실패하는 것이 아님을 보인다."""
    asyncio.run(_run_in_rollback(migrated_db_url, [*REVIEW_SETUP, _review(**values)]))


@pytest.mark.parametrize(
    "values",
    [
        {"review_kind": "field_edit", "extraction_item_id": "1"},  # field_path 없음
        {"review_kind": "field_edit", "field_path": "'/benefit'"},  # extraction_item_id 없음
        {"review_kind": "second_review", "extraction_item_id": "1"},  # rule_id 없음
        {"review_kind": "comment", "extraction_item_id": "1"},  # 허용되지 않은 종류
    ],
    ids=[
        "field_edit-no-field_path",
        "field_edit-no-extraction_item",
        "second_review-no-rule_id",
        "unknown-kind",
    ],
)
def test_review_log_check_violation_fails(migrated_db_url: str, values: dict[str, str]) -> None:
    with pytest.raises(IntegrityError) as excinfo:
        asyncio.run(_run_in_rollback(migrated_db_url, [*REVIEW_SETUP, _review(**values)]))
    assert _sqlstate(excinfo) == CHECK_VIOLATION
