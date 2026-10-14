"""POST /api/v1/places/{pnu}/corrections (docs/30 §2).

요청 본문은 로그에 남기지 않는다. 자유 입력 `message`에 연락처 같은 개인정보가 들어올 수 있다.
"""

import logging
from typing import Annotated

from fastapi import APIRouter, Depends, Response
from pydantic import BaseModel, ConfigDict, Field, StringConstraints

from app.core import db
from app.core.errors import ApiError, ErrorCode, ErrorResponse
from app.core.ratelimit import limit_correction
from app.core.request_id import new_request_id
from app.location.corrections import store
from app.location.corrections.store import CreateProblem, Kind
from app.location.places.router import (
    FLOOR_PATTERN,
    NO_HISTORY_MESSAGE,
    UNAVAILABLE_MESSAGE,
    check_pnu,
)

logger = logging.getLogger(__name__)

router = APIRouter(tags=["corrections"])

MESSAGE_MAX = 1000  # docs/04 `correction_request.message`
CHECK_MESSAGE = "입력한 내용을 확인해 주세요."


class CorrectionIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    floor: str | None = None
    record_id: Annotated[int, Field(ge=1)] | None = None
    kind: Kind
    message: Annotated[
        str, StringConstraints(strip_whitespace=True, min_length=1, max_length=MESSAGE_MAX)
    ]


class CorrectionCreated(BaseModel):
    id: int


class CreatedMeta(BaseModel):
    request_id: str


class CorrectionResponse(BaseModel):
    data: CorrectionCreated
    meta: CreatedMeta


def _invalid(field: str, kind: str) -> ApiError:
    return ApiError(ErrorCode.VALIDATION_ERROR, CHECK_MESSAGE, {"fields": {field: kind}})


@router.post(
    "/places/{pnu}/corrections",
    status_code=201,
    dependencies=[Depends(limit_correction)],
    responses={code: {"model": ErrorResponse} for code in (404, 422, 429, 503)},
)
async def create_correction(pnu: str, body: CorrectionIn, response: Response) -> CorrectionResponse:
    check_pnu(pnu)
    if body.floor is not None and FLOOR_PATTERN.fullmatch(body.floor) is None:
        raise _invalid("floor", "invalid_format")
    try:
        async with db.get_engine().begin() as conn:
            result = await store.create(
                conn, pnu, body.floor, body.record_id, body.kind, body.message
            )
    except Exception as exc:
        # 예외 메시지에는 SQL 인자(본문)가 들어 있을 수 있어 종류 이름만 남긴다
        logger.warning("corrections: create failed (%s)", type(exc).__name__)
        raise ApiError(ErrorCode.SERVICE_UNAVAILABLE, UNAVAILABLE_MESSAGE) from None
    if result is CreateProblem.NO_PARCEL:
        raise ApiError(ErrorCode.NO_HISTORY, NO_HISTORY_MESSAGE)
    if result is CreateProblem.NOT_IN_PLACE:
        raise _invalid("record_id", result.value)
    if result is CreateProblem.NOT_RECORD_FLOOR:
        raise _invalid("floor", result.value)
    assert isinstance(result, int)
    response.headers["Cache-Control"] = "no-store"
    return CorrectionResponse(
        data=CorrectionCreated(id=result), meta=CreatedMeta(request_id=new_request_id())
    )
