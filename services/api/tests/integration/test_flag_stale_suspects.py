"""미갱신 의심 표시 잡과 마이그레이션 0004 (T-017). 업소·필지는 모두 가상 예시다."""

import asyncio
from collections.abc import Awaitable, Callable
from datetime import date
from typing import Any

import pytest
from alembic.config import Config
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine
from sqlalchemy.pool import NullPool

from alembic import command
from jobs.flag_stale_suspects import Summary, flag, render_report

PNU = "1121510700100010001"
INSERT = """
INSERT INTO license_record
  (license_type, mgmt_no, jurisdiction_code, name, status, status_raw, opened_on, area_m2,
   pnu, floor, ho_list, no_fixed_place, parse_version)
VALUES ('{kind}', '{mgmt}', '3040000', '{name}', '{status}', '{status}', '{opened}', {area},
        '{pnu}', '{floor}', '{{{ho}}}', {mobile}, '2026.10.1')
"""
# (종류, 관리번호, 이름, 상태, 개업일, 면적, 층, 호, 고정된 자리 없음)
RECORDS = [
    ("general_restaurant", "A1", "가상분식", "open", "2010-01-01", "30.00", "1", "101", False),
    ("general_restaurant", "A2", "가상카페", "open", "2015-01-01", "80.00", "1", "101", False),
    ("rest_restaurant", "B1", "가상국밥", "open", "2010-01-01", "100.00", "2", "201", False),
    ("rest_restaurant", "B2", "가상치킨", "closed", "2015-01-01", "100.50", "2", "202", False),
    ("rest_restaurant", "C1", "가상제과(Gasang)", "open", "2020-01-01", "50.00", "3", "301", False),
    ("bakery", "C2", "가상제과", "open", "2021-01-01", "50.00", "3", "301", False),
    ("general_restaurant", "D1", "가상김밥", "open", "2010-01-01", "NULL", "4", "401", False),
    ("general_restaurant", "D2", "가상트럭", "open", "2015-01-01", "NULL", "4", "401", True),
]


def with_engine(url: str, work: Callable[[AsyncEngine], Awaitable[Any]]) -> Any:
    async def run() -> Any:
        engine = create_async_engine(url, poolclass=NullPool)
        try:
            return await work(engine)
        finally:
            await engine.dispose()

    return asyncio.run(run())


def execute(url: str, *statements: str) -> None:
    async def work(engine: AsyncEngine) -> None:
        async with engine.begin() as conn:
            for statement in statements:
                await conn.execute(text(statement))

    with_engine(url, work)


def flags(url: str) -> dict[str, tuple[bool, bool]]:
    async def work(engine: AsyncEngine) -> list[Any]:
        async with engine.connect() as conn:
            query = "SELECT mgmt_no, stale_suspect, stale_area_match FROM license_record"
            return list((await conn.execute(text(query))).all())

    return {row[0]: (row[1], row[2]) for row in with_engine(url, work)}


@pytest.fixture
def seeded(migrated_db_url: str) -> str:
    statements = ["TRUNCATE license_record CASCADE"]
    for kind, mgmt, name, status, opened, area, floor, ho, mobile in RECORDS:
        statements.append(
            INSERT.format(
                kind=kind, mgmt=mgmt, name=name, status=status, opened=opened, area=area,
                pnu=PNU, floor=floor, ho=ho, mobile=str(mobile).lower(),
            )
        )  # fmt: skip
    execute(migrated_db_url, *statements)
    return migrated_db_url


def test_flags_are_written_by_basis(seeded: str) -> None:
    summary: Summary = with_engine(seeded, flag)
    stored = flags(seeded)
    assert stored.pop("A1") == (True, False)  # 같은 호
    assert stored.pop("B1") == (False, True)  # 같은 면적만
    assert set(stored.values()) == {(False, False)}  # 같은 가게 쌍(C), 고정된 자리 없음(D) 등
    assert (summary.same_ho, summary.same_area, summary.area_only, summary.both) == (1, 1, 1, 0)
    result = summary.result
    assert (result.candidates, result.ho_pairs, result.ho_pairs_same_name) == (6, 2, 1)
    assert (result.area_pairs, result.area_pairs_same_name) == (2, 1)
    assert summary.by_license["general_restaurant"] == (4, 1, 0)
    assert summary.by_license["rest_restaurant"] == (2, 0, 1)

    report = render_report(summary, date(2026, 10, 13))
    assert "| 같은 호 | `stale_suspect` | **1** | 16.67% | 화면 배지, 민감도 분석 |" in report
    assert "| 면적만 같음 (화면에 내지 않는다) | 1 |" in report
    assert "| 같은 호 | 2 | 1 | 2 | 1 | 1 |" in report
    assert "가상" not in report  # 업소 이름은 리포트에 넣지 않는다


def test_rerun_is_the_same_and_stale_flags_are_cleared(seeded: str) -> None:
    with_engine(seeded, flag)
    first = flags(seeded)
    with_engine(seeded, flag)
    assert flags(seeded) == first

    # 뒤에 연 가게가 사라지면(예: 정정으로 호가 바뀜) 표시도 지워진다
    execute(
        seeded,
        "UPDATE license_record SET ho_list = '{999}' WHERE mgmt_no = 'A2'",
        "UPDATE license_record SET stale_area_match = true WHERE mgmt_no = 'D1'",  # 잘못 남은 값
    )
    with_engine(seeded, flag)
    cleared = flags(seeded)
    assert cleared["A1"] == (False, False) and cleared["D1"] == (False, False)
    assert cleared["B1"] == (False, True)


def test_migration_0004_roundtrip(
    empty_db_url: str, make_alembic_config: Callable[[str], Config]
) -> None:
    config = make_alembic_config(empty_db_url)
    query = (
        "SELECT column_default, is_nullable FROM information_schema.columns "
        "WHERE table_name = 'license_record' AND column_name = 'stale_area_match'"
    )

    def column() -> list[Any]:
        async def work(engine: AsyncEngine) -> list[Any]:
            async with engine.connect() as conn:
                return [tuple(row) for row in await conn.execute(text(query))]

        result: list[Any] = with_engine(empty_db_url, work)
        return result

    command.upgrade(config, "head")
    assert column() == [("false", "NO")]
    command.downgrade(config, "0003_normalize")
    assert column() == []
    command.upgrade(config, "head")
    assert column() == [("false", "NO")]
