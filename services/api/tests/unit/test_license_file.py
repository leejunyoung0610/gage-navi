"""인허가 파일 읽기 (docs/03 D1). 여기의 업소·주소·관리번호는 모두 가상 예시다."""

from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

from app.location.ingest import license_file
from app.location.ingest.license_file import (
    LicenseFileError,
    has_seoul_address,
    inspect_file,
    iter_rows,
    parse_source_time,
)
from jobs import ingest_licenses
from tests.license_csv import COLUMNS, ROWS, write_csv


def test_cp949_file_is_detected_as_cp949(tmp_path: Path) -> None:
    info = inspect_file(write_csv(tmp_path / "a.csv"))
    assert info.encoding == "cp949"
    assert len(info.sha256) == 64


def test_utf8_file_falls_back_to_utf8(tmp_path: Path) -> None:
    assert inspect_file(write_csv(tmp_path / "a.csv", encoding="utf-8")).encoding == "utf-8-sig"


def test_utf8_bom_is_not_part_of_first_column_name(tmp_path: Path) -> None:
    path = write_csv(tmp_path / "a.csv", encoding="utf-8-sig")
    rows = list(iter_rows(path, inspect_file(path).encoding))
    assert "개방자치단체코드" in rows[0]


def test_undecodable_file_is_rejected(tmp_path: Path) -> None:
    path = tmp_path / "a.csv"
    path.write_bytes(b"\xff\xfe\x00\x01" * 10)
    with pytest.raises(LicenseFileError, match="인코딩"):
        inspect_file(path)


@pytest.mark.parametrize("encoding", ["cp949", "utf-8"])
def test_address_with_newline_stays_in_one_row(tmp_path: Path, encoding: str) -> None:
    path = write_csv(tmp_path / "a.csv", encoding=encoding)
    rows = list(iter_rows(path, inspect_file(path).encoding))
    assert len(rows) == 3
    assert rows[1]["지번주소"] == "서울특별시 광진구 화양동 2-2\n지하1층"
    assert rows[1]["사업장명"] == "가상, 분식"
    assert rows[2]["관리번호"] == "3040000-101-2021-00003"


def test_rows_keep_original_column_names(tmp_path: Path) -> None:
    path = write_csv(tmp_path / "a.csv")
    assert list(next(iter_rows(path, "cp949"))) == COLUMNS


def test_seoul_address_is_judged_from_either_address(tmp_path: Path) -> None:
    path = write_csv(tmp_path / "a.csv")
    assert [has_seoul_address(row) for row in iter_rows(path, "cp949")] == [True, True, False]


def test_missing_required_column_is_rejected(tmp_path: Path) -> None:
    path = write_csv(tmp_path / "a.csv", rows=[], columns=["관리번호", "지번주소"])
    with pytest.raises(LicenseFileError, match="도로명주소"):
        list(iter_rows(path, "cp949"))


def test_row_with_wrong_column_count_is_rejected(tmp_path: Path) -> None:
    path = write_csv(tmp_path / "a.csv", rows=[ROWS[0], ["3040000", "짧은행"]])
    with pytest.raises(LicenseFileError, match="열 수"):
        list(iter_rows(path, "cp949"))


def test_empty_file_is_rejected(tmp_path: Path) -> None:
    path = tmp_path / "a.csv"
    path.write_bytes(b"")
    with pytest.raises(LicenseFileError, match="빈 파일"):
        list(iter_rows(path, "cp949"))


def test_source_time_is_read_as_korea_time() -> None:
    assert parse_source_time("2026-10-07 22:47:53") == datetime(
        2026, 10, 7, 22, 47, 53, tzinfo=ZoneInfo("Asia/Seoul")
    )


@pytest.mark.parametrize("value", ["", "  ", "2026-10-07", "20261007224753", "모름"])
def test_unreadable_source_time_is_none(value: str) -> None:
    assert parse_source_time(value) is None


def test_bad_byte_after_first_chunk_is_rejected(tmp_path: Path) -> None:
    """뒤쪽에 깨진 바이트가 하나만 있어도 대체 문자로 넘기지 않고 실패한다 (errors=strict)."""
    path = write_csv(tmp_path / "a.csv")
    path.write_bytes(path.read_bytes() + b"x" * (license_file._CHUNK + 10) + b"\xff\xff\r\n")
    with pytest.raises(LicenseFileError, match="인코딩"):
        inspect_file(path)


@pytest.mark.parametrize("chunk", [1, 2, 3, 7])
def test_multibyte_char_split_across_chunks_is_not_an_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, chunk: int
) -> None:
    monkeypatch.setattr(license_file, "_CHUNK", chunk)
    assert inspect_file(write_csv(tmp_path / "a.csv")).encoding == "cp949"
    assert inspect_file(write_csv(tmp_path / "b.csv", encoding="utf-8")).encoding == "utf-8-sig"


def test_file_cut_in_the_middle_of_a_char_is_rejected(tmp_path: Path) -> None:
    path = tmp_path / "a.csv"
    path.write_bytes("관리번호".encode("cp949")[:-1])
    with pytest.raises(LicenseFileError, match="인코딩"):
        inspect_file(path)


def test_cli_has_no_incremental_mode(capsys: pytest.CaptureFixture[str]) -> None:
    """갱신은 월 1회 전체 적재 (ADR-025)."""
    with pytest.raises(SystemExit) as exit_info:
        ingest_licenses.main(["--mode", "incremental", "--type", "bakery", "--file", "x.csv"])
    assert exit_info.value.code == 2
    assert "incremental" in capsys.readouterr().err


def test_cli_requires_file(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as exit_info:
        ingest_licenses.main(["--mode", "full", "--type", "bakery"])
    assert exit_info.value.code == 2
    assert "--file" in capsys.readouterr().err
