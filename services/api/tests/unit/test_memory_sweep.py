"""메모리 주기 정리: 방문이 없어도 만료된 IP·검색 캐시가 남지 않는다 (docs/60 §5, T-104).

`/privacy`의 "최대 1시간 1분"(IP), "최대 24시간 1분"(검색 캐시) = 만료 시간 + 정리 주기.
가짜 시계와 가짜 `sleep`으로 정리 루프를 돌린다. 검색 결과 값은 가상 예시.
"""

import asyncio
import math
from collections.abc import Callable
from typing import Any

import pytest
from fastapi.testclient import TestClient

import app.main as main_module
from app.address.cache import TTL_SECONDS, SearchCache
from app.address.juso import JusoItem, JusoPage
from app.address.router import search_cache
from app.core.memory_sweep import SWEEP_INTERVAL_SECONDS, Purgeable, sweep_periodically
from app.core.ratelimit import (
    LIMITERS,
    RateLimiter,
    correction_limiter,
    event_limiter,
    lookup_limiter,
)

PAGE = JusoPage(items=(JusoItem("가상로 1", "가상동 1", None, None),), page=1, total=1)


class Clock:
    def __init__(self) -> None:
        self.now = 0.0

    def __call__(self) -> float:
        return self.now


class Stop(Exception):
    pass


def run_sweeps(
    targets: list[Purgeable], clock: Clock, ticks: int, after_tick: Callable[[], None]
) -> None:
    """정리 루프를 `ticks`번 돌린다. `sleep`마다 시계를 주기만큼 당기고, 정리 뒤 상태를 기록한다."""
    calls = 0

    async def fake_sleep(seconds: float) -> None:
        nonlocal calls
        if calls > 0:
            after_tick()
        if calls == ticks:
            raise Stop
        calls += 1
        clock.now += seconds

    with pytest.raises(Stop):
        asyncio.run(sweep_periodically(targets, sleep=fake_sleep))


def test_sweep_interval_is_one_minute() -> None:
    assert SWEEP_INTERVAL_SECONDS == 60.0


@pytest.mark.parametrize("window", [60.0, 3600.0])
def test_limiter_keys_gone_after_window_plus_sweep_interval(window: float) -> None:
    clock = Clock()
    limiter = RateLimiter(5, window, clock)
    limiter.hit("192.0.2.1")
    clock.now = 30.0  # 정리 주기 사이에 온 요청
    limiter.hit("192.0.2.2")
    remaining: list[tuple[float, int]] = []
    ticks = int((window + 30.0 + SWEEP_INTERVAL_SECONDS) // SWEEP_INTERVAL_SECONDS)
    run_sweeps([limiter], clock, ticks, lambda: remaining.append((clock.now, len(limiter))))
    # 창이 끝나기 전에는 남아 있고(호출 제한이 동작), 창 + 정리 주기가 지나면 0
    assert all(count == 2 for at, count in remaining if at < window)
    assert all(
        count == 0 for at, count in remaining if at >= 30.0 + window + SWEEP_INTERVAL_SECONDS
    )
    assert len(limiter) == 0


def test_search_cache_gone_after_ttl_plus_sweep_interval() -> None:
    clock = Clock()
    cache = SearchCache(clock=clock)
    cache.put("가상로 1", 1, PAGE)
    clock.now = 30.0
    cache.put("가상로 2", 1, PAGE)
    remaining: list[tuple[float, int]] = []
    deadline = 30.0 + TTL_SECONDS + SWEEP_INTERVAL_SECONDS  # 마지막 저장 + TTL + 정리 주기
    ticks = math.ceil(deadline / SWEEP_INTERVAL_SECONDS)
    run_sweeps([cache], clock, ticks, lambda: remaining.append((clock.now, len(cache))))
    in_ttl = [count for at, count in remaining if at < TTL_SECONDS]
    assert in_ttl and set(in_ttl) == {2}
    after = [count for at, count in remaining if at >= deadline]
    assert after and set(after) == {0}
    assert len(cache) == 0


def test_purge_keeps_unexpired_cache_entries() -> None:
    clock = Clock()
    cache = SearchCache(clock=clock)
    cache.put("가상로 1", 1, PAGE)
    clock.now = TTL_SECONDS - 1
    cache.purge_expired()
    assert cache.get("가상로 1", 1) is PAGE


def test_app_sweeps_every_memory_store_holding_request_values() -> None:
    assert set(map(id, LIMITERS)) == {id(lookup_limiter), id(correction_limiter), id(event_limiter)}
    assert set(map(id, main_module.SWEEP_TARGETS)) == {*map(id, LIMITERS), id(search_cache)}


def test_lifespan_runs_sweeper_until_shutdown(monkeypatch: pytest.MonkeyPatch) -> None:
    seen: dict[str, Any] = {}

    async def fake_sweep(targets: tuple[Purgeable, ...]) -> None:
        seen["targets"] = targets
        try:
            await asyncio.Event().wait()
        except asyncio.CancelledError:
            seen["cancelled"] = True
            raise

    monkeypatch.setattr(main_module, "sweep_periodically", fake_sweep)
    with TestClient(main_module.app):
        pass
    assert seen == {"targets": main_module.SWEEP_TARGETS, "cancelled": True}
