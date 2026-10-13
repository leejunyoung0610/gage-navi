"""GET /api/v1/address/search — 도로명주소 API 프록시 (docs/30 §2).

검색어는 로그에 남기지 않는다. 로그에는 실패 종류(오류코드·예외 이름)만 쓴다.
"""

import logging
from functools import lru_cache
from typing import Annotated

import httpx2
from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel

from app.address.cache import SearchCache
from app.address.juso import (
    JusoClient,
    JusoKeywordError,
    JusoPage,
    JusoUnavailableError,
    clean_keyword,
)
from app.core import db
from app.core.config import get_settings
from app.core.errors import ApiError, ErrorCode, ErrorResponse
from app.core.ratelimit import limit_lookup
from app.core.request_id import new_request_id

logger = logging.getLogger(__name__)

router = APIRouter(tags=["address"])

MIN_KEYWORD_LENGTH = 2
KEYWORD_MESSAGE = "주소를 조금 더 자세히 입력해 주세요."
UPSTREAM_MESSAGE = "주소 검색에 일시적인 문제가 있어요. 잠시 후 다시 시도해 주세요."

search_cache = SearchCache()


class AddressItem(BaseModel):
    road_addr: str
    jibun_addr: str
    building_name: str | None
    # 응답으로 필지를 정할 수 없으면 둘 다 null
    pnu: str | None
    has_history: bool | None


class AddressSearchData(BaseModel):
    items: list[AddressItem]
    page: int
    total: int


class Meta(BaseModel):
    request_id: str


class AddressSearchResponse(BaseModel):
    data: AddressSearchData
    meta: Meta


@lru_cache(maxsize=1)
def _http_client() -> httpx2.AsyncClient:
    return httpx2.AsyncClient()


def get_juso_client() -> JusoClient:
    key = get_settings().juso_confm_key
    if key is None:
        logger.warning("address search: JUSO_CONFM_KEY is not set")
        raise ApiError(ErrorCode.UPSTREAM_UNAVAILABLE, UPSTREAM_MESSAGE)
    return JusoClient(key, _http_client())


def _keyword_error(reason: str) -> ApiError:
    return ApiError(ErrorCode.VALIDATION_ERROR, KEYWORD_MESSAGE, {"fields": {"q": reason}})


async def _search(client: JusoClient, keyword: str, page: int) -> JusoPage:
    cached = search_cache.get(keyword, page)
    if cached is not None:
        return cached
    result = await client.search(keyword, page)
    search_cache.put(keyword, page, result)
    return result


@router.get(
    "/address/search",
    dependencies=[Depends(limit_lookup)],
    responses={
        422: {"model": ErrorResponse},
        429: {"model": ErrorResponse},
        502: {"model": ErrorResponse},
        503: {"model": ErrorResponse},
    },
)
async def search_address(
    client: Annotated[JusoClient, Depends(get_juso_client)],
    q: Annotated[str, Query()],
    page: Annotated[int, Query()] = 1,
) -> AddressSearchResponse:
    keyword = clean_keyword(q)
    if len(keyword) < MIN_KEYWORD_LENGTH:
        raise _keyword_error("too_short")
    if page < 1:
        raise ApiError(
            ErrorCode.VALIDATION_ERROR,
            "페이지 번호를 확인해 주세요.",
            {"fields": {"page": "must_be_positive"}},
        )
    try:
        result = await _search(client, keyword, page)
    except JusoKeywordError as exc:
        raise _keyword_error(exc.code) from None
    except JusoUnavailableError as exc:
        logger.warning("address search: upstream failed (%s)", exc.reason)
        raise ApiError(ErrorCode.UPSTREAM_UNAVAILABLE, UPSTREAM_MESSAGE) from None

    pnus = sorted({item.pnu for item in result.items if item.pnu is not None})
    try:
        with_history = await db.existing_parcels(pnus)
    except Exception as exc:
        logger.warning("address search: parcel lookup failed (%s)", type(exc).__name__)
        raise ApiError(
            ErrorCode.SERVICE_UNAVAILABLE,
            "서비스에 일시적인 문제가 있어요. 잠시 후 다시 시도해 주세요.",
        ) from None
    items = [
        AddressItem(
            road_addr=item.road_addr,
            jibun_addr=item.jibun_addr,
            building_name=item.building_name,
            pnu=item.pnu,
            has_history=None if item.pnu is None else item.pnu in with_history,
        )
        for item in result.items
    ]
    return AddressSearchResponse(
        data=AddressSearchData(items=items, page=result.page, total=result.total),
        meta=Meta(request_id=new_request_id()),
    )
