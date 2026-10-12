"""호 파서 (docs/10 §4)."""

import pytest

from app.location.normalize.ho_parser import HoResult, parse_ho, parse_ho_text

# docs/10 §4 테스트 케이스 표의 문자열 하나짜리 전부
DOC_CASES = [
    ("2층 206호", ["206"]),
    ("1층 124, 134,135", ["124", "134", "135"]),
    ("가동 101호", ["101"]),
    ("B101호", ["101"]),
    ("0101호", ["101"]),
    ("205동 101,102호", ["101", "102"]),
    ("2층 201-5호", ["201-5"]),
    ("109,109-1,113호", ["109", "109-1", "113"]),
    ("1단지-상가3동 1층 3-01호", ["3-1"]),
    ("잠실역2호선", []),
    ("2호선 건대입구역 2층 212-010호", ["212-10"]),
    ("인왕시장 3호동 1층 6호", ["6"]),
    ("야구장내 1호점", []),
    ("국민대학교 3동 2호관 1층", []),
    ("당산빌딩 지하1층 113호실", ["113"]),
    ("잠실지하상가 D-12호", ["12"]),
    ("214~215호", ["215"]),
]

# 규칙 경계 (문서 표에 없는 것)
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
    ("3층 1,2호", ["1", "2"]),
    ("지하층 105,106", ["105", "106"]),
    ("1층 124", []),
    ("1층 12, 13", []),
    ("1층 10255,10256", []),
    ("101,102,103", []),
    ("0호", []),
    ("0-1호", []),
    ("1층 0101,0102", ["101", "102"]),
    ("102호 101-2호 101호 101-1호 1002호", ["101", "101-1", "101-2", "102", "1002"]),
    ("101-5호, 102-5호", ["101-5", "102-5"]),
    ("201-5호 201호", ["201", "201-5"]),
    ("24-25-26호", []),
    ("B201,B202,B203호", ["203"]),
    ("지하1층 20.21호", ["21"]),
    ("지하29,30 호동", []),
    ("2 호선 가상역", []),
    ("동양미래대학교 3호관동 1층", []),
    ("지하 243-6호점", []),
    ("17호동 18호호", ["18"]),
    ("지하1층 b101호 10호", ["10", "101"]),
]


@pytest.mark.parametrize(("text", "expected"), DOC_CASES)
def test_doc_table(text: str, expected: list[str]) -> None:
    assert parse_ho_text(text) == expected


@pytest.mark.parametrize(("text", "expected"), EXTRA_CASES)
def test_rule_boundaries(text: str | None, expected: list[str]) -> None:
    assert parse_ho_text(text) == expected


# docs/10 §4 테스트 케이스 표의 tail / road_detail 쌍
def test_same_list_is_not_conflict() -> None:
    assert parse_ho("태평양물산 1층 103호,104호", "1층 103,104호") == HoResult(
        ["103", "104"], "jibun_tail", False
    )


def test_conflict_keeps_tail() -> None:
    assert parse_ho("양지빌딩 1012호", "1층 102호") == HoResult(["1012"], "jibun_tail", True)


def test_falls_back_to_road_detail() -> None:
    assert parse_ho("잠실역2호선", "216-105호 (신천동)") == HoResult(
        ["216-105"], "road_detail", False
    )


def test_tail_only() -> None:
    assert parse_ho("가상상가 B11호", "") == HoResult(["11"], "jibun_tail", False)


def test_no_ho() -> None:
    assert parse_ho("가상상가 1층", None) == HoResult([], None, False)
    assert parse_ho(None, "") == HoResult([], None, False)
