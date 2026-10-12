"""층 파서 속성: 결과는 `None` 또는 정규화 값 (docs/10 §3, T-012 수용 기준)."""

import re

from hypothesis import given
from hypothesis import strategies as st

from app.location.normalize.floor_parser import parse_floor, parse_floor_text

FLOOR = re.compile(r"^(B[1-9]|[1-9][0-9]?|RF)$")

# 규칙에 걸리는 글자를 자주 섞는다
_PIECES = st.sampled_from(
    [
        "지하",
        "지층",
        "지상",
        "제",
        "층",
        "호",
        "옥탑",
        "옥상",
        "B",
        "b",
        "F",
        "f",
        "~",
        ",",
        "-",
        " ",
    ]
)
_TEXT = st.lists(
    st.one_of(_PIECES, st.integers(0, 1200).map(str), st.text(max_size=3)), max_size=8
).map("".join)


@given(_TEXT)
def test_text_result_is_normalized(text: str) -> None:
    result = parse_floor_text(text)
    assert result is None or FLOOR.fullmatch(result)


@given(_TEXT, _TEXT)
def test_result_is_normalized(tail: str, detail: str) -> None:
    result = parse_floor(tail, detail)
    assert result.floor is None or FLOOR.fullmatch(result.floor)
    assert (result.floor is None) == (result.source is None)
    if result.conflict:
        assert result.source == "jibun_tail"
