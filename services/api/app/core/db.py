"""DB 엔진 (SQLAlchemy 2 async + asyncpg)."""

import asyncio
from functools import lru_cache

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

from app.core.config import get_settings

PING_TIMEOUT_SECONDS = 3.0


class DatabaseNotConfiguredError(RuntimeError):
    pass


@lru_cache(maxsize=1)
def get_engine() -> AsyncEngine:
    url = get_settings().database_url
    if url is None:
        raise DatabaseNotConfiguredError("DATABASE_URL이 설정되지 않았습니다")
    return create_async_engine(url, pool_pre_ping=True)


async def ping_db() -> None:
    """DB에 `SELECT 1`을 보낸다. 실패하거나 제한 시간을 넘기면 예외."""
    async with asyncio.timeout(PING_TIMEOUT_SECONDS):
        async with get_engine().connect() as conn:
            await conn.execute(text("SELECT 1"))
