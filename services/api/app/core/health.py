"""GET /api/v1/health (docs/30 §2)."""

import logging
from typing import Literal

from fastapi import APIRouter
from pydantic import BaseModel

from app.core import db
from app.core.errors import ApiError, ErrorCode, ErrorResponse

logger = logging.getLogger(__name__)

router = APIRouter(tags=["health"])


class HealthResponse(BaseModel):
    status: Literal["ok"]
    db: Literal["ok"]
    # 값을 알 수 없으면 null. `approved_rules`는 T-055에서 채운다.
    location_snapshot: str | None
    approved_rules: int | None


@router.get("/health", responses={503: {"model": ErrorResponse}})
async def health() -> HealthResponse:
    try:
        await db.ping_db()
    except Exception as exc:
        logger.warning("health: db ping failed (%s)", type(exc).__name__)
        raise ApiError(
            ErrorCode.SERVICE_UNAVAILABLE,
            "서비스에 일시적인 문제가 있어요. 잠시 후 다시 시도해 주세요.",
            {"db": "error"},
        ) from exc
    return HealthResponse(
        status="ok", db="ok", location_snapshot=await _location_snapshot(), approved_rules=None
    )


async def _location_snapshot() -> str | None:
    """값을 알 수 없으면(테이블이 아직 없는 DB 등) `null`. 상태 확인 자체는 실패시키지 않는다."""
    try:
        return await db.location_snapshot_label()
    except Exception as exc:
        logger.warning("health: location snapshot lookup failed (%s)", type(exc).__name__)
        return None
