"""인허가 원본 행 정규화 (T-016). 업소·주소·관리번호·법정동코드는 모두 가상 예시다."""

from datetime import date
from decimal import Decimal

import pandas as pd
import pytest

from app.address.pnu import LegalDongIndex
from app.location.normalize.records import (
    LICENSE_TYPE,
    SNAPSHOT_ID,
    SOURCE_COLUMNS,
    normalize,
    parse_area,
    parse_date,
)

INDEX = LegalDongIndex.from_rows(
    [
        ("1121510700", "서울특별시 광진구 화양동", False),
        ("1144012000", "서울특별시 마포구 서교동", False),
    ]
)
# ADR-026 표본과 같은 좌표계(EPSG:5174)의 값: 서울 안, 그리고 경계 상자 밖(남쪽으로 100km)
INSIDE = ("205000.0", "450000.0")
OUTSIDE = ("205000.0", "350000.0")


def row(number: int, **values: str) -> dict[str, object]:
    base = {
        "개방자치단체코드": "3040000",
        "관리번호": f"3040000-101-2020-{number:05d}",
        "인허가일자": "2010-01-02",
        "영업상태명": "영업/정상",
        "폐업일자": "",
        "소재지면적": "33.50",
        "사업장명": f"가상식당{number}",
        "업태구분명": "한식",
        "지번주소": "서울특별시 광진구 화양동 1-1 가상상가 1층 101호",
        "도로명주소": "서울특별시 광진구 가상로 1, 1층 101호 (화양동)",
        "좌표정보(X)": INSIDE[0],
        "좌표정보(Y)": INSIDE[1],
        "데이터갱신시점": "2026-10-01 10:00:00",
        LICENSE_TYPE: "general_restaurant",
        SNAPSHOT_ID: 1,
    }
    assert set(values) <= set(base)
    return base | values


def frame(rows: list[dict[str, object]]) -> pd.DataFrame:
    return pd.DataFrame(rows, columns=[SNAPSHOT_ID, LICENSE_TYPE, *SOURCE_COLUMNS])


def one(result_frame: pd.DataFrame, number: int) -> dict[str, object]:
    matched = result_frame[result_frame["mgmt_no"].str.endswith(f"{number:05d}")]
    assert len(matched) == 1
    record: dict[str, object] = matched.iloc[0].to_dict()
    return record


def test_fields_of_a_plain_record() -> None:
    result = normalize(frame([row(1)]), INDEX)
    record = one(result.records, 1)
    assert record["status"] == "open" and record["status_raw"] == "영업/정상"
    assert record["opened_on"] == date(2010, 1, 2) and record["closed_on"] is None
    assert record["area_m2"] == Decimal("33.50")
    assert record["pnu"] == "1121510700100010001" and record["sigungu_code"] == "11215"
    assert (record["floor"], record["floor_source"], record["ho_list"]) == (
        "1",
        "jibun_tail",
        ["101"],
    )
    assert str(record["geom_ewkt"]).startswith("SRID=4326;POINT(127.")
    assert not record["bulk_closure"] and not record["no_fixed_place"]
    assert record["biz_category"] == "한식" and record["last_snapshot_id"] == 1
    stat = result.stats["general_restaurant"]
    assert (stat.input_rows, stat.seoul_rows, stat.records, stat.opened_on_parsed) == (1, 1, 1, 1)
    assert (stat.pnu_failed, stat.with_coords, stat.coords_outside) == (0, 1, 0)
    assert stat.status_counts == {"영업/정상": 1} and stat.category_counts == {"한식": 1}


def test_scope_exclusions() -> None:
    rows = [
        row(1),
        # 서울 밖 주소 → 제외
        row(2, 지번주소="경기도 수원시 영통구 원천동 3-3", 도로명주소="경기도 수원시 가상로 3"),
        # 지번주소가 비어도 도로명주소가 서울이면 남는다 (PNU는 실패)
        row(3, 지번주소="", 도로명주소="서울특별시 광진구 가상로 3, 2층"),
        # 고정된 자리가 없는 업태 → 남기되 표시
        row(4, 업태구분명="푸드트럭"),
        row(5, 업태구분명="이동조리"),
        # 편의점·출장조리는 표시하지 않는다 (업태는 그대로 보존)
        row(6, 업태구분명="편의점"),
        row(7, 업태구분명="출장조리"),
        row(8, 업태구분명=""),
    ]
    result = normalize(frame(rows), INDEX)
    stat = result.stats["general_restaurant"]
    assert (stat.input_rows, stat.non_seoul_excluded, stat.records) == (8, 1, 7)
    assert set(result.records["mgmt_no"].str[-1]) == set("1345678")
    flagged = result.records[result.records["no_fixed_place"]]
    assert set(flagged["biz_category"]) == {"푸드트럭", "이동조리"} and stat.no_fixed_place == 2
    assert one(result.records, 6)["biz_category"] == "편의점"
    assert one(result.records, 8)["biz_category"] is None
    third = one(result.records, 3)
    assert third["pnu"] is None and third["sigungu_code"] is None and third["jibun_addr"] is None
    assert (third["floor"], third["floor_source"]) == ("2", "road_detail")
    assert (stat.pnu_failed, stat.pnu_failures) == (1, {"regex_mismatch": 1})


