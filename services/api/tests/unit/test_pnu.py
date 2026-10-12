"""지번주소 → PNU (docs/10 §2.1).

여기의 법정동코드는 모두 가상 예시다(99로 시작). 실제 코드는 `legal_dong` 테이블에만 있다.
"""

import pytest

from app.address.pnu import (
    FAIL_AMBIGUOUS,
    FAIL_DONG_NOT_FOUND,
    FAIL_REGEX_MISMATCH,
    JibunParts,
    LegalDongIndex,
    build_pnu,
    parse_jibun,
    to_pnu,
)

# 가상 예시 코드
HWAYANG = "9921510500"
GWANGJANG = "9921510400"
EULJIRO3 = "9914012300"
JONGNO1 = "9911012600"
JAYANG = "9921510300"
GUUI = "9921510200"
GUNJA = "9921510100"

INDEX = LegalDongIndex.from_rows(
    [
        (HWAYANG, "서울특별시 광진구 화양동", False),
        (GWANGJANG, "서울특별시 광진구 광장동", False),
        (EULJIRO3, "서울특별시 중구 을지로3가", False),
        (JONGNO1, "서울특별시 종로구 종로1가", False),
        (JAYANG, "서울특별시 광진구 자양동", False),
        (GUUI, "서울특별시 광진구 구의동", False),
        (GUNJA, "서울특별시 광진구 군자동", False),
        # 현행 1 + 폐지 1 → 현행
        ("9930010100", "서울특별시 가상구 현행폐지동", False),
        ("9930010199", "서울특별시 가상구 현행폐지동", True),
        # 폐지만 1
        ("9930010200", "서울특별시 가상구 폐지동", True),
        # 현행 2
        ("9930010300", "서울특별시 가상구 중복동", False),
        ("9930010301", "서울특별시 가상구 중복동", False),
        # 폐지만 2
        ("9930010400", "서울특별시 가상구 폐지중복동", True),
        ("9930010401", "서울특별시 가상구 폐지중복동", True),
    ]
)


def pnu_of(addr: str) -> str | None:
    parts = parse_jibun(addr)
    assert parts is not None
    return to_pnu(parts, INDEX)


# --- docs/10 §2.1 표 ---


def test_doc_main_and_sub() -> None:
    assert pnu_of("서울특별시 광진구 화양동 47-1 ") == HWAYANG + "1" + "0047" + "0001"


def test_doc_sub_zero_is_0000() -> None:
    assert pnu_of("서울특별시 광진구 광장동 110-0") == GWANGJANG + "1" + "0110" + "0000"


def test_doc_san() -> None:
    assert pnu_of("서울특별시 광진구 광장동 산 21") == GWANGJANG + "2" + "0021" + "0000"


def test_doc_dong_name_with_digit_euljiro3ga() -> None:
    parts = parse_jibun("서울특별시 중구 을지로3가 296-1")
    assert parts is not None
    assert parts.dong == "을지로3가"
    assert to_pnu(parts, INDEX) == EULJIRO3 + "1" + "0296" + "0001"


def test_doc_dong_name_with_digit_jongno1ga() -> None:
    parts = parse_jibun("서울특별시 종로구 종로1가 24")
    assert parts is not None
    assert parts.dong == "종로1가"
    assert to_pnu(parts, INDEX) == JONGNO1 + "1" + "0024" + "0000"


def test_doc_tail_building_and_floor() -> None:
    parts = parse_jibun("서울특별시 광진구 자양동 227-342 롯데백화점스타시티점 지하1층")
    assert parts is not None
    assert parts.tail == "롯데백화점스타시티점 지하1층"
    assert to_pnu(parts, INDEX) == JAYANG + "1" + "0227" + "0342"


def test_doc_tail_with_commas() -> None:
    parts = parse_jibun("서울특별시 광진구 구의동 631-1 프라임 상가 1층 124, 134,135")
    assert parts is not None
    assert parts.tail == "프라임 상가 1층 124, 134,135"
    assert to_pnu(parts, INDEX) == GUUI + "1" + "0631" + "0001"


def test_doc_multiple_spaces_are_normalized() -> None:
    assert pnu_of("서울특별시  광진구   군자동 49-19") == GUNJA + "1" + "0049" + "0019"


# --- 추가: 파싱 ---


def test_parts_fields() -> None:
    assert parse_jibun("서울특별시 광진구 화양동 47-1") == JibunParts(
        sigungu="광진구", dong="화양동", is_san=False, main=47, sub=1, tail=""
    )


def test_san_without_space() -> None:
    parts = parse_jibun("서울특별시 광진구 광장동 산21-3")
    assert parts is not None
    assert (parts.is_san, parts.main, parts.sub) == (True, 21, 3)


