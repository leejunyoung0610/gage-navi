"""주소 API (docs/30 §2).

- GET /api/v1/address/search — 도로명주소 API 프록시
- GET /api/v1/address/reverse — 좌표 → 그 지점의 필지와 주소

검색어·좌표는 로그에 남기지 않는다. 로그에는 실패 종류(오류코드·예외 이름)만 쓴다.
`reverse`는 카카오 응답과 그 경로의 도로명주소 응답을 저장·캐시하지 않는다(`data/README.md`).
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
    JusoError,
    JusoItem,
    JusoKeywordError,
    JusoPage,
    JusoUnavailableError,
    clean_keyword,
)
from app.address.kakao import KakaoClient, KakaoSpot, KakaoUnavailableError
from app.address.pnu import LegalDongIndex, lot_pnu
from app.core import db
from app.core.config import get_settings
from app.core.errors import ApiError, ErrorCode, ErrorResponse
from app.core.ratelimit import limit_lookup
from app.core.request_id import current_request_id

logger = logging.getLogger(__name__)

router = APIRouter(tags=["address"])

MIN_KEYWORD_LENGTH = 2
KEYWORD_MESSAGE = "주소를 조금 더 자세히 입력해 주세요."
UPSTREAM_MESSAGE = "주소 검색에 일시적인 문제가 있어요. 잠시 후 다시 시도해 주세요."
REVERSE_UPSTREAM_MESSAGE = (
    "위치로 주소를 찾는 데 일시적인 문제가 있어요. 잠시 후 다시 시도해 주세요."
)
DB_MESSAGE = "서비스에 일시적인 문제가 있어요. 잠시 후 다시 시도해 주세요."

search_cache = SearchCache()


class AddressItem(BaseModel):
    # 주소 검색은 항상 값이 있다. 좌표 결과에서 카카오가 도로명 주소를 주지 않으면 null
    road_addr: str | None
    jibun_addr: str
    building_name: str | None
    # 응답으로 필지를 정할 수 없으면 둘 다 null
    pnu: str | None
    has_history: bool | None
    # 같은 건물의 관련지번 PNU. 법정동을 찾지 못한 지번은 뺀다 (docs/30 §2).
    # 주소 검색은 항상 목록이다. null은 좌표 결과에서 확인하지 못한 경우뿐
    # — []("확인했고 없음")과 다르다
    related_pnus: list[str] | None


class AddressSearchData(BaseModel):
    items: list[AddressItem]
    page: int
    total: int


class AddressReverseData(BaseModel):
    # 그 지점의 PNU. 법정동코드나 지번을 얻지 못하면 null이고 items는 빈 목록 (UNKNOWN)
    pnu: str | None
    items: list[AddressItem]


class Meta(BaseModel):
    request_id: str


class AddressSearchResponse(BaseModel):
    data: AddressSearchData
    meta: Meta


class AddressReverseResponse(BaseModel):
    data: AddressReverseData
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


def get_kakao_client() -> KakaoClient:
    key = get_settings().kakao_rest_api_key
    if key is None:
        logger.warning("address reverse: KAKAO_REST_API_KEY is not set")
        raise ApiError(ErrorCode.UPSTREAM_UNAVAILABLE, REVERSE_UPSTREAM_MESSAGE)
    return KakaoClient(key, _http_client())


def get_reverse_juso_client() -> JusoClient | None:
    """좌표 결과의 관련지번 확인용. 승인키가 없으면 확인 못 함으로 둔다(`related_pnus` null)."""
    key = get_settings().juso_confm_key
    return None if key is None else JusoClient(key, _http_client())


def _keyword_error(reason: str) -> ApiError:
    return ApiError(ErrorCode.VALIDATION_ERROR, KEYWORD_MESSAGE, {"fields": {"q": reason}})


def _related_pnus(item: JusoItem, index: LegalDongIndex) -> list[str]:
    """관련지번 → PNU. 대표 지번과 같은 값·중복은 빼고 나온 순서를 지킨다."""
    pnus: list[str] = []
    for lot in item.related_lots:
        pnu = lot_pnu(lot.dong_name, lot.is_san, lot.main, lot.sub, index)
        if pnu is not None and pnu != item.pnu and pnu not in pnus:
            pnus.append(pnu)
    return pnus


def _db_error(where: str, exc: Exception) -> ApiError:
    logger.warning("%s: parcel lookup failed (%s)", where, type(exc).__name__)
    return ApiError(ErrorCode.SERVICE_UNAVAILABLE, DB_MESSAGE)


async def _lookups(pnus: list[str], items: list[JusoItem]) -> tuple[set[str], LegalDongIndex]:
    """`has_history`용 `parcel` 존재 여부와 관련지번용 법정동 조회 표."""
    dong_names = sorted({lot.dong_name for item in items for lot in item.related_lots})
    with_history = await db.existing_parcels(sorted(set(pnus)))
    index = LegalDongIndex.from_rows(await db.legal_dong_rows(dong_names))
    return with_history, index


def _item(item: JusoItem, with_history: set[str], index: LegalDongIndex) -> AddressItem:
    return AddressItem(
        road_addr=item.road_addr,
        jibun_addr=item.jibun_addr,
        building_name=item.building_name,
        pnu=item.pnu,
        has_history=None if item.pnu is None else item.pnu in with_history,
        related_pnus=_related_pnus(item, index),
    )


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

    pnus = [item.pnu for item in result.items if item.pnu is not None]
    try:
        with_history, index = await _lookups(pnus, list(result.items))
    except Exception as exc:
        raise _db_error("address search", exc) from None
    items = [_item(item, with_history, index) for item in result.items]
    return AddressSearchResponse(
        data=AddressSearchData(items=items, page=result.page, total=result.total),
        meta=Meta(request_id=current_request_id()),
    )


async def _same_parcel(client: JusoClient | None, spot: KakaoSpot, pnu: str) -> list[JusoItem]:
    """그 주소로 도로명주소 검색을 한 번 부르고 PNU가 같은 결과만 남긴다. 캐시를 쓰지 않는다.

    부를 수 없거나 실패하면 빈 목록 — 호출하는 쪽이 `related_pnus`를 null(확인 못 함)로 둔다.
    """
    keyword = clean_keyword(spot.road_addr or spot.jibun_addr or "")
    if client is None or len(keyword) < MIN_KEYWORD_LENGTH:
        return []
    try:
        result = await client.search(keyword, 1)
    except JusoError as exc:
        logger.warning("address reverse: juso lookup skipped (%s)", type(exc).__name__)
        return []
    return [item for item in result.items if item.pnu == pnu]


@router.get(
    "/address/reverse",
    dependencies=[Depends(limit_lookup)],
    responses={
        422: {"model": ErrorResponse},
        429: {"model": ErrorResponse},
        502: {"model": ErrorResponse},
        503: {"model": ErrorResponse},
    },
)
async def reverse_address(
    kakao: Annotated[KakaoClient, Depends(get_kakao_client)],
    juso: Annotated[JusoClient | None, Depends(get_reverse_juso_client)],
    lat: Annotated[float, Query(ge=-90, le=90)],
    lng: Annotated[float, Query(ge=-180, le=180)],
) -> AddressReverseResponse:
    try:
        spot = await kakao.locate(lat, lng)
    except KakaoUnavailableError as exc:
        logger.warning("address reverse: upstream failed (%s)", exc.reason)
        raise ApiError(ErrorCode.UPSTREAM_UNAVAILABLE, REVERSE_UPSTREAM_MESSAGE) from None

    pnu = spot.pnu
    meta = Meta(request_id=current_request_id())
    if pnu is None or spot.jibun_addr is None:
        return AddressReverseResponse(data=AddressReverseData(pnu=None, items=[]), meta=meta)

    matched = await _same_parcel(juso, spot, pnu)
    try:
        with_history, index = await _lookups([pnu], matched)
    except Exception as exc:
        raise _db_error("address reverse", exc) from None
    if matched:
        items = [_item(item, with_history, index) for item in matched]
    else:
        items = [
            AddressItem(
                road_addr=spot.road_addr,
                jibun_addr=spot.jibun_addr,
                building_name=spot.building_name,
                pnu=pnu,
                has_history=pnu in with_history,
                related_pnus=None,  # 같은 건물의 다른 필지를 확인하지 못했다 ([]과 다르다)
            )
        ]
    return AddressReverseResponse(data=AddressReverseData(pnu=pnu, items=items), meta=meta)
