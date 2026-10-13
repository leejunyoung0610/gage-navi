"""검색 일치율 측정의 순수 함수 (docs/50 §7). 관리번호·주소·응답은 모두 가상 예시다."""

import hashlib

import pytest

from app.address.search_match import (
    REMEASURE_SEED,
    SAMPLE_SIZE,
    SEED,
    RecordKey,
    draw_sample,
    keyword_of,
    sample_rank,
)

POPULATION = [
    RecordKey(license_type, f"가상-{n:05d}")
    for license_type in ("general_restaurant", "rest_restaurant", "bakery")
    for n in range(400)
]


def test_preregistered_constants() -> None:
    assert (SEED, REMEASURE_SEED, SAMPLE_SIZE) == (20261013, 20261014, 2000)


def test_sample_rank_is_sha256_of_seed_and_key() -> None:
    key = RecordKey("bakery", "가상-00001")
    expected = hashlib.sha256("20261013:bakery:가상-00001".encode()).hexdigest()
    assert sample_rank(20261013, key) == expected


def test_draw_sample_takes_lowest_ranks() -> None:
    sample = draw_sample(POPULATION, seed=SEED, size=50)
    assert len(sample) == len(set(sample)) == 50
    ranks = [sample_rank(SEED, key) for key in sample]
    assert ranks == sorted(ranks)
    rest = set(POPULATION) - set(sample)
    assert max(ranks) < min(sample_rank(SEED, key) for key in rest)


def test_draw_sample_ignores_population_order_and_duplicates() -> None:
    forward = draw_sample(POPULATION, size=50)
    assert draw_sample(reversed(POPULATION), size=50) == forward
    assert draw_sample(POPULATION + POPULATION[:100], size=50) == forward


def test_draw_sample_changes_with_seed() -> None:
    first = draw_sample(POPULATION, seed=SEED, size=50)
    second = draw_sample(POPULATION, seed=REMEASURE_SEED, size=50)
    assert first != second
    assert len(set(first) & set(second)) < 25


def test_draw_sample_smaller_population() -> None:
    assert len(draw_sample(POPULATION[:10], size=50)) == 10


@pytest.mark.parametrize(
    ("road_addr", "expected"),
    [
        ("가상시 가상구 가상로 611 (가상동)", "가상시 가상구 가상로 611"),
        ("가상시 가상구 가상로41길 9, 제시동 1층 좌측호 (가상동)", "가상시 가상구 가상로41길 9"),
        ("가상시 가상구 가상로 지하 88, 374호 (가상동2가)", "가상시 가상구 가상로 지하 88"),
        ("가상시 가상구 가상로 870 (가상동, 지하3층)", "가상시 가상구 가상로 870"),
        ("가상시  가상구   가상로 12-3", "가상시 가상구 가상로 12-3"),
        ("가상시 가상구 가상로 12(가상동)", "가상시 가상구 가상로 12"),
    ],
)
def test_keyword_of(road_addr: str, expected: str) -> None:
    assert keyword_of(road_addr) == expected
