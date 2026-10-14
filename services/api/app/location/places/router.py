"""GET /api/v1/places/{pnu}, GET /api/v1/places/{pnu}/floors/{floor} (docs/30 §2).

응답에 전화번호 등 개인 연락처 필드를 넣지 않는다(정규화 테이블에도 없다).
"""

import logging
import re
from datetime import date
from decimal import Decimal
from typing import Literal

from fastapi import APIRouter, Depends, Response
from pydantic import BaseModel

from app.core.errors import ApiError, ErrorCode, ErrorResponse
from app.core.ratelimit import limit_lookup
from app.core.request_id import new_request_id
from app.location.places import build
from app.location.places.build import FloorScale, HiddenReason, RateRow, Record
from app.location.places.queries import ModelCardRef, PlaceReader, reader_session

logger = logging.getLogger(__name__)

router = APIRouter(tags=["places"])

CACHE_CONTROL = "public, max-age=300"  # docs/30 §1 "캐시"
_PNU = re.compile(r"\d{19}")
_FLOOR = re.compile(r"B[1-9]|[1-9]\d?|RF")  # 층 파서가 내는 값 (docs/10 §3)
NO_HISTORY_MESSAGE = "이 필지에는 식품 업소 인허가 기록이 없어요."
NO_FLOOR_MESSAGE = "이 층에는 식품 업소 인허가 기록이 없어요."
UNAVAILABLE_MESSAGE = "서비스에 일시적인 문제가 있어요. 잠시 후 다시 시도해 주세요."
ERROR_RESPONSES: dict[int | str, dict[str, object]] = {
    404: {"model": ErrorResponse},
    422: {"model": ErrorResponse},
    429: {"model": ErrorResponse},
    503: {"model": ErrorResponse},
}


class BulkClosureDetail(BaseModel):
    jurisdiction_label: str | None  # 관할 이름을 정할 수 없었으면 null
    closure_count: int


class PlaceRecord(BaseModel):
    record_id: int
    name: str
    license_type: str
    biz_category: str | None
    opened_on: date | None
    closed_on: date | None
    status: str
    tenure_days: int | None
    ho_list: list[str]
    bulk_closure: bool
    bulk_closure_detail: BulkClosureDetail | None


class FloorRecord(PlaceRecord):
    stale_suspect: bool


class Location(BaseModel):
    lat: float
    lng: float


class FloorCountItem(BaseModel):
    floor: str
    record_count: int
    open_now_count: int


class PlaceData(BaseModel):
    pnu: str
    jibun_label: str
    road_addr: str | None
    location: Location | None
    floors: list[FloorCountItem]
    records_without_floor: int
    history_without_floor: list[PlaceRecord]


class Meta(BaseModel):
    request_id: str
    data_as_of: date


class PlaceResponse(BaseModel):
    data: PlaceData
    meta: Meta


class FloorSummary(BaseModel):
    record_count: int
    records_since_2005: int
    open_now_count: int
    median_closed_tenure_days: int | None
    has_concurrent: bool
    max_concurrent: int


class HoGroup(BaseModel):
    ho: str
    record_ids: list[int]


class ScopedRate(BaseModel):
    scope_code: str
    scope_label: str | None
    rate: str
    ci: tuple[str, str]
    n: int


class BaselineRate(BaseModel):
    scope_code: str
    bucket: Literal["0"]
    rate: str
    ci: tuple[str, str]
    n: int


class BaseRate(BaseModel):
    display: bool
    hidden_reason: HiddenReason | None
    floor_scale: FloorScale
    prior_closures_now: int
    bucket: str
    primary: ScopedRate | None
    baseline: BaselineRate | None
    secondary: ScopedRate | None
    snapshot_label: str
    method_version: str


class FloorData(BaseModel):
    pnu: str
    floor: str
    jibun_label: str
    summary: FloorSummary
    history: list[FloorRecord]
    ho_groups: list[HoGroup]
    base_rate: BaseRate | None  # 기준율 모형 카드가 아직 없으면 null
    notices: list[str]
    data_as_of: date


