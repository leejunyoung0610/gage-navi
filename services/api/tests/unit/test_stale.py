"""미갱신 의심 탐지 (docs/10 §6). 업소 이름·필지·면적은 모두 가상 예시다."""

from datetime import date
from decimal import Decimal

import pandas as pd
import pytest

from app.location.normalize.stale import detect_stale, normalize_name, same_business


def record(
    number: int,
    name: str,
    opened: str | None,
    *,
    status: str = "open",
    ho: tuple[str, ...] = (),
    area: str | None = None,
    pnu: str | None = "P1",
    floor: str | None = "1",
    no_fixed_place: bool = False,
) -> dict[str, object]:
    return {
        "id": number,
        "name": name,
        "status": status,
        "opened_on": None if opened is None else date.fromisoformat(opened),
        "area_m2": None if area is None else Decimal(area),
        "pnu": pnu,
        "floor": floor,
        "ho_list": list(ho),
        "no_fixed_place": no_fixed_place,
    }


def flags(rows: list[dict[str, object]]) -> dict[int, tuple[bool, bool]]:
    result = detect_stale(pd.DataFrame(rows))
    return {
        int(row["id"]): (bool(row["same_ho"]), bool(row["same_area"]))
        for row in result.flags.to_dict("records")
    }


def test_same_ho_same_area_and_neither() -> None:
    rows = [
        # 같은 호: 1(영업 중) 뒤에 같은 101호로 2가 개업
        record(1, "가상분식", "2010-01-01", ho=("101",), area="30.00", pnu="P1"),
        record(2, "가상카페", "2015-01-01", ho=("101", "102"), area="80.00", pnu="P1"),
        # 같은 면적만: 호는 다르고 면적 차이 1% 이내 (100.00 vs 101.00, 큰 쪽의 1%는 1.01)
        record(3, "가상국밥", "2010-01-01", ho=("201",), area="100.00", pnu="P2"),
        record(4, "가상치킨", "2015-01-01", ho=("202",), area="101.00", pnu="P2", status="closed"),
        # 둘 다: 같은 호이고 면적도 같다
        record(5, "가상김밥", "2010-01-01", ho=("1",), area="33.00", pnu="P3"),
        record(6, "가상우동", "2015-01-01", ho=("1",), area="33.00", pnu="P3"),
        # 둘 다 아님: 호가 다르고 면적 차이가 1%를 넘는다 (100.00 vs 101.02, 큰 쪽의 1%는 1.0102)
        record(7, "가상족발", "2010-01-01", ho=("301",), area="100.00", pnu="P4"),
        record(8, "가상보쌈", "2015-01-01", ho=("302",), area="101.02", pnu="P4"),
    ]
    assert flags(rows) == {1: (True, False), 3: (False, True), 5: (True, True)}


def test_only_open_records_with_a_later_opening_are_flagged() -> None:
    rows = [
        record(1, "가상분식", "2015-01-01", ho=("101",)),  # 나중에 연 쪽은 표시하지 않는다
        record(2, "가상카페", "2010-01-01", ho=("101",), status="closed"),  # 폐업 기록은 대상 아님
        record(3, "가상국밥", "2010-01-01", ho=("7",), pnu="P2"),
        record(4, "가상치킨", "2010-01-01", ho=("7",), pnu="P2"),  # 같은 날 개업 → "나중"이 아니다
    ]
    assert flags(rows) == {}


def test_floor_key_and_scope() -> None:
    rows = [
        record(1, "가상분식", "2010-01-01", ho=("101",), floor="1"),
        record(2, "가상카페", "2015-01-01", ho=("101",), floor="2"),  # 층이 다르다
        record(3, "가상국밥", "2010-01-01", ho=("101",), pnu="P2"),
        record(4, "가상치킨", "2015-01-01", ho=("101",), pnu="P3"),  # 필지가 다르다
        record(5, "가상김밥", "2010-01-01", ho=("5",), pnu=None),  # 층키 없음
        record(6, "가상우동", "2015-01-01", ho=("5",), pnu=None),
        record(7, "가상족발", "2010-01-01", ho=("6",), pnu="P4"),
        record(8, "가상트럭", "2015-01-01", ho=("6",), pnu="P4", no_fixed_place=True),
        record(9, "가상보쌈", None, ho=("9",), pnu="P5"),  # 개업일 없음
        record(10, "가상냉면", "2015-01-01", ho=("9",), pnu="P5"),
    ]
    assert flags(rows) == {}


