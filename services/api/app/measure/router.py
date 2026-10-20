"""POST /api/v1/measure/events (docs/30 §2, ADR-027).

요청 본문·결과를 로그에 남기지 않는다. 식별자·주소·User-Agent를 받지 않고 읽지 않는다.
"""

import logging
from datetime import date, datetime
from typing import Annotated

from fastapi import APIRouter, Depends, Response
from pydantic import BaseModel, ConfigDict

from app.core import db
from app.core.errors import ApiError, ErrorCode, ErrorResponse
from app.core.ratelimit import limit_event
from app.measure import store
from app.measure.events import Event, date_in_range

logger = logging.getLogger(__name__)

router = APIRouter(tags=["measure"])

CHECK_MESSAGE = "입력한 내용을 확인해 주세요."
UNAVAILABLE_MESSAGE = "일시적인 문제가 생겼어요. 잠시 후 다시 시도해 주세요."


class MeasureEventIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    event: Event
    date: date


def today_kst() -> date:
    """서버의 한국 시간 오늘 (API 계층에서만, .claude/rules/backend.md)."""
    return datetime.now(db.DISPLAY_TZ).date()


@router.post(
    "/measure/events",
    status_code=204,
    dependencies=[Depends(limit_event)],
    responses={code: {"model": ErrorResponse} for code in (422, 429, 503)},
)
async def record_event(
    body: MeasureEventIn,
    response: Response,
    today: Annotated[date, Depends(today_kst)],
) -> None:
    if not date_in_range(body.event, body.date, today):
        raise ApiError(
            ErrorCode.VALIDATION_ERROR, CHECK_MESSAGE, {"fields": {"date": "out_of_range"}}
        )
    try:
        async with db.get_engine().begin() as conn:
            await store.increment(conn, body.date, body.event)
    except Exception as exc:
        # 예외 메시지에는 SQL 인자가 들어 있을 수 있어 종류 이름만 남긴다
        logger.warning("measure: increment failed (%s)", type(exc).__name__)
        raise ApiError(ErrorCode.SERVICE_UNAVAILABLE, UNAVAILABLE_MESSAGE) from None
    response.headers["Cache-Control"] = "no-store"
