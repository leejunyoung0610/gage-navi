"""법정동코드 파일 읽기 (docs/03 D3). 여기의 코드와 지명은 모두 가상 예시다(99로 시작)."""

from pathlib import Path

import pytest

from app.address.legal_dong_file import LegalDong, LegalDongFileError, read_file
from jobs import ingest_legal_dong

HEADER = "법정동코드,시도명,시군구명,읍면동명,리명,순번,생성일자"
LINES = [
    "9900000000,가상특별시,,,,1,1988-04-23",
    "9911000000,가상특별시,가상구,,,1,1988-04-23",
    "9911010100,가상특별시,가상구,가상동,,1,1995-03-01",
    "9980042027,가상도,가상시 가상구,가상면,가상리,7,2024-01-18",
]


def write(path: Path, lines: list[str] = LINES, *, header: str = HEADER, bom: bool = True) -> Path:
    body = "\r\n".join([header, *lines]) + "\r\n"
    path.write_bytes((b"\xef\xbb\xbf" if bom else b"") + body.encode("utf-8"))
    return path


def test_rows_are_read_with_bom_stripped(tmp_path: Path) -> None:
    dongs, created_on_max = read_file(write(tmp_path / "a.csv"))

    assert len(dongs) == 4
    assert dongs[2] == LegalDong(
        code="9911010100",
        sido="가상특별시",
        sigungu="가상구",
        eupmyeondong="가상동",
        ri=None,
        full_name="가상특별시 가상구 가상동",
        abolished=False,
    )
    assert created_on_max == "2024-01-18"


def test_file_without_bom_is_read(tmp_path: Path) -> None:
    dongs, _ = read_file(write(tmp_path / "a.csv", bom=False))
    assert dongs[0].code == "9900000000"


def test_empty_levels_are_none_and_left_out_of_full_name(tmp_path: Path) -> None:
    dongs, _ = read_file(write(tmp_path / "a.csv"))
    assert (dongs[0].sigungu, dongs[0].eupmyeondong, dongs[0].ri) == (None, None, None)
    assert dongs[0].full_name == "가상특별시"
    assert dongs[1].full_name == "가상특별시 가상구"


def test_ri_level_full_name_keeps_all_parts(tmp_path: Path) -> None:
    dongs, _ = read_file(write(tmp_path / "a.csv"))
    assert dongs[3].full_name == "가상도 가상시 가상구 가상면 가상리"


def test_every_row_is_current(tmp_path: Path) -> None:
    dongs, _ = read_file(write(tmp_path / "a.csv"))
    assert not any(dong.abolished for dong in dongs)


def test_missing_column_is_rejected(tmp_path: Path) -> None:
    path = write(tmp_path / "a.csv", header="법정동코드,시도명,시군구명,읍면동명,순번,생성일자")
    with pytest.raises(LegalDongFileError, match="리명"):
        read_file(path)


def test_cp949_file_is_rejected(tmp_path: Path) -> None:
    path = tmp_path / "a.csv"
    path.write_bytes("\r\n".join([HEADER, *LINES]).encode("cp949"))
    with pytest.raises(LegalDongFileError, match="UTF-8"):
        read_file(path)


@pytest.mark.parametrize("code", ["991101010", "99110101000", "99110101AB", ""])
def test_code_must_be_10_digits(tmp_path: Path, code: str) -> None:
    path = write(tmp_path / "a.csv", [f"{code},가상특별시,가상구,가상동,,1,1995-03-01"])
    with pytest.raises(LegalDongFileError, match="10자리"):
        read_file(path)


def test_duplicate_code_is_rejected(tmp_path: Path) -> None:
    path = write(tmp_path / "a.csv", [LINES[2], LINES[2]])
    with pytest.raises(LegalDongFileError, match="중복"):
        read_file(path)


def test_wrong_column_count_is_rejected(tmp_path: Path) -> None:
    path = write(tmp_path / "a.csv", ["9911010100,가상특별시,가상구,가상동"])
    with pytest.raises(LegalDongFileError, match="열 수"):
        read_file(path)


def test_header_only_file_is_rejected(tmp_path: Path) -> None:
    with pytest.raises(LegalDongFileError, match="행이 없습니다"):
        read_file(write(tmp_path / "a.csv", []))


def test_cli_reports_missing_file(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    assert ingest_legal_dong.main(["--file", str(tmp_path / "none.csv")]) == 1
    assert "적재 실패" in capsys.readouterr().err
