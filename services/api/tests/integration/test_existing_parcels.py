"""주소 검색 `has_history`: `parcel` 테이블에 있는 필지만 고른다 (T-021). 필지는 가상 예시다."""

import asyncio

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.pool import NullPool

from app.core import db

P1 = "1121510700100470001"
P2 = "1121510700200210000"
MISSING = "1121510700100480000"


async def _seed(url: str) -> None:
    engine = create_async_engine(url, poolclass=NullPool)
    try:
        async with engine.begin() as conn:
            await conn.execute(
                text(
                    "INSERT INTO legal_dong (code, sido, sigungu, eupmyeondong, full_name) VALUES "
                    "('1121510700', '가상시', '가상구', '가상동', '가상시 가상구 가상동')"
                )
            )
            for pnu in (P1, P2):
                await conn.execute(
                    text(
                        "INSERT INTO parcel (pnu, legal_dong_code, jibun_label, floors, "
                        "record_count) VALUES (:pnu, '1121510700', '가상동 1', '{}', 1)"
                    ),
                    {"pnu": pnu},
                )
    finally:
        await engine.dispose()


def test_existing_parcels(migrated_db_url: str, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DATABASE_URL", migrated_db_url)
    db.get_engine.cache_clear()

    async def run() -> tuple[set[str], set[str], set[str]]:
        try:
            await _seed(migrated_db_url)
            return (
                await db.existing_parcels([P1, MISSING, P2]),
                await db.existing_parcels([MISSING]),
                await db.existing_parcels([]),
            )
        finally:
            await db.get_engine().dispose()

    try:
        assert asyncio.run(run()) == ({P1, P2}, set(), set())
    finally:
        db.get_engine.cache_clear()
