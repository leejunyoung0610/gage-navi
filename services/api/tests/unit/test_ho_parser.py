"""호 파서 (docs/10 §4)."""

import pytest

from app.location.normalize.ho_parser import parse_ho_text

# docs/10 §4 사례 전부 + 정규화 예시
DOC_CASES = [
    ("2층 206호", ["206"]),
    ("1층 124, 134,135", ["124", "134", "135"]),
    ("가동 101호", ["101"]),
    ("B101호", ["101"]),
    ("0101호", ["101"]),
]

# 규칙 경계 (문서 사례에 없는 것)
EXTRA_CASES = [
    (None, []),
    ("", []),
    ("크레신타워3차", []),
    ("1층", []),
    ("101 호", ["101"]),
    ("1층 103호,104호", ["103", "104"]),
    ("2층 206호 (자양동, 이튼타워리버1차)", ["206"]),
    ("제지2층 제비201호", ["201"]),
    ("지1층 1호 (상수동)", ["1"]),
    ("B01호, B02호", ["1", "2"]),
    ("1002호 101호 101호", ["101", "1002"]),
    ("프라임 상가 1층 124, 134,135", ["124", "134", "135"]),
    ("1층 101, 102, 103호", ["101", "102", "103"]),
    ("지하층 105,106", ["105", "106"]),
    ("1층 124", []),
    ("1층 12, 13", []),
    ("1층 10255,10256", []),
    ("101,102,103", []),
    ("0호", []),
    ("1층 0101,0102", ["101", "102"]),
]


@pytest.mark.parametrize(("text", "expected"), DOC_CASES)
def test_doc_cases(text: str, expected: list[str]) -> None:
    assert parse_ho_text(text) == expected


@pytest.mark.parametrize(("text", "expected"), EXTRA_CASES)
def test_rule_boundaries(text: str | None, expected: list[str]) -> None:
    assert parse_ho_text(text) == expected
