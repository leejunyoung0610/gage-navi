"""통합 테스트용 임시 데이터베이스.

`TEST_DATABASE_URL`(없으면 `DATABASE_URL`)이 가리키는 PostgreSQL 서버에 테스트마다 쓰고 버리는
데이터베이스를 만든다. 개발용 데이터베이스의 테이블은 건드리지 않는다.
로컬에서는 `docker compose up -d db` 후 `make test`.
"""

import asyncio
import os
import uuid
from collections.abc import Callable, Iterator
from pathlib import Path

import pytest
from alembic.config import Config
from sqlalchemy import make_url, text
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.pool import NullPool

from alembic import command

API_ROOT = Path(__file__).resolve().parents[2]


def _server_url() -> str:
    url = os.environ.get("TEST_DATABASE_URL") or os.environ.get("DATABASE_URL")
    if not url:
        pytest.fail(
            "통합 테스트에는 PostgreSQL(PostGIS)이 필요합니다. "
            "TEST_DATABASE_URL 또는 DATABASE_URL을 설정하세요 "
            "(로컬: docker compose up -d db 후 make test)."
        )
    return url


async def _admin_execute(statement: str) -> None:
    engine = create_async_engine(_server_url(), poolclass=NullPool, isolation_level="AUTOCOMMIT")
    try:
        async with engine.connect() as conn:
            await conn.execute(text(statement))
    finally:
        await engine.dispose()


def _temp_database() -> Iterator[str]:
    name = f"gagenavi_test_{uuid.uuid4().hex[:12]}"
    asyncio.run(_admin_execute(f'CREATE DATABASE "{name}"'))
    try:
        yield make_url(_server_url()).set(database=name).render_as_string(hide_password=False)
    finally:
        asyncio.run(_admin_execute(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)'))


def alembic_config(database_url: str) -> Config:
    config = Config(str(API_ROOT / "alembic.ini"))
    config.set_main_option("sqlalchemy.url", database_url.replace("%", "%%"))
    return config


@pytest.fixture(scope="session")
def make_alembic_config() -> Callable[[str], Config]:
    return alembic_config


@pytest.fixture
def empty_db_url() -> Iterator[str]:
    """마이그레이션을 적용하지 않은 빈 임시 데이터베이스."""
    yield from _temp_database()


@pytest.fixture(scope="module")
def migrated_db_url() -> Iterator[str]:
    """`upgrade head`까지 적용한 임시 데이터베이스 (모듈당 1개)."""
    for url in _temp_database():
        command.upgrade(alembic_config(url), "head")
        yield url
