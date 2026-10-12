"""층 파서 (docs/10 §3)."""

import json
from pathlib import Path
from typing import Any

import pytest

from app.location.normalize.floor_parser import (
    FloorResult,
    floor_sort_key,
    parse_floor,
    parse_floor_text,
    road_detail,
)

# docs/10 §3 테스트 케이스 표 전부
DOC_CASES = [
    (" 1층", "1"),
    ("롯데백화점스타시티점 지상10층", "10"),
    ("롯데백화점스타시티점 지하1층", "B1"),
    ("(1층)", "1"),
    ("프라임 상가 1층 124, 134,135", "1"),
    ("2층 206호 (자양동, 이튼타워리버1차)", "2"),
    ("지층", "B1"),
    ("지하층 일부", "B1"),
    ("B1", "B1"),
    ("B2층", "B2"),
    ("상가B1층", "B1"),
    ("B101호", None),
    ("1F", "1"),
    ("제1층", "1"),
    ("지하 2 층", "B2"),
    ("1~2층", "1"),
    ("2,3층", "2"),
    ("1-2층", "1"),
    ("3-1동 2층", "2"),
    ("크레신타워3차", None),
    ("0층", None),
    ("지1층 1호 (상수동)", "B1"),
    ("제지2층 제비201호", "B2"),
    ("외3필지 3층", "3"),
    ("2단지 1층", "1"),
    ("성우빌딩지1층3호", "1"),
    ("옥탑", "RF"),
    ("", None),
]

# 규칙 경계 (문서 표에 없는 것)
EXTRA_CASES = [
    (None, None),
    ("옥상", "RF"),
    ("b1", "B1"),
    ("2f", "2"),
    ("B1F", "B1"),
    ("B 2", "B2"),
    ("B1호", None),
    ("B12호", None),
    ("ABC1", None),
    ("100층", None),
    ("99층", "99"),
    ("지하0층", None),
    ("지하10층", None),
    ("지하9층", "B9"),
    ("B0", None),
    ("B10", None),
    ("3~2층", "2"),
    ("0~1층", None),
    ("지하1층~2층", "B1"),
    ("1층 옥탑", "1"),
    ("101호", None),
    ("지 2 층", "B2"),
    ("제 지1층", "B1"),
    ("(지1층)", "B1"),
    ("번지 2층", "2"),
    ("빌리지1층101호", "1"),
    ("지0층", None),
    ("지10층", None),
]


@pytest.mark.parametrize(("text", "expected"), DOC_CASES)
def test_doc_table(text: str, expected: str | None) -> None:
    assert parse_floor_text(text) == expected


@pytest.mark.parametrize(("text", "expected"), EXTRA_CASES)
def test_rule_boundaries(text: str | None, expected: str | None) -> None:
    assert parse_floor_text(text) == expected


def test_tail_first() -> None:
    assert parse_floor("상가 1층", "1층 101호") == FloorResult("1", "jibun_tail", False)


def test_falls_back_to_road_detail() -> None:
    assert parse_floor("크레신타워3차", "2층 206호") == FloorResult("2", "road_detail", False)


def test_conflict_keeps_tail() -> None:
    assert parse_floor("지하1층", "1층") == FloorResult("B1", "jibun_tail", True)


def test_out_of_range_tail_falls_back() -> None:
    assert parse_floor("0층", "1층") == FloorResult("1", "road_detail", False)


def test_no_floor() -> None:
    assert parse_floor("101호", None) == FloorResult(None, None, False)
    assert parse_floor(None, "") == FloorResult(None, None, False)


@pytest.mark.parametrize(
    ("road_addr", "expected"),
    [
        (
            "서울특별시 광진구 가상로 1, 2층 206호 (자양동, 이튼타워리버1차)",
            "2층 206호 (자양동, 이튼타워리버1차)",
        ),
        ("서울특별시 광진구 가상로 1 (자양동)", ""),
        ("", ""),
        (None, ""),
    ],
)
def test_road_detail(road_addr: str | None, expected: str) -> None:
    assert road_detail(road_addr) == expected


def test_sort_order() -> None:
    floors = ["RF", "2", "B1", "10", "B9", "1"]
    assert sorted(floors, key=floor_sort_key) == ["B9", "B1", "1", "2", "10", "RF"]


# 실제 데이터 40건 (T-012). 기대값은 사용자가 파서 결과를 보지 않고 썼다.
# 추출: `jobs.sample_floor_cases` (seed·모집단은 파일에 기록)
REAL_CASES = json.loads(
    (Path(__file__).parent / "data" / "floor_real_cases.json").read_text(encoding="utf-8")
)["cases"]


def test_real_cases_are_all_labeled() -> None:
    assert len(REAL_CASES) == 40
    assert sum(case["stratum"] == "tricky" for case in REAL_CASES) == 20


@pytest.mark.parametrize("case", REAL_CASES, ids=lambda case: f"real-{case['no']:02d}")
def test_real_cases(case: dict[str, Any]) -> None:
    assert parse_floor(case["tail"], case["road_detail"]).floor == case["expected"]
