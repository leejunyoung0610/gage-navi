"""DB 엔진 (SQLAlchemy 2 async + asyncpg)."""

import asyncio
from datetime import datetime
from functools import lru_cache
from zoneinfo import ZoneInfo

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

from app.core.config import get_settings

PING_TIMEOUT_SECONDS = 3.0
DISPLAY_TZ = ZoneInfo("Asia/Seoul")

# 정규화까지 통과한 종류별 최신 스냅샷의 데이터 기준 시각 중 가장 이른 값 (docs/30 §2)
_LOCATION_SNAPSHOT = """
SELECT min(source_updated_max) FROM (
  SELECT DISTINCT ON (license_type) source_updated_max
  FROM data_snapshot WHERE status = 'validated'
  ORDER BY license_type, id DESC
) latest
"""


class DatabaseNotConfiguredError(RuntimeError):
    pass


@lru_cache(maxsize=1)
def get_engine() -> AsyncEngine:
    url = get_settings().database_url
    if url is None:
        raise DatabaseNotConfiguredError("DATABASE_URL이 설정되지 않았습니다")
    # 오류 메시지에 SQL 인자(정정 요청 메시지 등)를 넣지 않는다 (docs/30 §1 `INTERNAL`)
    return create_async_engine(url, pool_pre_ping=True, hide_parameters=True)


async def ping_db() -> None:
    """DB에 `SELECT 1`을 보낸다. 실패하거나 제한 시간을 넘기면 예외."""
    async with asyncio.timeout(PING_TIMEOUT_SECONDS):
        async with get_engine().connect() as conn:
            await conn.execute(text("SELECT 1"))


async def location_snapshot_label() -> str | None:
    """`validated` 스냅샷의 데이터 기준 연-월(`YYYY-MM`, Asia/Seoul). 없으면 `None`."""
    async with asyncio.timeout(PING_TIMEOUT_SECONDS):
        async with get_engine().connect() as conn:
            earliest: datetime | None = (await conn.execute(text(_LOCATION_SNAPSHOT))).scalar()
    return None if earliest is None else earliest.astimezone(DISPLAY_TZ).strftime("%Y-%m")


async def existing_parcels(pnus: list[str]) -> set[str]:
    """`pnus` 중 `parcel` 테이블에 있는 것 (주소 검색 `has_history`, docs/30 §2)."""
    if not pnus:
        return set()
    async with asyncio.timeout(PING_TIMEOUT_SECONDS):
        async with get_engine().connect() as conn:
            rows = await conn.execute(
                text("SELECT pnu FROM parcel WHERE pnu = ANY(:pnus)"), {"pnus": pnus}
            )
            return {str(row[0]) for row in rows}


async def legal_dong_rows(names: list[str]) -> list[tuple[str, str, bool]]:
    """`full_name`이 `names` 중 하나인 `legal_dong` 행 `(code, full_name, abolished)`."""
    if not names:
        return []
    async with asyncio.timeout(PING_TIMEOUT_SECONDS):
        async with get_engine().connect() as conn:
            rows = await conn.execute(
                text(
                    "SELECT code, full_name, abolished FROM legal_dong "
                    "WHERE full_name = ANY(:names)"
                ),
                {"names": names},
            )
            return [(str(code), str(name), bool(abolished)) for code, name, abolished in rows]
