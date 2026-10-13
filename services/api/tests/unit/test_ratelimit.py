"""IP 기준 호출 제한 (docs/30 §1: 조회 120회/분)."""

from app.core.ratelimit import LOOKUP_LIMIT_PER_MINUTE, RateLimiter


class Clock:
    def __init__(self) -> None:
        self.now = 0.0

    def __call__(self) -> float:
        return self.now


def test_lookup_limit_matches_docs() -> None:
    assert LOOKUP_LIMIT_PER_MINUTE == 120


def test_blocks_after_limit_and_reports_retry_after() -> None:
    clock = Clock()
    limiter = RateLimiter(3, 60.0, clock)
    assert [limiter.hit("a") for _ in range(3)] == [None, None, None]
    clock.now = 12.5
    assert limiter.hit("a") == 48
    assert limiter.hit("b") is None  # 다른 IP는 따로 센다


def test_window_resets() -> None:
    clock = Clock()
    limiter = RateLimiter(1, 60.0, clock)
    assert limiter.hit("a") is None
    clock.now = 59.9
    assert limiter.hit("a") == 1
    clock.now = 60.0
    assert limiter.hit("a") is None
