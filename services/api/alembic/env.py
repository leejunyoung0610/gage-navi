"""Alembic 환경 (async, asyncpg).

스키마 정본은 docs/04-data-model.md의 DDL이다. 마이그레이션은 그 DDL을 직접 실행하므로
autogenerate용 메타데이터는 두지 않는다.
"""

import asyncio
from logging.config import fileConfig

from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.pool import NullPool

from alembic import context
from app.core.config import get_settings

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name, disable_existing_loggers=False)


def get_url() -> str:
    """`sqlalchemy.url` 옵션(테스트가 지정)이 있으면 그것을, 없으면 DATABASE_URL을 쓴다."""
    url = config.get_main_option("sqlalchemy.url") or get_settings().database_url
    if not url:
        raise RuntimeError("DATABASE_URL이 설정되지 않았습니다")
    return url


def run_migrations_offline() -> None:
    context.configure(url=get_url(), target_metadata=None, literal_binds=True)
    with context.begin_transaction():
        context.run_migrations()


def do_run_migrations(connection: Connection) -> None:
    context.configure(connection=connection, target_metadata=None)
    with context.begin_transaction():
        context.run_migrations()


async def run_migrations_online() -> None:
    engine = create_async_engine(get_url(), poolclass=NullPool)
    async with engine.connect() as connection:
        await connection.run_sync(do_run_migrations)
    await engine.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    asyncio.run(run_migrations_online())