class FloorResponse(BaseModel):
    data: FloorData
    meta: Meta


def _check_pnu(pnu: str) -> None:
    if _PNU.fullmatch(pnu) is None:
        raise ApiError(
            ErrorCode.VALIDATION_ERROR,
            "필지 번호를 확인해 주세요.",
            {"fields": {"pnu": "invalid_format"}},
        )


def _unavailable(where: str, exc: Exception) -> ApiError:
    logger.warning("places: %s failed (%s)", where, type(exc).__name__)
    return ApiError(ErrorCode.SERVICE_UNAVAILABLE, UNAVAILABLE_MESSAGE)


def _place_record(record: Record, as_of: date) -> PlaceRecord:
    return PlaceRecord(**_record_fields(record, as_of))


def _floor_record(record: Record, as_of: date) -> FloorRecord:
    return FloorRecord(**_record_fields(record, as_of), stale_suspect=record.stale_suspect)


def _record_fields(record: Record, as_of: date) -> dict[str, object]:
    detail = None
    if record.bulk_closure and record.surge_count is not None:
        detail = BulkClosureDetail(
            jurisdiction_label=record.surge_label, closure_count=record.surge_count
        )
    return {
        "record_id": record.record_id,
        "name": record.name,
        "license_type": record.license_type,
        "biz_category": record.biz_category,
        "opened_on": record.opened_on,
        "closed_on": record.closed_on,
        "status": record.status,
        "tenure_days": build.tenure_days(record, as_of),
        "ho_list": list(record.ho_list),
        "bulk_closure": record.bulk_closure,
        "bulk_closure_detail": detail,
    }


def _rate_text(value: Decimal) -> str:
    return str(value.quantize(Decimal("0.0001")))


def _scoped(row: RateRow | None, labels: dict[str, str | None]) -> ScopedRate | None:
    if row is None:
        return None
    return ScopedRate(
        scope_code=row.scope_code,
        scope_label=labels.get(row.scope_code),
        rate=_rate_text(row.rate),
        ci=(_rate_text(row.ci_low), _rate_text(row.ci_high)),
        n=row.n,
    )


def _baseline(row: RateRow | None) -> BaselineRate | None:
    if row is None:
        return None
    return BaselineRate(
        scope_code=row.scope_code,
        bucket="0",
        rate=_rate_text(row.rate),
        ci=(_rate_text(row.ci_low), _rate_text(row.ci_high)),
        n=row.n,
    )


async def _as_of(reader: PlaceReader) -> date:
    as_of = await reader.as_of()
    if as_of is None:
        # 이력은 정규화를 통과한 스냅샷으로만 만든다. 기준일이 없으면 응답을 만들 수 없다
        raise RuntimeError("no validated snapshot")
    return as_of


async def _base_rate(
    reader: PlaceReader, card: ModelCardRef, pnu: str, floor: str, max_concurrent: int, as_of: date
) -> BaseRate:
    scale = build.floor_scale(max_concurrent)
    prior_now = await reader.prior_closures_now(pnu, floor, as_of)
    bucket = build.bucket_of(prior_now)
    sigungu = pnu[:5]
    holds = build.scale_holds(card.by_floor_scale, scale)
    rows = await reader.rates(card, scale, sigungu, bucket) if holds else []
    choice = build.choose_rates(rows, sigungu, bucket, holds)
    labels: dict[str, str | None] = {build.SEOUL_SCOPE: build.SEOUL_LABEL}
    if choice.primary is not None and choice.primary.scope_code != build.SEOUL_SCOPE:
        labels[sigungu] = await reader.sigungu_label(sigungu)
    return BaseRate(
        display=choice.display,
        hidden_reason=choice.hidden_reason,
        floor_scale=scale,
        prior_closures_now=prior_now,
        bucket=bucket,
        primary=_scoped(choice.primary, labels),
        baseline=_baseline(choice.baseline),
        secondary=_scoped(choice.secondary, labels),
        snapshot_label=card.snapshot_label,
        method_version=card.method_version,
    )