def test_tab_and_newline_count_as_spaces() -> None:
    parts = parse_jibun("서울특별시\t광진구 화양동\n47-1  2층")
    assert parts is not None
    assert (parts.main, parts.sub, parts.tail) == (47, 1, "2층")


def test_tail_directly_after_number() -> None:
    parts = parse_jibun("서울특별시 광진구 화양동 47-1번지 1층")
    assert parts is not None
    assert (parts.main, parts.sub, parts.tail) == (47, 1, "번지 1층")


def test_leading_zeros_in_numbers() -> None:
    parts = parse_jibun("서울특별시 광진구 화양동 0047-0001")
    assert parts is not None
    assert (parts.main, parts.sub) == (47, 1)


def test_four_digit_main_and_sub_fit() -> None:
    assert pnu_of("서울특별시 광진구 화양동 9999-9999") == HWAYANG + "1" + "9999" + "9999"


@pytest.mark.parametrize(
    "addr",
    [
        "",
        "   ",
        "서울특별시 광진구 화양동",  # 번지 없음
        "서울특별시 광진구 화양동 일대",  # 번지 자리에 글자
        "경기도 성남시 분당구 정자동 178-1",  # 서울 아님
        # 지번 칸에 도로명: 정규식은 통과하고 조회에서 실패한다
        "서울특별시 광진구 능동로 120",
        "광진구 화양동 47-1",  # 시도 없음
        "서울특별시 광진구 화양동 12345-1",  # 본번 5자리
        "서울특별시 광진구 화양동 47-12345",  # 부번 5자리
    ],
)
def test_regex_mismatch_or_lookup_failure(addr: str) -> None:
    result = build_pnu(addr, INDEX)
    assert result.pnu is None
    assert result.failure in (FAIL_REGEX_MISMATCH, FAIL_DONG_NOT_FOUND)


def test_none_address_is_regex_mismatch() -> None:
    assert build_pnu(None, INDEX).failure == FAIL_REGEX_MISMATCH


def test_missing_number_is_regex_mismatch() -> None:
    assert build_pnu("서울특별시 광진구 화양동", INDEX).failure == FAIL_REGEX_MISMATCH


def test_overflowing_main_is_regex_mismatch() -> None:
    assert parse_jibun("서울특별시 광진구 화양동 12345-1") is None


def test_road_address_in_jibun_column_is_dong_not_found() -> None:
    result = build_pnu("서울특별시 광진구 능동로 120", INDEX)
    assert (result.pnu, result.failure) == (None, FAIL_DONG_NOT_FOUND)


# --- 추가: 법정동코드 조회 (같은 이름에 코드 여럿) ---


def test_unknown_dong_is_dong_not_found() -> None:
    result = build_pnu("서울특별시 광진구 없는동 1-1", INDEX)
    assert (result.pnu, result.failure) == (None, FAIL_DONG_NOT_FOUND)


def test_current_code_wins_over_abolished() -> None:
    result = build_pnu("서울특별시 가상구 현행폐지동 10-2", INDEX)
    assert result.pnu == "9930010100" + "1" + "0010" + "0002"
    assert result.failure is None
    assert result.abolished_only is False


def test_abolished_only_builds_pnu_and_is_flagged() -> None:
    result = build_pnu("서울특별시 가상구 폐지동 10-2", INDEX)
    assert result.pnu == "9930010200" + "1" + "0010" + "0002"
    assert result.failure is None
    assert result.abolished_only is True


def test_two_current_codes_are_ambiguous() -> None:
    result = build_pnu("서울특별시 가상구 중복동 10-2", INDEX)
    assert (result.pnu, result.failure) == (None, FAIL_AMBIGUOUS)


def test_two_abolished_codes_without_current_are_ambiguous() -> None:
    result = build_pnu("서울특별시 가상구 폐지중복동 10-2", INDEX)
    assert (result.pnu, result.failure) == (None, FAIL_AMBIGUOUS)


def test_to_pnu_returns_none_when_ambiguous() -> None:
    parts = parse_jibun("서울특별시 가상구 중복동 10-2")
    assert parts is not None
    assert to_pnu(parts, INDEX) is None


def test_pnu_is_always_19_digits() -> None:
    for addr in (
        "서울특별시 광진구 화양동 1",
        "서울특별시 광진구 광장동 산 9999-9999",
        "서울특별시 중구 을지로3가 296-1 지하1층",
    ):
        pnu = pnu_of(addr)
        assert pnu is not None
        assert len(pnu) == 19
        assert pnu.isdigit()
