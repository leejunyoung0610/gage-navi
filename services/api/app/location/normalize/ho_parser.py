"""호 파서 (docs/10 §4).

지번주소 꼬리(`tail`)와 도로명주소 상세(`road_detail`)에서 호 번호를 읽어 `ho_list`로 정규화한다.
번호는 `N` 또는 가지번호 `N-M`·`N-A`(문자열 그대로 한 원소)이고, 앞의 0 제거·중복 제거·
(본번, 가지번) 오름차순이다. 호를 읽지 못하면 빈 목록.
"""

import re
from dataclasses import dataclass
from typing import Literal

HoSource = Literal["jibun_tail", "road_detail"]

# 번호 하나: "104.1"(세 자리 이상 + 마침표 + 한 자리 — 가지번호), "201-5", "132-A", "206"
_NUMBER = r"(?:\d{3,}\s*\.\s*\d(?!\d)|\d+(?:-\d+|-[A-Za-z])?)"
# 규칙 1: `호`로 끝나는 번호 또는 쉼표·마침표 목록 전체 — "206호", "101,102호", "20.21호".
# `호` 뒤가 선·동·점·관이면 호수가 아니다 (2호선, 3호동, 1호점, 2호관)
_HO = re.compile(rf"(?<!\d)(?<!\d-)({_NUMBER}(?:\s*[,.]\s*{_NUMBER})*)\s*호(?![선동점관])")
# 규칙 2: 층 바로 뒤 숫자 나열 "1층 124, 134,135" — `호`가 없어도 쉼표로 구분된 3~4자리 숫자 목록
_AFTER_FLOOR = re.compile(r"층\s*(\d{3,4}(?:\s*,\s*\d{3,4})+)(?!\d)")
_ITEM = re.compile(_NUMBER)
_PARTS = re.compile(r"(\d+)(?:\s*[-.]\s*(\d+|[A-Za-z]))?")

# 가지번 종류의 정렬 순서: 없음 < 숫자 < 영문
_NO_SUB, _DIGIT_SUB, _LETTER_SUB = 0, 1, 2
_Key = tuple[int, int, int]


@dataclass(frozen=True)
class HoResult:
    ho_list: list[str]
    source: HoSource | None
    conflict: bool  # tail과 road_detail이 서로 다른 목록을 말한다 (`ho_conflict` 지표)


def _key(raw: str) -> _Key:
    match = _PARTS.fullmatch(raw)
    assert match is not None  # `_NUMBER`가 찾은 문자열만 들어온다
    main, sub = int(match[1]), match[2]
    if sub is None:
        return main, _NO_SUB, 0
    if sub.isdigit():
        return main, _DIGIT_SUB, int(sub)
    return main, _LETTER_SUB, ord(sub.upper())


def _format(key: _Key) -> str:
    main, kind, sub = key
    if kind == _NO_SUB:
        return str(main)
    return f"{main}-{sub}" if kind == _DIGIT_SUB else f"{main}-{chr(sub)}"


def parse_ho_text(text: str | None) -> list[str]:
    """문자열 하나에서 호 번호 목록을 읽는다."""
    if not text:
        return []
    listings = _HO.findall(text) + _AFTER_FLOOR.findall(text)
    keys = {_key(raw) for listing in listings for raw in _ITEM.findall(listing)}
    # 본번이 0인 "0호"·"00호"는 오입력으로 보고 버린다 (층 파서의 `0층`과 같다)
    return [_format(key) for key in sorted(keys) if key[0] != 0]


def parse_ho(tail: str | None, road_detail: str | None) -> HoResult:
    """`tail`에서 먼저 찾고, 없으면 `road_detail`. 둘이 다르면 `tail` 목록을 쓴다."""
    from_tail = parse_ho_text(tail)
    from_road = parse_ho_text(road_detail)
    if from_tail:
        return HoResult(from_tail, "jibun_tail", bool(from_road) and from_road != from_tail)
    if from_road:
        return HoResult(from_road, "road_detail", False)
    return HoResult([], None, False)
