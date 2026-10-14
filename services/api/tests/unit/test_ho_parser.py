"""호 파서 (docs/10 §4)."""

import json
from pathlib import Path
from typing import Any

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
    ("지1층 B132-A호", ["132-A"]),
    ("101-b호 101-A호 101-2호 101호 102호", ["101", "101-2", "101-A", "101-B", "102"]),
    ("지하1층 20.21호", ["20", "21"]),
    ("지하 6.10.11.12호", ["6", "10", "11", "12"]),
    ("104.1호", ["104-1"]),
    ("214~215호", ["215"]),
    ("지하29,30 호동", []),
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
    ("101-A,101-B,102-A,102-B호", ["101-A", "101-B", "102-A", "102-B"]),
    ("중앙대병원 B101-B호", ["101-B"]),
    ("101-AB호", []),
    ("101B호", []),
    ("A동 109.110호", ["109", "110"]),
    ("1.2.3.4.5.6.11호", ["1", "2", "3", "4", "5", "6", "11"]),
    ("105 . 6호", ["105-6"]),
    ("12.3호", ["3", "12"]),
    ("104.12호", ["12", "104"]),
    ("102.3.201호", ["102-3", "201"]),
    ("104.1호 104-1호", ["104-1"]),
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


# 실제 데이터 20건 (T-013). 기대값은 파서 결과를 보지 않고 실제 호실 기준으로 썼다.
# 작성자는 건별 `labeled_by` — 17건은 채팅 Claude, 사람이 쓴 라벨이 아니다(docs/50 §1).
# 추출: `jobs.sample_ho_cases` (seed·모집단은 파일에 기록)
REAL_FILE = json.loads(
    (Path(__file__).parent / "data" / "ho_real_cases.json").read_text(encoding="utf-8")
)
REAL_CASES = REAL_FILE["cases"]


def _parsed(case: dict[str, Any]) -> list[str]:
    return parse_ho(case["tail"], case["road_detail"]).ho_list


def test_real_cases_are_all_labeled() -> None:
    assert len(REAL_CASES) == 20
    assert sum(case["stratum"] == "tricky" for case in REAL_CASES) == 10
    assert all(isinstance(case["expected"], list) and case["labeled_by"] for case in REAL_CASES)


def test_label_sources_match_file_summary() -> None:
    """라벨 출처를 숨기지 않는다: 파일 설명과 건별 `labeled_by`의 건수가 같다."""
    by_claude = [case for case in REAL_CASES if case["labeled_by"].startswith("채팅 Claude(")]
    by_user = [case for case in REAL_CASES if case["labeled_by"] == "사용자"]
    assert (len(by_claude), len(by_user)) == (17, 2)
    assert REAL_FILE["labeled_by_summary"].startswith("20건 중 17건은 채팅 Claude")


def test_real_cases_summary() -> None:
    """실제 데이터 20건 중 정답 일치 19건, 알려진 한계 1건."""
    matched = [case["no"] for case in REAL_CASES if _parsed(case) == case["expected"]]
    known_limits = [case["no"] for case in REAL_CASES if "known_limit" in case]
    assert (len(matched), known_limits) == (19, [7])


@pytest.mark.parametrize("case", REAL_CASES, ids=lambda case: f"real-{case['no']:02d}")
def test_real_cases(case: dict[str, Any]) -> None:
    if "known_limit" in case:
        # 알려진 한계: 기대값(실제 호실)은 그대로 두고 지금의 파서 결과를 확인한다.
        # 규칙을 고쳐 정답을 내게 되면 이 테스트가 깨져서 `known_limit`을 지우라고 알려 준다
        assert case["known_limit"]
        assert case["parser_output"] != case["expected"]
        assert _parsed(case) == case["parser_output"]
    else:
        assert _parsed(case) == case["expected"]
