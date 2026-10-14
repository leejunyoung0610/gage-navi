"""IP 기준 호출 제한 (docs/30 §1). 고정 창 방식, 프로세스 메모리에만 둔다."""

import math
import time
from collections.abc import Callable

from fastapi import Request

from app.core.errors import ApiError, ErrorCode

LOOKUP_LIMIT_PER_MINUTE = 120  # 조회 API (docs/30 §1)
CORRECTION_LIMIT_PER_HOUR = 5  # 정정 요청 (docs/30 §1)
_PURGE_THRESHOLD = 10_000


class RateLimiter:
    def __init__(
        self, limit: int, window_seconds: float, clock: Callable[[], float] = time.monotonic
    ) -> None:
        self._limit = limit
        self._window = window_seconds
        self._clock = clock
        self._windows: dict[str, tuple[float, int]] = {}

    def hit(self, key: str) -> int | None:
        """허용이면 `None`, 한도를 넘었으면 다시 시도할 수 있을 때까지 남은 초."""
        now = self._clock()
        started, count = self._windows.get(key, (now, 0))
        if now - started >= self._window:
            started, count = now, 0
        if count >= self._limit:
            return max(1, math.ceil(started + self._window - now))
        if len(self._windows) >= _PURGE_THRESHOLD and key not in self._windows:
            self._purge(now)
        self._windows[key] = (started, count + 1)
        return None

    def _purge(self, now: float) -> None:
        self._windows = {
            key: value for key, value in self._windows.items() if now - value[0] < self._window
        }

    def reset(self) -> None:
        self._windows.clear()


lookup_limiter = RateLimiter(LOOKUP_LIMIT_PER_MINUTE, 60.0)
correction_limiter = RateLimiter(CORRECTION_LIMIT_PER_HOUR, 3600.0)


def _enforce(limiter: RateLimiter, request: Request) -> None:
    client_ip = request.client.host if request.client else "unknown"
    retry_after = limiter.hit(client_ip)
    if retry_after is not None:
        raise ApiError(
            ErrorCode.RATE_LIMITED,
            "요청이 너무 많아요. 잠시 후 다시 시도해 주세요.",
            headers={"Retry-After": str(retry_after)},
        )


def limit_lookup(request: Request) -> None:
    """조회 API 의존성. 한도를 넘으면 429 `RATE_LIMITED` + `Retry-After`."""
    _enforce(lookup_limiter, request)


def limit_correction(request: Request) -> None:
    """정정 요청 의존성 (IP당 5회/시간)."""
    _enforce(correction_limiter, request)
