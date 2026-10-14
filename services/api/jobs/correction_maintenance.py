"""정정 요청 정리 (docs/30 §3, docs/60 §5, T-023). 매일 1회 (docs/03 §5).

    python -m jobs.correction_maintenance

1. 처리 후 1년이 지난 요청의 `message`를 지운다(행과 처리 결과는 남긴다)
2. 숨김 처리했지만 웹 재생성이 아직 성공하지 않은 요청에 재생성을 다시 요청한다

출력에는 건수만 쓴다(메시지 내용은 쓰지 않는다).
"""

import argparse
import asyncio
import json
from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy.ext.asyncio import AsyncEngine

from app.admin.revalidate import revalidate
from app.core.db import get_engine
from app.location.corrections import store


@dataclass(frozen=True)
class MaintenanceResult:
    messages_purged: int
    revalidation_pending: int
    revalidated: int


async def maintain(engine: AsyncEngine, now: datetime) -> MaintenanceResult:
    async with engine.begin() as conn:
        purged = await store.purge_messages(conn, now)
        pending = await store.pending_revalidations(conn)
    done = 0
    for correction_id, paths in pending:
        if await revalidate(paths, correction_id):
            async with engine.begin() as conn:
                await store.mark_revalidated(conn, correction_id, datetime.now(UTC))
            done += 1
    return MaintenanceResult(purged, len(pending), done)


async def run() -> MaintenanceResult:
    engine = get_engine()
    try:
        return await maintain(engine, datetime.now(UTC))
    finally:
        await engine.dispose()


def main(argv: list[str] | None = None) -> int:
    argparse.ArgumentParser(
        prog="jobs.correction_maintenance",
        description="정정 요청 메시지 삭제(처리 후 1년)·웹 재생성 재시도",
    ).parse_args(argv)
    result = asyncio.run(run())
    print(
        json.dumps(
            {
                "job": "correction_maintenance",
                "messages_purged": result.messages_purged,
                "revalidation_pending": result.revalidation_pending,
                "revalidated": result.revalidated,
            },
            ensure_ascii=False,
        )
    )
    return 0 if result.revalidated == result.revalidation_pending else 1


if __name__ == "__main__":
    raise SystemExit(main())
