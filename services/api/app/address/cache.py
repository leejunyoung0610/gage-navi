"""주소 검색 결과 캐시 (docs/03 D4: 동일 질의 24시간).

키는 (정제한 검색어, 페이지), 값은 도로명주소 API 결과뿐이다. 요청한 사람에 관한 값
(IP, 시각, 헤더)은 넣지 않는다. 프로세스 메모리에만 있고 디스크·DB에 쓰지 않는다.
만료 항목은 `purge_expired`(앱의 주기 정리, `app.core.memory_sweep`)로 지운다. 남는 최대 시간 =
TTL + 정리 주기(docs/60 §5, `/privacy` 고지).
"""

import time
from collections import OrderedDict
from collections.abc import Callable

from app.address.juso import JusoPage

TTL_SECONDS = 24 * 60 * 60
MAX_ENTRIES = 10_000


class SearchCache:
    def __init__(
        self,
        ttl_seconds: float = TTL_SECONDS,
        max_entries: int = MAX_ENTRIES,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._ttl = ttl_seconds
        self._max = max_entries
        self._clock = clock
        self._entries: OrderedDict[tuple[str, int], tuple[float, JusoPage]] = OrderedDict()

    def get(self, keyword: str, page: int) -> JusoPage | None:
        entry = self._entries.get((keyword, page))
        if entry is None:
            return None
        expires_at, value = entry
        if self._clock() >= expires_at:
            del self._entries[(keyword, page)]
            return None
        self._entries.move_to_end((keyword, page))
        return value

    def put(self, keyword: str, page: int, value: JusoPage) -> None:
        self._entries[(keyword, page)] = (self._clock() + self._ttl, value)
        self._entries.move_to_end((keyword, page))
        while len(self._entries) > self._max:
            self._entries.popitem(last=False)

    def purge_expired(self) -> None:
        """만료된 항목을 지운다 (주기 정리)."""
        now = self._clock()
        expired = [key for key, (expires_at, _) in self._entries.items() if now >= expires_at]
        for key in expired:
            del self._entries[key]

    def clear(self) -> None:
        self._entries.clear()

    def __len__(self) -> int:
        return len(self._entries)
