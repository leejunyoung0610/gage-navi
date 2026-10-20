"""`measure_daily_count` 읽기·쓰기 (docs/04 §2). 이벤트 한 건씩 저장하지 않고 합계만 둔다."""

from datetime import date

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from app.measure.events import Event

_INCREMENT = """
INSERT INTO measure_daily_count (day, event, count) VALUES (:day, :event, 1)
ON CONFLICT (day, event) DO UPDATE SET count = measure_daily_count.count + 1
"""
_RANGE = """
SELECT day, event, count FROM measure_daily_count
WHERE day >= :start AND day <= :end ORDER BY day, event
"""


async def increment(conn: AsyncConnection, day: date, event: Event) -> None:
    await conn.execute(text(_INCREMENT), {"day": day, "event": event})


async def counts_between(
    conn: AsyncConnection, start: date, end: date
) -> dict[tuple[date, str], int]:
    """`start`~`end`(포함) 날짜의 `(날짜, 이벤트) → 합계`."""
    rows = await conn.execute(text(_RANGE), {"start": start, "end": end})
    return {(row[0], str(row[1])): int(row[2]) for row in rows}