@router.get(
    "/places/{pnu}",
    dependencies=[Depends(limit_lookup)],
    responses=ERROR_RESPONSES,
)
async def get_place(pnu: str, response: Response) -> PlaceResponse:
    _check_pnu(pnu)
    try:
        async with reader_session() as reader:
            parcel = await reader.parcel(pnu)
            if parcel is None:
                raise ApiError(ErrorCode.NO_HISTORY, NO_HISTORY_MESSAGE)
            as_of = await _as_of(reader)
            counts = await reader.floor_counts(pnu)
            floorless = await reader.records(pnu, None)
    except ApiError:
        raise
    except Exception as exc:
        raise _unavailable("place lookup", exc) from None
    location = None
    if parcel.lat is not None and parcel.lng is not None:
        location = Location(lat=parcel.lat, lng=parcel.lng)
    floors = [
        FloorCountItem(
            floor=f, record_count=counts[f].record_count, open_now_count=counts[f].open_now_count
        )
        for f in parcel.floors
        if f in counts
    ]
    response.headers["Cache-Control"] = CACHE_CONTROL
    return PlaceResponse(
        data=PlaceData(
            pnu=pnu,
            jibun_label=parcel.jibun_label,
            road_addr=parcel.road_addr,
            location=location,
            floors=floors,
            records_without_floor=len(floorless),
            history_without_floor=[_place_record(r, as_of) for r in floorless],
        ),
        meta=Meta(request_id=new_request_id(), data_as_of=as_of),
    )


@router.get(
    "/places/{pnu}/floors/{floor}",
    dependencies=[Depends(limit_lookup)],
    responses=ERROR_RESPONSES,
)
async def get_floor(pnu: str, floor: str, response: Response) -> FloorResponse:
    _check_pnu(pnu)
    if _FLOOR.fullmatch(floor) is None:
        raise ApiError(
            ErrorCode.VALIDATION_ERROR,
            "층을 확인해 주세요.",
            {"fields": {"floor": "invalid_format"}},
        )
    try:
        async with reader_session() as reader:
            parcel = await reader.parcel(pnu)
            summary = None if parcel is None else await reader.floor_summary(pnu, floor)
            if parcel is None or summary is None:
                message = NO_HISTORY_MESSAGE if parcel is None else NO_FLOOR_MESSAGE
                raise ApiError(ErrorCode.NO_HISTORY, message)
            as_of = await _as_of(reader)
            history = await reader.records(pnu, floor)
            pre_2005_floorless = await reader.pre_2005_floorless(pnu)
            card = await reader.latest_model_card()
            base_rate = None
            if card is not None:
                base_rate = await _base_rate(
                    reader, card, pnu, floor, summary.max_concurrent, as_of
                )
    except ApiError:
        raise
    except Exception as exc:
        raise _unavailable("floor lookup", exc) from None
    response.headers["Cache-Control"] = CACHE_CONTROL
    return FloorResponse(
        data=FloorData(
            pnu=pnu,
            floor=floor,
            jibun_label=parcel.jibun_label,
            summary=FloorSummary(
                record_count=summary.record_count,
                records_since_2005=summary.records_since_2005,
                open_now_count=summary.open_now_count,
                median_closed_tenure_days=summary.median_closed_tenure_days,
                has_concurrent=summary.has_concurrent,
                max_concurrent=summary.max_concurrent,
            ),
            history=[_floor_record(r, as_of) for r in history],
            ho_groups=[HoGroup(ho=ho, record_ids=ids) for ho, ids in build.ho_groups(history)],
            base_rate=base_rate,
            notices=build.notices(summary.has_concurrent, history, pre_2005_floorless),
            data_as_of=as_of,
        ),
        meta=Meta(request_id=new_request_id(), data_as_of=as_of),
    )
