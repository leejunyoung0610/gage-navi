"""법정동코드 파일(D3) 읽기와 `legal_dong` 적재 (docs/03 D3, docs/04 §2).

제공 파일(공공데이터포털 `국토교통부_전국 법정동`)에는 현행 코드만 있어 모든 행을
`abolished=false`로 넣는다. 폐지 코드 파일을 따로 넣을 수 있게 `abolished` 컬럼과 조회 규칙
(docs/10 §2.1)은 그대로 둔다.
"""

import csv
import hashlib
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

CODE = "법정동코드"
SIDO = "시도명"
SIGUNGU = "시군구명"
EUPMYEONDONG = "읍면동명"
RI = "리명"
CREATED_ON = "생성일자"
REQUIRED_COLUMNS = (CODE, SIDO, SIGUNGU, EUPMYEONDONG, RI)

# 제공 파일은 UTF-8(BOM). BOM이 없어도 읽는다.
ENCODING = "utf-8-sig"
_CODE_LENGTH = 10

_UPSERT = """
INSERT INTO legal_dong (code, sido, sigungu, eupmyeondong, ri, full_name, abolished)
VALUES (:code, :sido, :sigungu, :eupmyeondong, :ri, :full_name, :abolished)
ON CONFLICT (code) DO UPDATE SET
  sido = EXCLUDED.sido, sigungu = EXCLUDED.sigungu, eupmyeondong = EXCLUDED.eupmyeondong,
  ri = EXCLUDED.ri, full_name = EXCLUDED.full_name, abolished = EXCLUDED.abolished
"""


class LegalDongFileError(ValueError):
    """파일을 적재할 수 없는 상태 (인코딩·헤더·열 수·코드 문제)."""


@dataclass(frozen=True)
class LegalDong:
    code: str
    sido: str
    sigungu: str | None
    eupmyeondong: str | None
    ri: str | None
    full_name: str
    abolished: bool = False


@dataclass(frozen=True)
class LegalDongIngestResult:
    file_rows: int
    table_rows: int  # 적재 뒤 `legal_dong` 전체 행 수
    seoul_rows: int
    created_on_max: str | None  # 파일의 `생성일자` 최댓값 (원문 그대로)
    file_sha256: str


def iter_rows(path: Path) -> Iterator[dict[str, str]]:
    with path.open(encoding=ENCODING, newline="") as handle:
        reader = csv.reader(handle)
        try:
            header = next(reader)
        except StopIteration:
            raise LegalDongFileError("빈 파일입니다") from None
        except UnicodeDecodeError as exc:
            raise LegalDongFileError(f"UTF-8로 읽을 수 없습니다: {exc}") from exc
        missing = [column for column in REQUIRED_COLUMNS if column not in header]
        if missing:
            raise LegalDongFileError(f"필수 컬럼이 없습니다: {', '.join(missing)}")
        try:
            for number, row in enumerate(reader, start=1):
                if len(row) != len(header):
                    raise LegalDongFileError(
                        f"{number}번째 행: 열 수가 헤더와 다릅니다 ({len(row)} != {len(header)})"
                    )
                yield dict(zip(header, row, strict=True))
        except UnicodeDecodeError as exc:
            raise LegalDongFileError(f"UTF-8로 읽을 수 없습니다: {exc}") from exc


def to_legal_dong(row: dict[str, str], number: int) -> LegalDong:
    code = row[CODE].strip()
    if len(code) != _CODE_LENGTH or not code.isdigit():
        raise LegalDongFileError(f"{number}번째 행: 법정동코드가 10자리 숫자가 아닙니다: {code!r}")
    sido = row[SIDO].strip()
    if not sido:
        raise LegalDongFileError(f"{number}번째 행: 시도명이 비어 있습니다")
    lower = [row[column].strip() or None for column in (SIGUNGU, EUPMYEONDONG, RI)]
    return LegalDong(
        code=code,
        sido=sido,
        sigungu=lower[0],
        eupmyeondong=lower[1],
        ri=lower[2],
        full_name=" ".join([sido, *(name for name in lower if name is not None)]),
    )


def read_file(path: Path) -> tuple[list[LegalDong], str | None]:
    """파일 전체를 읽어 `(행, 생성일자 최댓값)`을 낸다. 코드가 중복되면 실패."""
    dongs: list[LegalDong] = []
    seen: set[str] = set()
    created_on_max: str | None = None
    for number, row in enumerate(iter_rows(path), start=1):
        dong = to_legal_dong(row, number)
        if dong.code in seen:
            raise LegalDongFileError(f"법정동코드가 중복됩니다: {dong.code}")
        seen.add(dong.code)
        dongs.append(dong)
        created_on = row.get(CREATED_ON, "").strip()
        if created_on and (created_on_max is None or created_on > created_on_max):
            created_on_max = created_on
    if not dongs:
        raise LegalDongFileError("행이 없습니다")
    return dongs, created_on_max


async def ingest_file(engine: AsyncEngine, path: Path) -> LegalDongIngestResult:
    """파일의 모든 행을 `legal_dong`에 upsert한다 (한 트랜잭션, 다시 실행해도 같은 결과).

    파일에 없는 기존 행은 지우지 않는다. `parcel`이 참조할 수 있고, 폐지 코드를 따로 넣었을 수
    있다.
    """
    dongs, created_on_max = read_file(path)
    sha256 = hashlib.sha256(path.read_bytes()).hexdigest()
    async with engine.begin() as conn:
        await conn.execute(
            text(_UPSERT),
            [
                {
                    "code": dong.code,
                    "sido": dong.sido,
                    "sigungu": dong.sigungu,
                    "eupmyeondong": dong.eupmyeondong,
                    "ri": dong.ri,
                    "full_name": dong.full_name,
                    "abolished": dong.abolished,
                }
                for dong in dongs
            ],
        )
        table_rows: int = (await conn.execute(text("SELECT count(*) FROM legal_dong"))).scalar_one()
    return LegalDongIngestResult(
        file_rows=len(dongs),
        table_rows=table_rows,
        seoul_rows=sum(1 for dong in dongs if dong.sido == "서울특별시"),
        created_on_max=created_on_max,
        file_sha256=sha256,
    )
