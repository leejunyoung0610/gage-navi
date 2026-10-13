"""주소 검색 캐시: 24시간, 검색어 → 결과만 (docs/03 D4). 값은 가상 예시."""

from app.address.cache import TTL_SECONDS, SearchCache
from app.address.juso import JusoItem, JusoPage

PAGE = JusoPage(items=(JusoItem("가상로 1", "가상동 1", None, None),), page=1, total=1)


class Clock:
    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now


def test_ttl_is_24_hours() -> None:
    assert TTL_SECONDS == 86_400


def test_hit_until_ttl_then_miss() -> None:
    clock = Clock()
    cache = SearchCache(clock=clock)
    cache.put("가상로 1", 1, PAGE)
    assert cache.get("가상로 1", 1) is PAGE
    assert cache.get("가상로 1", 2) is None
    clock.now += TTL_SECONDS - 1
    assert cache.get("가상로 1", 1) is PAGE
    clock.now += 1
    assert cache.get("가상로 1", 1) is None
    assert len(cache) == 0


def test_evicts_least_recently_used() -> None:
    cache = SearchCache(max_entries=2, clock=Clock())
    cache.put("a", 1, PAGE)
    cache.put("b", 1, PAGE)
    assert cache.get("a", 1) is PAGE
    cache.put("c", 1, PAGE)
    assert cache.get("b", 1) is None
    assert cache.get("a", 1) is PAGE and cache.get("c", 1) is PAGE


def test_entry_holds_only_keyword_page_and_result() -> None:
    cache = SearchCache(clock=Clock())
    cache.put("가상로 1", 1, PAGE)
    ((key, (expires_at, value)),) = cache._entries.items()
    assert key == ("가상로 1", 1)
    assert isinstance(expires_at, float) and value is PAGE
