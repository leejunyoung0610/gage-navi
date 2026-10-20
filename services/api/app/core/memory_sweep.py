"""메모리에 잠시 두는 값(호출 제한의 IP, 주소 검색 캐시)의 주기 정리 (docs/60 §5, T-104).

방문이 적어도 만료된 값이 프로세스가 끝날 때까지 남지 않게, 앱 수명 동안 1분마다 지운다.
`/privacy`의 "최대 n시간 m분"은 만료 시간 + 이 주기다. 한 대상이 실패해도 다른 대상과 다음
주기는 계속 돈다(로그에는 예외 종류 이름만 — 메시지에 IP·검색어가 들어갈 수 있다).
"""

import asyncio
import logging
from collections.abc import Awaitable, Callable, Sequence
from typing import Protocol

SWEEP_INTERVAL_SECONDS = 60.0

logger = logging.getLogger(__name__)


class Purgeable(Protocol):
    def purge_expired(self) -> None: ...


async def sweep_periodically(
    targets: Sequence[Purgeable],
    interval_seconds: float = SWEEP_INTERVAL_SECONDS,
    sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
) -> None:
    """취소될 때까지 `interval_seconds`마다 모든 대상을 정리한다."""
    while True:
        await sleep(interval_seconds)
        for target in targets:
            try:
                target.purge_expired()
            except Exception as exc:  # 다음 주기에 다시 정리한다
                logger.warning("memory sweep failed (%s)", type(exc).__name__)
