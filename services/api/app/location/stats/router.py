"""GET /api/v1/stats/model-card — 방법론 페이지 데이터 (docs/30 §2, docs/40 §4.9, T-034).

모형 카드(`model_card`)와 검색 일치율(`search_match_result`)을 함께 준다. 쓰기는 없다.
"""

import asyncio
import logging
from typing import Any

from fastapi import APIRouter, Response
from pydantic import BaseModel
from sqlalchemy import text

from app.address.search_match import SearchMatchPayload
from app.core.db import get_engine
from app.core.errors import ApiError, ErrorCode, ErrorResponse
from app.core.request_id import current_request_id
from app.location.stats.card import ModelCardPayload

logger = logging.getLogger(__name__)

router = APIRouter(tags=["stats"])

CACHE_CONTROL = "public, max-age=300"  # docs/30 §1 "캐시"
QUERY_TIMEOUT_SECONDS = 5.0
UNAVAILABLE_MESSAGE = "서비스에 일시적인 문제가 있어요. 잠시 후 다시 시도해 주세요."

# 기준율 카드와 같은 카드: W0 재현 카드가 아닌 것 중 가장 최근 (docs/30 `base_rate`)
_LATEST_CARD = """
SELECT method_version, payload FROM model_card
WHERE method_version <> 'w0' ORDER BY id DESC LIMIT 1
"""
_LATEST_SEARCH_MATCH = "SELECT payload FROM search_match_result ORDER BY id DESC LIMIT 1"


class ModelCardData(BaseModel):
    method_version: str | None  # 모형 카드가 없으면 null
    model_card: ModelCardPayload | None
    search_match: SearchMatchPayload | None


class StatsMeta(BaseModel):
    request_id: str


class ModelCardResponse(BaseModel):
    data: ModelCardData
    meta: StatsMeta


async def _read() -> tuple[tuple[str, Any] | None, Any | None]:
    async with asyncio.timeout(QUERY_TIMEOUT_SECONDS):
        async with get_engine().connect() as conn:
            card = (await conn.execute(text(_LATEST_CARD))).one_or_none()
            match = (await conn.execute(text(_LATEST_SEARCH_MATCH))).scalar()
    return (None if card is None else (str(card[0]), card[1])), match


@router.get("/stats/model-card", responses={503: {"model": ErrorResponse}})
async def get_model_card(response: Response) -> ModelCardResponse:
    try:
        card, match = await _read()
        data = ModelCardData(
            method_version=None if card is None else card[0],
            model_card=None if card is None else ModelCardPayload.model_validate(card[1]),
            search_match=None if match is None else SearchMatchPayload.model_validate(match),
        )
    except Exception as exc:
        logger.warning("stats: model card lookup failed (%s)", type(exc).__name__)
        raise ApiError(ErrorCode.SERVICE_UNAVAILABLE, UNAVAILABLE_MESSAGE) from None
    response.headers["Cache-Control"] = CACHE_CONTROL
    return ModelCardResponse(data=data, meta=StatsMeta(request_id=current_request_id()))
