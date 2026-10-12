"""층 이력 빌드 잡과 마이그레이션 0005 (T-018). 필지·업소·날짜는 모두 가상 예시다."""

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
from app.location.history.job import HistoryBuildError, HistoryResult, build_history

P1 = "1121510700100470001"
P2 = "1121510700200210000"
INSERT = """
INSERT INTO license_record
  (license_type, mgmt_no, jurisdiction_code, name, biz_category, status, status_raw, opened_on,
   closed_on, road_addr, pnu, floor, geom, bulk_closure, no_fixed_place, parse_version)
VALUES ('rest_restaurant', '{mgmt}', '3040000', '가상업소 {mgmt}', '{category}', '{status}',
        '{status}', '{opened}', {closed}, {road}, '{pnu}', {floor}, {geom}, {bulk}, {mobile},
        '2026.10.1')
"""
POINT = "ST_GeomFromEWKT('SRID=4326;POINT(127.07 37.54)')"
ROAD = "서울특별시 광진구 가상로"
# (관리번호, 업태, 개업일, 폐업일, 층, 급증일 폐업, 고정된 자리 없음, 도로명주소, 좌표, 필지)
RECORDS: list[tuple[str, str, str, str | None, str | None, bool, bool, str | None, bool, str]] = [
    ("A1", "한식", "2006-01-01", "2010-06-30", "1", False, False, f"{ROAD} 1, 1층", True, P1),
    ("A2", "한식", "2008-01-01", "2012-03-31", "1", True, False, None, False, P1),
    ("A3", "편의점", "2012-04-01", None, "1", False, False, f"{ROAD} 1-1, 1층 101호", False, P1),
    ("A4", "푸드트럭", "2013-01-01", None, "1", False, True, f"{ROAD} 9", False, P1),
    ("A5", "한식", "2014-01-01", None, "B1", False, False, None, False, P1),
    ("A6", "한식", "2015-01-01", None, None, False, False, None, False, P1),
    ("B1", "한식", "2016-01-01", None, None, False, False, None, False, P2),
]  # fmt: skip


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


def fetch_all(url: str, sql: str) -> list[tuple[Any, ...]]:
    async def work(engine: AsyncEngine) -> list[tuple[Any, ...]]:
        async with engine.connect() as conn:
            return [tuple(row) for row in await conn.execute(text(sql))]

    result: list[tuple[Any, ...]] = with_engine(url, work)
    return result


def build(url: str, as_of: date | None = None) -> HistoryResult:
    result: HistoryResult = with_engine(url, lambda engine: build_history(engine, as_of))
    return result


def quote(value: str | None) -> str:
    return "NULL" if value is None else f"'{value}'"


@pytest.fixture
def seeded(migrated_db_url: str) -> str:
    statements = [
        "TRUNCATE license_record, floor_summary, parcel, data_snapshot, legal_dong CASCADE",
        "INSERT INTO legal_dong (code, sido, sigungu, eupmyeondong, full_name) "
        "VALUES ('1121510700', '서울특별시', '광진구', '화양동', '서울특별시 광진구 화양동')",
        "INSERT INTO data_snapshot (source, license_type, row_count, status, source_updated_max) "
        "VALUES ('license_file', 'rest_restaurant', 7, 'validated', '2026-10-07 22:47:53+09')",
    ]
    for mgmt, category, opened, closed, floor, bulk, mobile, road, geom, pnu in RECORDS:
        statements.append(
            INSERT.format(
                mgmt=mgmt, category=category, status="closed" if closed else "open", opened=opened,
                closed=quote(closed), road=quote(road), pnu=pnu, floor=quote(floor),
                geom=POINT if geom else "NULL", bulk=str(bulk).lower(), mobile=str(mobile).lower(),
            )
        )  # fmt: skip
    execute(migrated_db_url, *statements)
    return migrated_db_url


PRIORS = (
    "SELECT r.mgmt_no, p.prior_closures_floor, p.prior_closures_floor_ex_surge, p.method_version "
    "FROM record_prior p JOIN license_record r ON r.id = p.record_id ORDER BY 1"
)
FLOORS = (
    "SELECT floor, record_count, records_since_2005, open_now_count, median_closed_tenure_days, "
    "has_concurrent, method_version FROM floor_summary ORDER BY floor"
)
PARCELS = (
    "SELECT pnu, legal_dong_code, jibun_label, road_addr, ST_AsText(geom), floors, record_count "
    "FROM parcel ORDER BY pnu"
)


