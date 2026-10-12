"""인허가 원천 파일(D1) 읽기와 `license_raw` 적재 (docs/03 D1, docs/04 §2).

파일의 모든 행을 원문 컬럼명 그대로 `license_raw.payload`에 넣는다. 서울 밖 주소 행도 빼지 않고
수만 센다 — 걸러내는 일은 정규화(T-016)가 한다. 전화번호는 payload에만 남는다 (AGENTS.md §2.7).
"""

import codecs
import csv
import hashlib
import json
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

LICENSE_TYPES = ("general_restaurant", "rest_restaurant", "bakery")
SOURCE_FILE = "license_file"

MGMT_NO = "관리번호"
JIBUN_ADDR = "지번주소"
ROAD_ADDR = "도로명주소"
SOURCE_UPDATED_AT = "데이터갱신시점"
REQUIRED_COLUMNS = (MGMT_NO, JIBUN_ADDR, ROAD_ADDR, SOURCE_UPDATED_AT)
SEOUL_PREFIX = "서울특별시"

# CP949를 먼저 시도한다 (docs/03 D1). UTF-8 파일은 CP949로 읽히지 않는 바이트가 나와 넘어간다.
ENCODINGS = ("cp949", "utf-8-sig")
# 원천 시각 문자열에는 시간대가 없다. 국내 행정 시스템 값이므로 한국 시간으로 읽는다.
SOURCE_TZ = ZoneInfo("Asia/Seoul")
SOURCE_TIME_FORMAT = "%Y-%m-%d %H:%M:%S"
_CHUNK = 1 << 20


class LicenseFileError(ValueError):
    """파일을 적재할 수 없는 상태 (인코딩·헤더·열 수·관리번호 문제)."""


@dataclass(frozen=True)
class FileInfo:
    encoding: str
    sha256: str


@dataclass(frozen=True)
class IngestResult:
    snapshot_id: int
    row_count: int
    non_seoul_address_rows: int
    source_updated_max: datetime | None
    encoding: str
    file_sha256: str
    skipped: bool  # 같은 파일이 이미 적재돼 있어 아무것도 하지 않았다


def inspect_file(path: Path) -> FileInfo:
    """파일 전체를 한 번 읽어 인코딩과 SHA-256을 정한다."""
    for encoding in ENCODINGS:
        digest = hashlib.sha256()
        try:
            with path.open("rb") as raw:
                decoder = codecs.getincrementaldecoder(encoding)(errors="strict")
                while chunk := raw.read(_CHUNK):
                    digest.update(chunk)
                    decoder.decode(chunk)
                decoder.decode(b"", final=True)
        except UnicodeDecodeError:
            continue
        return FileInfo(encoding=encoding, sha256=digest.hexdigest())
    raise LicenseFileError(f"인코딩을 판별하지 못했습니다 (시도: {', '.join(ENCODINGS)})")


def iter_rows(path: Path, encoding: str) -> Iterator[dict[str, str]]:
    """행을 `{원문 컬럼명: 값}`으로 낸다. 주소에 줄바꿈이 있을 수 있어 `csv` 모듈로 읽는다."""
    with path.open(encoding=encoding, newline="") as handle:
        reader = csv.reader(handle)
        try:
            header = next(reader)
        except StopIteration:
            raise LicenseFileError("빈 파일입니다") from None
        missing = [column for column in REQUIRED_COLUMNS if column not in header]
        if missing:
            raise LicenseFileError(f"필수 컬럼이 없습니다: {', '.join(missing)}")
        if len(set(header)) != len(header):
            raise LicenseFileError("헤더에 같은 컬럼명이 두 번 나옵니다")
        for row in reader:
            if len(row) != len(header):
                raise LicenseFileError(
                    f"{reader.line_num}번째 줄: 열 수가 {len(row)}개입니다 (헤더 {len(header)}개)"
                )
            yield dict(zip(header, row, strict=True))


def has_seoul_address(row: dict[str, str]) -> bool:
    return row[JIBUN_ADDR].startswith(SEOUL_PREFIX) or row[ROAD_ADDR].startswith(SEOUL_PREFIX)


def parse_source_time(value: str) -> datetime | None:
    """`데이터갱신시점` → 시각. 비었거나 형식이 다르면 `None` (추측하지 않는다)."""
    try:
        return datetime.strptime(value.strip(), SOURCE_TIME_FORMAT).replace(tzinfo=SOURCE_TZ)
    except ValueError:
        return None