def test_area_needs_both_positive() -> None:
    rows = [
        record(1, "가상분식", "2010-01-01", area="0.00"),
        record(2, "가상카페", "2015-01-01", area="0.00"),
        record(3, "가상국밥", "2010-01-01", area=None, pnu="P2"),
        record(4, "가상치킨", "2015-01-01", area="50.00", pnu="P2"),
        record(5, "가상김밥", "2010-01-01", ho=(), pnu="P3"),  # 호가 둘 다 없으면 겹침이 아니다
        record(6, "가상우동", "2015-01-01", ho=(), pnu="P3"),
    ]
    assert flags(rows) == {}


def test_same_business_pairs_are_excluded() -> None:
    rows = [
        # 한 가게가 같은 호에 휴게음식점과 제과점 기록을 함께 가진 경우
        record(1, "가상베이커리(Gasang)", "2020-01-01", ho=("101",), area="50.00", pnu="P1"),
        record(2, "가상 베이커리 (GASANG)", "2021-01-01", ho=("101",), area="50.00", pnu="P1"),
        # 한쪽이 다른 쪽을 포함
        record(3, "가상화로 본점", "2020-01-01", ho=("7",), pnu="P2"),
        record(4, "주식회사 가상화로", "2021-01-01", ho=("7",), pnu="P2"),
        # 같은 이름 쌍은 빠지지만, 이름이 다른 뒤 기록이 하나 더 있으면 표시된다
        record(5, "가상국밥", "2020-01-01", ho=("9",), pnu="P3"),
        record(6, "가상국밥", "2021-01-01", ho=("9",), pnu="P3", status="closed"),
        record(7, "가상치킨", "2022-01-01", ho=("9",), pnu="P3"),
        # 지점 이름만 같은 다른 가게는 빼지 않는다
        record(8, "가상김밥 가상플라자점", "2020-01-01", ho=("3",), pnu="P4"),
        record(9, "가상우동 가상플라자점", "2021-01-01", ho=("3",), pnu="P4"),
    ]
    result = detect_stale(pd.DataFrame(rows))
    assert {int(i) for i in result.flags["id"]} == {5, 8}
    # 쌍: (1,2) (3,4) (5,6) (5,7) (8,9) + 6은 폐업이라 A가 아님 → 같은 호 쌍 5개 중 3개가 같은 가게
    assert (result.ho_pairs, result.ho_pairs_same_name) == (5, 3)
    assert (result.area_pairs, result.area_pairs_same_name) == (1, 1)
    assert (result.ho_records_before, len(result.flags)) == (4, 2)
    assert result.candidates == 8 and result.later_pairs == 5


@pytest.mark.parametrize(
    ("a", "b", "expected"),
    [
        ("가상식당", "가상식당", True),
        ("가상 식당", "가상식당", True),
        ("(주)가상식당", "주식회사 가상식당", True),
        ("Gasang Cafe", "GASANG-CAFE", True),
        ("가상식당 본점", "가상식당", True),
        ("소서(SOSEO)", "소서", True),
        ("가상김밥 가상점", "가상우동 가상점", False),
        ("가", "가상식당", False),  # 한 글자는 포함 관계로 보지 않는다
        ("", "", False),
        ("(주)", "가상식당", False),
    ],
)
def test_same_business(a: str, b: str, expected: bool) -> None:
    assert same_business(a, b) is expected
    assert same_business(b, a) is expected


def test_normalize_name() -> None:
    assert normalize_name(" ㈜ 가상-식당 (Gasang) ") == "가상식당gasang"


def test_no_records() -> None:
    empty = pd.DataFrame(
        columns=[
            "id",
            "name",
            "status",
            "opened_on",
            "area_m2",
            "pnu",
            "floor",
            "ho_list",
            "no_fixed_place",
        ]
    )
    result = detect_stale(empty)
    assert result.flags.empty and result.candidates == 0
