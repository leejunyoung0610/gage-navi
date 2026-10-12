"""좌표계 후보 비교표 (T-014). 좌표·주소는 가상 예시다."""

from jobs.crs_candidates import SAMPLE_SIZE, Row, kakao_link, pick_sample


def _rows() -> list[Row]:
    return [
        Row(
            mgmt_no=f"가상-{gu:02d}-{n}",
            name=f"가상 가게{n}",
            gu=f"가상{gu:02d}구",
            road_addr="가상 예시 도로명주소",
            is_open=True,
            x=200000.0 + gu,
            y=450000.0 + n,
        )
        for gu in range(25)
        for n in range(3)
    ]


def test_sample_has_one_record_per_gu() -> None:
    sample = pick_sample(_rows())
    assert len(sample) == SAMPLE_SIZE
    assert len({row.gu for row in sample}) == SAMPLE_SIZE


def test_sample_does_not_depend_on_input_order() -> None:
    rows = _rows()
    assert pick_sample(rows) == pick_sample(rows[::-1])


def test_sample_skips_closed_and_link_unsafe_names() -> None:
    rows = _rows()
    extra = [
        Row("가상-폐업", "가상 폐업 가게", "가상00구", "가상 예시 도로명주소", False, 1.0, 1.0),
        Row("가상-쉼표", "가상,가게", "가상00구", "가상 예시 도로명주소", True, 1.0, 1.0),
        Row("가상-무주소", "가상 가게", "가상00구", "", True, 1.0, 1.0),
    ]
    picked = {row.mgmt_no for row in pick_sample(rows + extra)}
    assert not picked & {row.mgmt_no for row in extra}


def test_kakao_link_encodes_name_and_keeps_lat_lng_order() -> None:
    assert kakao_link("가 게", 37.5, 127.0) == (
        "https://map.kakao.com/link/map/%EA%B0%80%20%EA%B2%8C,37.500000,127.000000"
    )