def test_build_writes_parcels_floors_and_priors(seeded: str) -> None:
    result = build(seeded)
    assert result.as_of == date(2026, 10, 7)  # 스냅샷의 데이터 기준일
    assert (result.records, result.parcels, result.floors, result.priors) == (7, 2, 2, 4)
    assert (result.floors_with_concurrent, result.priors_changed_by_surge) == (1, 1)

    assert fetch_all(seeded, PARCELS) == [
        (P1, "1121510700", "서울특별시 광진구 화양동 47-1", "서울특별시 광진구 가상로 1-1",
         "POINT(127.07 37.54)", ["B1", "1"], 5),
        (P2, "1121510700", "서울특별시 광진구 화양동 산 21", None, None, [], 1),
    ]  # fmt: skip
    assert fetch_all(seeded, FLOORS) == [
        # 1층: A1·A2·A3 (푸드트럭 A4는 빠진다).
        # 폐업 영업기간 중앙값은 급증일 폐업 A2를 뺀 A1의 1,641일
        ("1", 3, 3, 1, 1641, True, "2026.10.1"),
        ("B1", 1, 1, 1, None, False, "2026.10.1"),
    ]
    assert fetch_all(seeded, PRIORS) == [
        ("A1", 0, 0, "2026.10.1"),
        ("A2", 0, 0, "2026.10.1"),
        ("A3", 2, 1, "2026.10.1"),  # 편의점도 이력·통계 집합에 있다. A2는 급증일 폐업
        ("A5", 0, 0, "2026.10.1"),
    ]
    store = fetch_all(seeded, "SELECT biz_category FROM license_record WHERE mgmt_no = 'A3'")
    assert store == [("편의점",)]


def test_rebuild_is_the_same_and_follows_suppression(seeded: str) -> None:
    build(seeded)
    first = (fetch_all(seeded, PARCELS), fetch_all(seeded, FLOORS), fetch_all(seeded, PRIORS))
    build(seeded)
    assert (
        fetch_all(seeded, PARCELS),
        fetch_all(seeded, FLOORS),
        fetch_all(seeded, PRIORS),
    ) == first

    # 정정 요청으로 숨긴 기록은 이력 요약에서 빠지고, 통계용 과거 폐업 횟수는 그대로다
    execute(
        seeded,
        "INSERT INTO record_suppression (record_id, reason) "
        "SELECT id, '가상 사유' FROM license_record WHERE mgmt_no = 'A5'",
    )
    build(seeded)
    assert [row[0] for row in fetch_all(seeded, FLOORS)] == ["1"]
    assert fetch_all(seeded, PARCELS)[0][5:] == (["1"], 4)
    assert fetch_all(seeded, PRIORS) == first[2]


def test_as_of_argument_changes_open_spans(seeded: str) -> None:
    # 기준일을 A3 개업 30일 뒤로 주면 영업 중인 A3과 겹치는 기록이 없다 (A1·A2의 겹침만 남는다)
    execute(seeded, "UPDATE license_record SET closed_on = '2008-01-20' WHERE mgmt_no = 'A1'")
    result = build(seeded, date(2012, 5, 1))
    assert result.as_of == date(2012, 5, 1) and result.floors_with_concurrent == 0


def test_needs_a_validated_snapshot_for_the_default_as_of(seeded: str) -> None:
    execute(seeded, "UPDATE data_snapshot SET status = 'loaded'")
    with pytest.raises(HistoryBuildError, match="기준일"):
        build(seeded)
    assert build(seeded, date(2026, 10, 7)).parcels == 2


def test_migration_0005_roundtrip(
    empty_db_url: str, make_alembic_config: Callable[[str], Config]
) -> None:
    config = make_alembic_config(empty_db_url)
    query = (
        "SELECT is_nullable, column_default FROM information_schema.columns "
        "WHERE table_name = 'record_prior' AND column_name = 'prior_closures_floor_ex_surge'"
    )
    command.upgrade(config, "head")
    assert fetch_all(empty_db_url, query) == [("NO", None)]
    command.downgrade(config, "0004_stale_area")
    assert fetch_all(empty_db_url, query) == []
    command.upgrade(config, "head")
    assert fetch_all(empty_db_url, query) == [("NO", None)]
