"""호 파서 (docs/10 §4).

주소 문자열에서 호 번호를 읽어 `ho_list`(앞의 0 제거, 중복 제거, 숫자 오름차순)로 정규화한다.
호를 읽지 못하면 빈 목록.
"""

import re

# "206호", "B101호", "0101 호" — 숫자 뒤에 `호`가 붙은 모든 곳
_HO = re.compile(r"(\d+)\s*호")
# 층 바로 뒤 숫자 나열 "1층 124, 134,135" — `호`가 없어도 쉼표로 구분된 3~4자리 숫자 목록
_AFTER_FLOOR = re.compile(r"층\s*(\d{3,4}(?:\s*,\s*\d{3,4})+)(?!\d)")
_NUMBER = re.compile(r"\d+")


def parse_ho_text(text: str | None) -> list[str]:
    """문자열 하나에서 호 번호 목록을 읽는다."""
    if not text:
        return []
    found = _HO.findall(text)
    for listing in _AFTER_FLOOR.findall(text):
        found.extend(_NUMBER.findall(listing))
    # 앞의 0을 떼면 남는 것이 없는 "0호"·"00호"는 오입력으로 보고 버린다 (층 파서의 `0층`과 같다)
    numbers = {int(raw) for raw in found} - {0}
    return [str(n) for n in sorted(numbers)]
