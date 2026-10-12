"""인허가 CSV 테스트 픽스처. 업소·주소·관리번호는 모두 가상 예시다."""

import csv
import io
from pathlib import Path

COLUMNS = [
    "개방자치단체코드",
    "관리번호",
    "인허가일자",
    "영업상태명",
    "사업장명",
    "데이터갱신시점",
    "도로명주소",
    "전화번호",
    "지번주소",
]
# 가상 예시 행. 두 번째 행은 지번주소 안에 줄바꿈이, 세 번째 행은 서울 밖 주소가 있다.
ROWS = [
    [
        "3040000",
        "3040000-101-2020-00001",
        "2020-01-02",
        "영업/정상",
        "가상식당",
        "2026-10-01 10:00:00",
        "서울특별시 광진구 가상로 1, 1층",
        "",
        "서울특별시 광진구 화양동 1-1",
    ],
    [
        "3040000",
        "3040000-101-2020-00002",
        "2020-03-04",
        "폐업",
        "가상, 분식",
        "2026-10-07 22:47:53",
        "",
        "",
        "서울특별시 광진구 화양동 2-2\n지하1층",
    ],
    [
        "3040000",
        "3040000-101-2021-00003",
        "2021-05-06",
        "폐업",
        "가상카페",
        "",
        "경기도 수원시 가상로 3",
        "",
        "경기도 수원시 영통구 원천동 3-3",
    ],
]


def write_csv(
    path: Path,
    rows: list[list[str]] | None = None,
    encoding: str = "cp949",
    columns: list[str] | None = None,
) -> Path:
    buffer = io.StringIO(newline="")
    writer = csv.writer(buffer, lineterminator="\r\n")
    writer.writerow(COLUMNS if columns is None else columns)
    writer.writerows(ROWS if rows is None else rows)
    path.write_bytes(buffer.getvalue().encode(encoding))
    return path
