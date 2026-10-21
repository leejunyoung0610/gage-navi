"""IP 기준 호출 제한 (docs/30 §1). 고정 창 방식, 프로세스 메모리에만 둔다.

IP는 창이 끝나면 `purge_expired`(앱의 주기 정리, `app.core.memory_sweep`)로 버리고
디스크·DB·로그에 쓰지 않는다. 남는 최대 시간 = 창 길이 + 정리 주기(docs/60 §5, `/privacy` 고지).

웹 서버의 조회(서버 렌더링)는 비밀 헤더가 맞으면 IP 대신 공유 한도 하나로 센다(ADR-031).
"""

import hmac
import math
import time
from collections.abc import Callable

from fastapi import Request

from app.core.config import get_settings
from app.core.errors import ApiError, ErrorCode

LOOKUP_LIMIT_PER_MINUTE = 120  # 조회 API (docs/30 §1)
CORRECTION_LIMIT_PER_HOUR = 5  # 정정 요청 (docs/30 §1)
EVENT_LIMIT_PER_MINUTE = 120  # 측정 이벤트, 조회와 따로 센다 (docs/30 §1, T-104)
SSR_LOOKUP_LIMIT_PER_MINUTE = 600  # 서버 렌더링 요청 전체 (docs/30 §1, ADR-031)
SSR_SECRET_HEADER = "x-ssr-secret"
_SSR_KEY = "ssr"  # IP별로 나누지 않는다 — 서버 렌더링 요청 전체가 하나
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

    def purge_expired(self) -> None:
        """창이 끝난 IP를 지운다 (주기 정리)."""
        self._purge(self._clock())

    def _purge(self, now: float) -> None:
        self._windows = {
            key: value for key, value in self._windows.items() if now - value[0] < self._window
        }

    def __len__(self) -> int:
        return len(self._windows)

    def reset(self) -> None:
        self._windows.clear()


lookup_limiter = RateLimiter(LOOKUP_LIMIT_PER_MINUTE, 60.0)
correction_limiter = RateLimiter(CORRECTION_LIMIT_PER_HOUR, 3600.0)
event_limiter = RateLimiter(EVENT_LIMIT_PER_MINUTE, 60.0)
ssr_limiter = RateLimiter(SSR_LOOKUP_LIMIT_PER_MINUTE, 60.0)
LIMITERS = (lookup_limiter, correction_limiter, event_limiter, ssr_limiter)


def _enforce(limiter: RateLimiter, request: Request) -> None:
    client_ip = request.client.host if request.client else "unknown"
    _hit(limiter, client_ip)


def _from_web_server(request: Request) -> bool:
    """`x-ssr-secret`이 `API_SSR_SECRET`과 같은가. API에 비밀 값이 없으면 헤더를 보지 않는다."""
    secret = get_settings().ssr_secret
    given = request.headers.get(SSR_SECRET_HEADER)
    if secret is None or given is None:
        return False
    return hmac.compare_digest(given.encode(), secret.encode())


def _hit(limiter: RateLimiter, key: str) -> None:
    retry_after = limiter.hit(key)
    if retry_after is not None:
        raise ApiError(
            ErrorCode.RATE_LIMITED,
            "요청이 너무 많아요. 잠시 후 다시 시도해 주세요.",
            headers={"Retry-After": str(retry_after)},
        )


def limit_lookup(request: Request) -> None:
    """조회 API 의존성. 한도를 넘으면 429 `RATE_LIMITED` + `Retry-After`.

    웹 서버의 서버 렌더링 요청(비밀 헤더가 맞음)은 IP 한도 대신 공유 한도로 센다(ADR-031).
    """
    if _from_web_server(request):
        _hit(ssr_limiter, _SSR_KEY)
    else:
        _enforce(lookup_limiter, request)


def limit_correction(request: Request) -> None:
    """정정 요청 의존성 (IP당 5회/시간)."""
    _enforce(correction_limiter, request)


def limit_event(request: Request) -> None:
    """측정 이벤트 의존성 (IP당 120회/분)."""
    _enforce(event_limiter, request)
