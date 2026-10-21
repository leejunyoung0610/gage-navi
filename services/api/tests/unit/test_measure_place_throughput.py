"""층 조회 처리량 측정의 집계·판정 (ADR-031 조건). 숫자는 가상 예시."""

import math

from jobs.measure_place_throughput import Level, percentile, summarize, verdict


def _level(rps: float, passed: bool) -> Level:
    return Level(4, 100, 0, 60.0, rps, 10.0, 20.0, 0.0, passed)


def test_percentile_nearest_rank() -> None:
    values = [float(v) for v in range(1, 101)]
    assert percentile(values, 0.95) == 95.0
    assert percentile(values, 0.5) == 50.0
    assert math.isnan(percentile([], 0.95))


def test_level_fails_on_slow_p95_or_errors() -> None:
    fast = [100.0] * 100
    assert summarize(4, fast, 0, 10.0).passed
    assert summarize(4, fast, 0, 10.0).rps == 10.0
    assert not summarize(4, [100.0] * 94 + [600.0] * 6, 0, 10.0).passed  # p95 600ms
    assert not summarize(4, fast, 2, 10.0).passed  # 오류율 2/102 ≥ 1%
    assert summarize(4, fast, 1, 10.0).passed  # 1/101 < 1%


def test_level_with_no_success_is_failure() -> None:
    level = summarize(4, [], 5, 10.0)
    assert level.error_rate == 1.0 and not level.passed


def test_verdict_halves_when_limit_exceeds_half_of_sustained() -> None:
    # 지속 15 rps → 분당 900, 절반 450 < 600 → 450으로 낮춘다
    result = verdict([_level(8.0, True), _level(15.0, True), _level(20.0, False)], 600)
    assert result == {"sustained_rps": 15.0, "half_per_minute": 450, "lower_limit_to": 450}


def test_verdict_keeps_limit_when_within_half() -> None:
    result = verdict([_level(40.0, True)], 600)  # 절반 1,200 ≥ 600
    assert result["lower_limit_to"] is None


def test_verdict_without_passing_level() -> None:
    assert verdict([_level(5.0, False)], 600)["sustained_rps"] is None
