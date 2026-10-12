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
    # 값을 알 수 없으면 null. 스냅샷·규칙 테이블은 T-003·T-005 이후에 생긴다.
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
    return HealthResponse(status="ok", db="ok", location_snapshot=None, approved_rules=None)
