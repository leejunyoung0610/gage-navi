"""요청 ID (ULID: 시각 48비트 + 난수 80비트, Crockford base32 26자).

요청마다 한 번 만들어 응답 `meta.request_id`, 헤더 `X-Request-ID`, 그 요청의 로그에 같은 값을
쓴다(docs/30 §1). 사용자가 오류 화면의 ID를 알려 주면 그 값으로 로그를 찾는다.
"""

import logging
import secrets
import time
from contextvars import ContextVar

from starlette.datastructures import MutableHeaders
from starlette.types import ASGIApp, Message, Receive, Scope, Send

_ALPHABET = "0123456789ABCDEFGHJKMNPQRSTVWXYZ"
HEADER = "X-Request-ID"
ACCESS_LOGGER = "app.access"

_current: ContextVar[str | None] = ContextVar("request_id", default=None)
access_logger = logging.getLogger(ACCESS_LOGGER)


def new_request_id() -> str:
    value = (time.time_ns() // 1_000_000) << 80 | secrets.randbits(80)
    return "".join(_ALPHABET[(value >> shift) & 31] for shift in range(125, -1, -5))


def current_request_id() -> str:
    """지금 처리 중인 요청의 ID. 요청 밖(배치 잡 등)에서는 새로 만든다."""
    return _current.get() or new_request_id()


def log_request_id() -> str:
    """로그에 쓸 요청 ID. 요청 밖이면 `-`."""
    return _current.get() or "-"


class RequestIdMiddleware:
    """요청마다 ID를 한 번 만들고, 응답 헤더에 넣고, 접속 로그 한 줄을 남긴다.

    클라이언트가 보낸 `X-Request-ID`는 쓰지 않는다. 접속 로그의 경로는 쿼리스트링을 뺀
    것이고(주소 검색어가 들어 있다) 본문은 남기지 않는다(docs/01 §6).
    """

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        request_id = new_request_id()
        token = _current.set(request_id)
        started = time.perf_counter()
        status = 500

        async def send_with_id(message: Message) -> None:
            nonlocal status
            if message["type"] == "http.response.start":
                status = message["status"]
                MutableHeaders(scope=message)[HEADER] = request_id
            await send(message)

        try:
            await self.app(scope, receive, send_with_id)
        finally:
            access_logger.info(
                "method=%s path=%s status=%s latency_ms=%d",
                scope.get("method", ""),
                scope.get("path", ""),
                status,
                round((time.perf_counter() - started) * 1000),
            )
            _current.reset(token)
