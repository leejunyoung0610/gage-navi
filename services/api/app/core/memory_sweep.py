"""메모리에 잠시 두는 값(호출 제한의 IP, 주소 검색 캐시)의 주기 정리 (docs/60 §5, T-104).

방문이 적어도 만료된 값이 프로세스가 끝날 때까지 남지 않게, 앱 수명 동안 1분마다 지운다.
`/privacy`의 "최대 n시간 m분"은 만료 시간 + 이 주기다.
"""

import asyncio
from collections.abc import Awaitable, Callable, Sequence
from typing import Protocol

SWEEP_INTERVAL_SECONDS = 60.0


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
            target.purge_expired()
