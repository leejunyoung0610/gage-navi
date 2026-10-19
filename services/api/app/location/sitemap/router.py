"""GET /api/v1/sitemap/sigungu, GET /api/v1/sitemap/sigungu/{code} (docs/30 §2, T-035).

웹 사이트맵(docs/40 §9)에 넣을 층 페이지: `floor_summary.record_count ≥ 2`인 층. 이 값은 숨김
기록을 뺀 것이다(숨김 처리 때 필지 요약을 다시 만든다, docs/10 §7.1). 쓰기는 없다.
"""

import asyncio
import logging
import re
from typing import Any

from fastapi import APIRouter, Depends, Response
from pydantic import BaseModel
from sqlalchemy import text

from app.core.db import get_engine
from app.core.errors import ApiError, ErrorCode, ErrorResponse
from app.core.ratelimit import limit_lookup
from app.core.request_id import current_request_id

logger = logging.getLogger(__name__)

router = APIRouter(tags=["sitemap"])

CACHE_CONTROL = "public, max-age=300"  # docs/30 §1 "캐시"
QUERY_TIMEOUT_SECONDS = 5.0
UNAVAILABLE_MESSAGE = "서비스에 일시적인 문제가 있어요. 잠시 후 다시 시도해 주세요."
MIN_RECORDS = 2  # 색인 허용: 기록 2건 이상인 층 (docs/40 §9)
SIGUNGU_PATTERN = re.compile(r"\d{5}")
ERROR_RESPONSES: dict[int | str, dict[str, object]] = {
    422: {"model": ErrorResponse},
    429: {"model": ErrorResponse},
    503: {"model": ErrorResponse},
}

_SIGUNGU = """
SELECT left(pnu, 5) AS code, count(*) FROM floor_summary
WHERE record_count >= :min_records
GROUP BY code ORDER BY code
"""

_FLOORS = """
SELECT pnu, floor FROM floor_summary
WHERE left(pnu, 5) = :code AND record_count >= :min_records
ORDER BY pnu, floor COLLATE "C"
"""


class SitemapSigungu(BaseModel):
    code: str
    floor_count: int


class SigunguList(BaseModel):
    sigungu: list[SitemapSigungu]


class SitemapFloor(BaseModel):
    pnu: str
    floor: str


class SigunguFloors(BaseModel):
    code: str
    floors: list[SitemapFloor]


class SitemapMeta(BaseModel):
    request_id: str


class SigunguListResponse(BaseModel):
    data: SigunguList
    meta: SitemapMeta


class SigunguFloorsResponse(BaseModel):
    data: SigunguFloors
    meta: SitemapMeta


async def _rows(sql: str, params: dict[str, Any]) -> list[tuple[str, Any]]:
    try:
        async with asyncio.timeout(QUERY_TIMEOUT_SECONDS):
            async with get_engine().connect() as conn:
                rows = await conn.execute(text(sql), {"min_records": MIN_RECORDS, **params})
                return [(str(r[0]), r[1]) for r in rows]
    except Exception as exc:
        logger.warning("sitemap: lookup failed (%s)", type(exc).__name__)
        raise ApiError(ErrorCode.SERVICE_UNAVAILABLE, UNAVAILABLE_MESSAGE) from None


@router.get("/sitemap/sigungu", dependencies=[Depends(limit_lookup)], responses=ERROR_RESPONSES)
async def get_sigungu(response: Response) -> SigunguListResponse:
    rows = await _rows(_SIGUNGU, {})
    response.headers["Cache-Control"] = CACHE_CONTROL
    return SigunguListResponse(
        data=SigunguList(sigungu=[SitemapSigungu(code=c, floor_count=int(n)) for c, n in rows]),
        meta=SitemapMeta(request_id=current_request_id()),
    )


@router.get(
    "/sitemap/sigungu/{code}", dependencies=[Depends(limit_lookup)], responses=ERROR_RESPONSES
)
async def get_sigungu_floors(code: str, response: Response) -> SigunguFloorsResponse:
    if SIGUNGU_PATTERN.fullmatch(code) is None:
        raise ApiError(
            ErrorCode.VALIDATION_ERROR,
            "시군구 코드를 확인해 주세요.",
            {"fields": {"code": "invalid_format"}},
        )
    rows = await _rows(_FLOORS, {"code": code})
    response.headers["Cache-Control"] = CACHE_CONTROL
    return SigunguFloorsResponse(
        data=SigunguFloors(code=code, floors=[SitemapFloor(pnu=p, floor=str(f)) for p, f in rows]),
        meta=SitemapMeta(request_id=current_request_id()),
    )
