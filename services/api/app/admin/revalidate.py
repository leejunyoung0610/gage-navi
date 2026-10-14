"""웹 on-demand 재생성 호출 (docs/30 §1·§3, docs/40 `/api/revalidate`).

`WEB_REVALIDATE_URL`에 `POST {"paths": [...]}`, 헤더 `x-revalidate-secret`. 실패하면 최대 3번까지
시도하고, 그래도 실패하면 `False`(호출한 쪽이 `revalidated_at`을 비워 두고 나중에 재시도한다).
"""

import asyncio
import logging
from collections.abc import Awaitable, Callable

import httpx2

from app.core.config import get_settings

logger = logging.getLogger(__name__)

SECRET_HEADER = "x-revalidate-secret"
ATTEMPTS = 3
BACKOFF_SECONDS = (0.5, 1.0)  # 두 번째·세 번째 시도 전에 기다리는 시간
TIMEOUT_SECONDS = 5.0

# 테스트에서 `httpx2.MockTransport`로 바꾼다
transport: httpx2.AsyncBaseTransport | None = None
sleep: Callable[[float], Awaitable[None]] = asyncio.sleep


async def revalidate(paths: list[str], correction_id: int) -> bool:
    """재생성을 요청한다. 성공(2xx)하면 `True`. 실패는 경고 로그만 남기고 `False`."""
    settings = get_settings()
    if not settings.web_revalidate_url or not settings.revalidate_secret:
        logger.warning("revalidate: not configured correction_id=%s", correction_id)
        return False
    reason = ""
    async with httpx2.AsyncClient(timeout=TIMEOUT_SECONDS, transport=transport) as client:
        for attempt in range(ATTEMPTS):
            if attempt:
                await sleep(BACKOFF_SECONDS[attempt - 1])
            try:
                response = await client.post(
                    settings.web_revalidate_url,
                    json={"paths": paths},
                    headers={SECRET_HEADER: settings.revalidate_secret},
                )
            except httpx2.HTTPError as exc:
                reason = type(exc).__name__
                continue
            if response.is_success:
                return True
            reason = f"status {response.status_code}"
    logger.warning(
        "revalidate: failed correction_id=%s attempts=%s reason=%s",
        correction_id,
        ATTEMPTS,
        reason,
    )
    return False
