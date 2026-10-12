"""층 파서 (docs/10 §3).

지번주소 꼬리(`tail`)와 도로명주소 상세(`road_detail`)에서 층을 읽어 `B9…B1`, `1…99`, `RF`로
정규화한다. 규칙은 문서 표 그대로이고 위에서부터 첫 매치를 쓴다. 층을 읽지 못하면 `None`.
"""

import re
from collections.abc import Callable
from dataclasses import dataclass
from typing import Literal

FloorSource = Literal["jibun_tail", "road_detail"]

ROOFTOP = "RF"
_BASEMENT_MAX = 9
_GROUND_MAX = 99


def _basement(match: re.Match[str]) -> str | None:
    n = int(match[1])
    return f"B{n}" if 1 <= n <= _BASEMENT_MAX else None


def _ground(n: int) -> str | None:
    return str(n) if 1 <= n <= _GROUND_MAX else None


# (패턴, 매치 → 정규화 값). 범위를 벗어난 숫자는 오입력으로 보고 `None`
_RULES: tuple[tuple[re.Pattern[str], Callable[[re.Match[str]], str | None]], ...] = (
    (re.compile(r"지하\s*(\d+)\s*층", re.I), _basement),
    (re.compile(r"지하층|지층", re.I), lambda _: "B1"),
    # "지N층"·"제지N층"은 지하 N층의 줄임 표기. 필지·단지·번지·건물명 뒤의 "지"는 제외한다
    (re.compile(r"(?<![가-힣A-Za-z0-9])(?:제\s*)?지\s*(\d+)\s*층", re.I), _basement),
    (re.compile(r"(?<![A-Za-z])B\s*(\d{1,2})(?!\d)(?!\s*호)(?:\s*층|F\b)?", re.I), _basement),
    (
        re.compile(r"(\d+)\s*[~,\-]\s*(\d+)\s*층", re.I),
        lambda m: _ground(min(int(m[1]), int(m[2]))),
    ),
    (re.compile(r"(?:지상\s*|제\s*)?(\d+)\s*층", re.I), lambda m: _ground(int(m[1]))),
    (re.compile(r"(\d+)\s*F\b", re.I), lambda m: _ground(int(m[1]))),
    (re.compile(r"옥탑|옥상", re.I), lambda _: ROOFTOP),
)


@dataclass(frozen=True)
class FloorResult:
    floor: str | None
    source: FloorSource | None
    conflict: bool  # tail과 road_detail이 서로 다른 층을 말한다 (`floor_conflict` 지표)


def road_detail(road_addr: str | None) -> str:
    """도로명주소의 첫 쉼표 뒤 문자열. 쉼표가 없으면 빈 문자열."""
    if road_addr is None:
        return ""
    _, _, detail = road_addr.partition(",")
    return detail.strip()


def parse_floor_text(text: str | None) -> str | None:
    """문자열 하나에서 층을 읽는다."""
    if not text:
        return None
    for pattern, normalize in _RULES:
        match = pattern.search(text)
        if match is not None:
            return normalize(match)
    return None


def parse_floor(tail: str | None, road_detail: str | None) -> FloorResult:
    """`tail`에서 먼저 찾고, 없으면 `road_detail`. 둘이 다르면 `tail` 값을 쓴다."""
    from_tail = parse_floor_text(tail)
    from_road = parse_floor_text(road_detail)
    if from_tail is not None:
        return FloorResult(
            from_tail, "jibun_tail", from_road is not None and from_road != from_tail
        )
    if from_road is not None:
        return FloorResult(from_road, "road_detail", False)
    return FloorResult(None, None, False)


def floor_sort_key(floor: str) -> int:
    """정렬 순서 `B9 … B1, 1, 2, …, RF`."""
    if floor == ROOFTOP:
        return _GROUND_MAX + 1
    if floor.startswith("B"):
        return -int(floor[1:])
    return int(floor)