async def ingest_file(engine: AsyncEngine, license_type: str, path: Path) -> IngestResult:
    """파일 하나를 `data_snapshot` 1행 + `license_raw` N행으로 적재한다 (한 트랜잭션).

    같은 내용의 파일(`file_sha256`)이 이미 적재돼 있으면 그 스냅샷을 돌려주고 끝낸다.
    """
    if license_type not in LICENSE_TYPES:
        raise LicenseFileError(f"알 수 없는 인허가 종류: {license_type}")
    info = inspect_file(path)

    async with engine.begin() as conn:
        existing = (
            await conn.execute(
                text(
                    "SELECT id, row_count, source_updated_max, validation FROM data_snapshot "
                    "WHERE source = :source AND license_type = :license_type "
                    "AND file_sha256 = :sha AND status <> 'failed' ORDER BY id DESC LIMIT 1"
                ),
                {"source": SOURCE_FILE, "license_type": license_type, "sha": info.sha256},
            )
        ).first()
        if existing is not None:
            return IngestResult(
                snapshot_id=existing.id,
                row_count=existing.row_count,
                non_seoul_address_rows=existing.validation["ingest"]["non_seoul_address_rows"],
                source_updated_max=existing.source_updated_max,
                encoding=info.encoding,
                file_sha256=info.sha256,
                skipped=True,
            )

        snapshot_id: int = (
            await conn.execute(
                text(
                    "INSERT INTO data_snapshot "
                    "(source, license_type, row_count, file_sha256, status) "
                    "VALUES (:source, :license_type, 0, :sha, 'loaded') RETURNING id"
                ),
                {"source": SOURCE_FILE, "license_type": license_type, "sha": info.sha256},
            )
        ).scalar_one()

        counters = _Counters()
        raw_conn = await conn.get_raw_connection()
        await raw_conn.driver_connection.copy_records_to_table(  # type: ignore[union-attr]
            "license_raw",
            records=_records(path, info.encoding, snapshot_id, license_type, counters),
            columns=("snapshot_id", "license_type", "mgmt_no", "payload"),
        )

        validation = {
            "ingest": {
                "file_rows": counters.rows,
                "non_seoul_address_rows": counters.non_seoul,
                "source_time_unparsed_rows": counters.time_unparsed,
                "encoding": info.encoding,
            }
        }
        await conn.execute(
            text(
                "UPDATE data_snapshot SET row_count = :rows, source_updated_max = :updated, "
                "validation = CAST(:validation AS jsonb) WHERE id = :id"
            ),
            {
                "rows": counters.rows,
                "updated": counters.updated_max,
                "validation": json.dumps(validation, ensure_ascii=False),
                "id": snapshot_id,
            },
        )
    return IngestResult(
        snapshot_id=snapshot_id,
        row_count=counters.rows,
        non_seoul_address_rows=counters.non_seoul,
        source_updated_max=counters.updated_max,
        encoding=info.encoding,
        file_sha256=info.sha256,
        skipped=False,
    )


class _Counters:
    def __init__(self) -> None:
        self.rows = 0
        self.non_seoul = 0
        self.time_unparsed = 0
        self.updated_max: datetime | None = None


def _records(
    path: Path, encoding: str, snapshot_id: int, license_type: str, counters: _Counters
) -> Iterator[tuple[int, str, str, str]]:
    seen: set[str] = set()
    for row in iter_rows(path, encoding):
        mgmt_no = row[MGMT_NO]
        if not mgmt_no:
            raise LicenseFileError(f"{counters.rows + 1}번째 행: 관리번호가 비어 있습니다")
        if mgmt_no in seen:
            raise LicenseFileError(f"관리번호가 중복됩니다: {mgmt_no}")
        seen.add(mgmt_no)
        counters.rows += 1
        if not has_seoul_address(row):
            counters.non_seoul += 1
        updated = parse_source_time(row[SOURCE_UPDATED_AT])
        if updated is None:
            counters.time_unparsed += 1
        elif counters.updated_max is None or updated > counters.updated_max:
            counters.updated_max = updated
        yield snapshot_id, license_type, mgmt_no, json.dumps(row, ensure_ascii=False)
