"""주소 검색 `has_history`·`related_with_history`: `parcel`의 필지와 `jibun_label`.

T-021·T-033. 필지는 가상 예시다.
"""

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


def test_parcel_labels(migrated_db_url: str, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DATABASE_URL", migrated_db_url)
    db.get_engine.cache_clear()

    async def run() -> tuple[dict[str, str], dict[str, str], dict[str, str]]:
        try:
            await _seed(migrated_db_url)
            return (
                await db.parcel_labels([P1, MISSING, P2]),
                await db.parcel_labels([MISSING]),
                await db.parcel_labels([]),
            )
        finally:
            await db.get_engine().dispose()

    try:
        assert asyncio.run(run()) == ({P1: "가상동 1", P2: "가상동 1"}, {}, {})
    finally:
        db.get_engine.cache_clear()