def test_status_dates_and_checks() -> None:
    rows = [
        row(1, 영업상태명="폐업", 폐업일자="2015-03-04"),
        row(2, 영업상태명="폐업", 폐업일자=""),  # DV10: 폐업인데 폐업일자 없음
        row(3, 영업상태명="폐업", 폐업일자="2009-12-31"),  # DV4: 날짜 역전 → 격리
        row(4, 영업상태명="휴업"),
        row(5, 영업상태명="직권말소"),  # DV5: 표에 없는 값
        row(6, 인허가일자="2010-13-45"),  # DV3: 없는 날짜
        row(7, 인허가일자="1999-05-05"),
        row(8, 관리번호="3040000-101-2020-00001"),  # DV2: 관리번호 중복
        row(9, 지번주소="서울특별시 광진구 없는동 9-9", 도로명주소=""),  # DV6: 동 조회 실패
    ]
    result = normalize(frame(rows), INDEX)
    stat = result.stats["general_restaurant"]
    assert one(result.records, 2)["closed_on"] is None
    assert one(result.records, 4)["status"] == "suspended"
    assert one(result.records, 5)["status"] is None
    assert one(result.records, 6)["opened_on"] is None
    assert stat.duplicate_mgmt_no == 1
    assert stat.unknown_status == {"직권말소": 1}
    assert (stat.opened_on_parsed, stat.seoul_rows) == (8, 9)
    assert (stat.date_inversion, stat.records) == (1, 8)
    assert not result.records["mgmt_no"].str.endswith("00003").any()
    assert (stat.closed, stat.closed_without_date) == (3, 1)
    assert (stat.pnu_failed, stat.pnu_failures) == (1, {"dong_not_found": 1})
    # DV7: 2005년 이후 개업 7건(1999년 개업과 날짜 오류 제외) 중 층이 있는 것 6건
    assert (stat.since_2005, stat.since_2005_with_floor) == (7, 6)


def test_conflicts_and_coordinates() -> None:
    rows = [
        row(1, 지번주소="서울특별시 광진구 화양동 1-1 지하1층 102호"),  # 층·호 모두 도로명과 다름
        row(2, **{"좌표정보(X)": "", "좌표정보(Y)": ""}),
        row(3, **{"좌표정보(X)": OUTSIDE[0], "좌표정보(Y)": OUTSIDE[1]}),
        row(4, **{"좌표정보(X)": "가상", "좌표정보(Y)": "1"}),
    ]
    result = normalize(frame(rows), INDEX)
    stat = result.stats["general_restaurant"]
    first = one(result.records, 1)
    assert (first["floor"], first["ho_list"]) == ("B1", ["102"])
    assert (stat.floor_conflict, stat.ho_conflict) == (1, 1)
    assert one(result.records, 2)["geom_ewkt"] is None
    assert one(result.records, 4)["geom_ewkt"] is None
    assert (stat.with_coords, stat.coords_outside) == (2, 1)


def test_surge_days_across_license_types() -> None:
    rows = []
    for day in range(1, 5):  # 평소: 하루 2건
        for _ in range(2):
            rows.append(
                row(
                    len(rows) + 1,
                    영업상태명="폐업",
                    폐업일자=f"2020-03-0{day}",
                    개방자치단체코드="3130000",
                    지번주소="서울특별시 마포구 서교동 2-2 1층",
                )
            )
    for number in range(30):  # 급증일: 일반 20건 + 휴게 10건 = 30건 (3종 합산)
        kind = "general_restaurant" if number < 20 else "rest_restaurant"
        rows.append(
            row(
                len(rows) + 1,
                영업상태명="폐업",
                폐업일자="2020-03-09",
                개방자치단체코드="3130000",
                지번주소="서울특별시 마포구 서교동 2-2 1층",
            )
            | {LICENSE_TYPE: kind}
        )
    rows.append(row(len(rows) + 1, 폐업일자="2020-03-09", 개방자치단체코드="3130000"))  # 영업 중
    result = normalize(frame(rows), INDEX)
    assert result.surge_days.to_dict("records") == [
        {
            "jurisdiction_code": "3130000",
            "closed_on": date(2020, 3, 9),
            "jurisdiction_label": "마포구",
            "closure_count": 30,
            "median": 2.0,
        }
    ]
    assert (result.surge_cells, result.surge_dates) == (1, 1)
    assert int(result.records["bulk_closure"].sum()) == 30
    assert result.stats["general_restaurant"].surge_records == 20
    assert result.stats["rest_restaurant"].surge_records == 10


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("2020-01-02", date(2020, 1, 2)),
        (" 2020-01-02 ", date(2020, 1, 2)),
        ("", None),
        ("2020-02-30", None),
        ("20200102", None),
        ("2020-1-2", None),
    ],
)
def test_parse_date(value: str, expected: date | None) -> None:
    assert parse_date(value) == expected


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("74.38", Decimal("74.38")),
        ("1,367.33", Decimal("1367.33")),
        ("33", Decimal("33.00")),
        ("0", Decimal("0.00")),
        ("12.345", Decimal("12.35")),
        ("", None),
        ("-1", None),
        ("약 30", None),
        ("NaN", None),
        ("100000000", None),
    ],
)
def test_parse_area(value: str, expected: Decimal | None) -> None:
    assert parse_area(value) == expected
