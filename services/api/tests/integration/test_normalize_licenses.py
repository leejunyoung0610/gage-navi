"""정규화 파이프라인과 데이터 검증 (T-016). 픽스처의 업소·주소·관리번호·코드는 모두 가상 예시다."""

import asyncio
import os
import time
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine
from sqlalchemy.pool import NullPool

from app.address import legal_dong_file
from app.core import db
from app.location.ingest.license_file import ingest_file
from app.location.normalize.job import NormalizeError, NormalizeResult, run_normalize
from app.location.normalize.records import PARSE_VERSION, SOURCE_COLUMNS
from tests.license_csv import write_csv

REPO_ROOT = Path(__file__).resolve().parents[4]
RAW = REPO_ROOT / "data" / "raw"
# 실제 원천 파일 (gitignore). 없으면 해당 테스트는 건너뛴다.
REAL_FILES = {
    "general_restaurant": Path(
        os.environ.get("LICENSE_GENERAL_CSV")
        or RAW / "2026-10-08" / "식품_일반음식점_서울특별시.csv"
    ),
    "rest_restaurant": Path(
        os.environ.get("LICENSE_REST_CSV") or RAW / "2026-10-12" / "식품_휴게음식점_서울특별시.csv"
    ),
    "bakery": Path(
        os.environ.get("LICENSE_BAKERY_CSV")
        or RAW / "2026-10-12" / "식품_제과점영업_서울특별시.csv"
    ),
}
REAL_LEGAL_DONG = Path(
    os.environ.get("LEGAL_DONG_CSV") or RAW / "2026-10-12" / "국토교통부_전국 법정동_20260630.csv"
)

COLUMNS = [*SOURCE_COLUMNS, "전화번호"]
LEGAL_DONGS = [("1121510700", "광진구", "화양동"), ("1144012000", "마포구", "서교동")]


def with_engine(url: str, work: Callable[[AsyncEngine], Awaitable[Any]]) -> Any:
    async def run() -> Any:
        engine = create_async_engine(url, poolclass=NullPool)
        try:
            return await work(engine)
        finally:
            await engine.dispose()

    return asyncio.run(run())


def execute(url: str, *statements: str) -> None:
    async def work(engine: AsyncEngine) -> None:
        async with engine.begin() as conn:
            for statement in statements:
                await conn.execute(text(statement))

    with_engine(url, work)


def fetch_all(url: str, sql: str) -> list[Any]:
    async def work(engine: AsyncEngine) -> list[Any]:
        async with engine.connect() as conn:
            return list((await conn.execute(text(sql))).all())

    result: list[Any] = with_engine(url, work)
    return result


def ingest(url: str, license_type: str, path: Path) -> int:
    snapshot_id: int = with_engine(
        url, lambda engine: ingest_file(engine, license_type, path)
    ).snapshot_id
    return snapshot_id


def normalize(url: str) -> NormalizeResult:
    result: NormalizeResult = with_engine(url, run_normalize)
    return result


@pytest.fixture
def clean_db(migrated_db_url: str) -> str:
    """테이블을 비우고 가상 법정동 두 개를 넣은 DB."""
    execute(
        migrated_db_url,
        "TRUNCATE license_record, closure_surge_day, data_snapshot, legal_dong CASCADE",
        *(
            "INSERT INTO legal_dong (code, sido, sigungu, eupmyeondong, full_name) "
            f"VALUES ('{code}', '서울특별시', '{sigungu}', '{dong}', '서울특별시 {sigungu} {dong}')"
            for code, sigungu, dong in LEGAL_DONGS
        ),
    )
    return migrated_db_url


def row(number: int, **values: str) -> list[str]:
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
        "좌표정보(X)": "205000.0",
        "좌표정보(Y)": "450000.0",
        "데이터갱신시점": "2026-10-07 22:47:53",
        "전화번호": "",
    }
    assert set(values) <= set(base)
    return [(base | values)[column] for column in COLUMNS]


def closure(number: int, closed_on: str) -> list[str]:
    return row(
        number,
        영업상태명="폐업",
        폐업일자=closed_on,
        개방자치단체코드="3130000",
        지번주소="서울특별시 마포구 서교동 2-2 가상빌딩 지하1층",
        도로명주소="",
    )


def general_rows() -> list[list[str]]:
    rows = [
        row(1),
        row(2, 지번주소="경기도 수원시 영통구 원천동 3-3", 도로명주소="경기도 수원시 가상로 3"),
        row(3, 업태구분명="푸드트럭"),
        row(4, 영업상태명="폐업", 폐업일자="2009-01-01"),  # 날짜 역전 → 격리
        row(5, 지번주소="서울특별시 광진구 화양동 1-1 지하1층 102호"),  # 층·호 충돌
    ]
    for day in range(1, 5):
        rows += [
            closure(len(rows) + 1, f"2020-03-0{day}"),
            closure(len(rows) + 2, f"2020-03-0{day}"),
        ]
    rows += [closure(len(rows) + 1 + n, "2020-03-09") for n in range(1, 21)]
    return rows  # 5 + 8 + 20 = 33행


def rest_rows() -> list[list[str]]:
    rows = [row(101, 업태구분명="편의점", 데이터갱신시점="2026-11-03 09:00:00")]
    rows += [closure(200 + n, "2020-03-09") for n in range(10)]
    return rows  # 11행. 급증일은 일반 20건 + 휴게 10건 = 30건


def load_both(url: str, tmp_path: Path) -> tuple[int, int]:
    general = ingest(
        url, "general_restaurant", write_csv(tmp_path / "g.csv", general_rows(), columns=COLUMNS)
    )
    rest = ingest(
        url, "rest_restaurant", write_csv(tmp_path / "r.csv", rest_rows(), columns=COLUMNS)
    )
    return general, rest


def test_normalize_writes_records_surge_days_and_validation(clean_db: str, tmp_path: Path) -> None:
    general, rest = load_both(clean_db, tmp_path)
    result = normalize(clean_db)

    assert result.applied and (result.records, result.surge_days) == (42, 1)
    assert {s.license_type: s.status for s in result.snapshots} == {
        "general_restaurant": "validated",
        "rest_restaurant": "validated",
    }
    counts = fetch_all(
        clean_db,
        "SELECT count(*) AS n, sum(bulk_closure::int) AS surge, "
        "sum(no_fixed_place::int) AS mobile, count(DISTINCT parse_version) AS versions, "
        "min(parse_version) AS version FROM license_record",
    )[0]
    assert tuple(counts) == (42, 30, 1, 1, PARSE_VERSION)

    first = fetch_all(
        clean_db,
        "SELECT status, opened_on::text, area_m2::text, pnu, sigungu_code, floor, floor_source, "
        "ho_list, round(ST_Y(geom)::numeric, 2)::text AS lat, last_snapshot_id, "
        "source_updated_at AT TIME ZONE 'Asia/Seoul' AS updated, stale_suspect "
        "FROM license_record WHERE mgmt_no = '3040000-101-2020-00001'",
    )[0]
    assert tuple(first)[:9] == (
        "open",
        "2010-01-02",
        "33.50",
        "1121510700100010001",
        "11215",
        "1",
        "jibun_tail",
        ["101"],
        "37.55",
    )
    assert first.last_snapshot_id == general and not first.stale_suspect
    assert str(first.updated) == "2026-10-07 22:47:53"
    store = fetch_all(
        clean_db,
        "SELECT biz_category, no_fixed_place FROM license_record WHERE biz_category = '편의점'",
    )
    assert [tuple(r) for r in store] == [("편의점", False)]
    gone = fetch_all(
        clean_db, "SELECT count(*) AS n FROM license_record WHERE mgmt_no ~ '-0000[24]$'"
    )[0]
    assert gone.n == 0  # 서울 밖 주소 행과 날짜 역전 행

    surge = fetch_all(clean_db, "SELECT * FROM closure_surge_day")
    assert [tuple(r) for r in surge] == [
        ("3130000", surge[0].closed_on, "마포구", 30, surge[0].median_daily, PARSE_VERSION)
    ]
    assert (str(surge[0].closed_on), str(surge[0].median_daily)) == ("2020-03-09", "2.0")

    snapshot = fetch_all(
        clean_db, f"SELECT status, validation FROM data_snapshot WHERE id = {general}"
    )[0]
    assert snapshot.status == "validated"
    assert snapshot.validation["ingest"]["file_rows"] == 33  # 적재 기록은 그대로
    recorded = snapshot.validation["normalize"]
    assert recorded["passed"] and recorded["applied"] and recorded["warnings"] == ["DV4"]
    assert (
        recorded["input_rows"],
        recorded["non_seoul_excluded"],
        recorded["records"],
        recorded["no_fixed_place"],
        recorded["floor_conflict"],
        recorded["ho_conflict"],
    ) == (33, 1, 31, 1, 1, 1)
    assert recorded["checks"]["DV9"] == {
        "result": "recorded",
        "surge_cells": 1,
        "surge_dates": 1,
        "records": 20,
    }
    assert recorded["status_counts"] == {"폐업": 29, "영업/정상": 4}
    assert recorded["category_counts"] == {"한식": 32, "푸드트럭": 1}
    assert rest != general


def test_health_snapshot_label_is_earliest_validated_month(
    clean_db: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def label(engine: AsyncEngine) -> str | None:
        monkeypatch.setattr(db, "get_engine", lambda: engine)
        return await db.location_snapshot_label()

    assert with_engine(clean_db, label) is None  # 스냅샷 없음
    load_both(clean_db, tmp_path)
    assert with_engine(clean_db, label) is None  # 적재만 하고 정규화 전
    normalize(clean_db)
    # 일반음식점 기준 시각 2026-10-07, 휴게음식점 2026-11-03 → 더 이른 쪽의 연-월
    assert with_engine(clean_db, label) == "2026-10"


def test_rerun_gives_the_same_result(clean_db: str, tmp_path: Path) -> None:
    load_both(clean_db, tmp_path)
    query = (
        "SELECT license_type, mgmt_no, status, pnu, floor, ho_list, bulk_closure, no_fixed_place "
        "FROM license_record ORDER BY 1, 2"
    )
    first = normalize(clean_db)
    records = [tuple(r) for r in fetch_all(clean_db, query)]
    second = normalize(clean_db)
    assert second.applied and [s.status for s in second.snapshots] == ["validated", "validated"]
    assert [tuple(r) for r in fetch_all(clean_db, query)] == records
    assert [s.validation for s in second.snapshots] == [s.validation for s in first.snapshots]
    assert fetch_all(clean_db, "SELECT count(*) AS n FROM closure_surge_day")[0].n == 1


def test_failed_check_keeps_existing_data(clean_db: str, tmp_path: Path) -> None:
    general, rest = load_both(clean_db, tmp_path)
    normalize(clean_db)
    before = [tuple(r) for r in fetch_all(clean_db, "SELECT * FROM license_record ORDER BY id")]

    # 다음 달 파일: 표에 없는 영업상태 값(DV5)과 이름이 바뀐 업소
    changed = general_rows()
    changed[0] = row(1, 사업장명="바뀐가상식당", 영업상태명="직권말소")
    bad = ingest(
        clean_db, "general_restaurant", write_csv(tmp_path / "g2.csv", changed, columns=COLUMNS)
    )
    result = normalize(clean_db)

    assert not result.applied and (result.records, result.surge_days) == (0, 0)
    assert {s.snapshot_id: s.status for s in result.snapshots} == {bad: "failed", rest: "unchanged"}
    assert [
        tuple(r) for r in fetch_all(clean_db, "SELECT * FROM license_record ORDER BY id")
    ] == before
    statuses = {
        r.id: r for r in fetch_all(clean_db, "SELECT id, status, validation FROM data_snapshot")
    }
    assert (statuses[general].status, statuses[rest].status, statuses[bad].status) == (
        "validated",
        "validated",
        "failed",
    )
    failed = statuses[bad].validation["normalize"]
    assert failed["failed"] == ["DV5"] and not failed["applied"]
    assert failed["checks"]["DV5"]["unknown"] == {"직권말소": 1}
    assert failed["checks"]["DV1"] == {
        "result": "pass",
        "rows": 33,
        "previous_rows": 33,
        "change": "0.000000",
    }

    # 실패한 스냅샷은 건너뛰고 직전 성공 스냅샷으로 다시 정규화할 수 있다
    again = normalize(clean_db)
    assert again.applied and {s.snapshot_id for s in again.snapshots} == {general, rest}


def test_row_count_change_over_five_percent_fails(clean_db: str, tmp_path: Path) -> None:
    load_both(clean_db, tmp_path)
    normalize(clean_db)
    grown = general_rows() + [row(900 + n) for n in range(2)]  # 33 → 35행 (+6.1%)
    bigger = ingest(
        clean_db, "general_restaurant", write_csv(tmp_path / "g3.csv", grown, columns=COLUMNS)
    )
    result = normalize(clean_db)
    assert not result.applied
    failed = next(s for s in result.snapshots if s.snapshot_id == bigger)
    assert failed.status == "failed" and failed.validation["failed"] == ["DV1"]
    assert failed.validation["checks"]["DV7"]["previous_ratio"] is not None


def test_updated_file_within_limits_replaces_records(clean_db: str, tmp_path: Path) -> None:
    load_both(clean_db, tmp_path)
    normalize(clean_db)
    changed = general_rows()
    changed[0] = row(1, 영업상태명="폐업", 폐업일자="2026-09-30", 사업장명="가상식당1")
    newer = ingest(
        clean_db, "general_restaurant", write_csv(tmp_path / "g4.csv", changed, columns=COLUMNS)
    )
    result = normalize(clean_db)
    assert result.applied
    record = fetch_all(
        clean_db,
        "SELECT status, closed_on::text, last_snapshot_id FROM license_record "
        "WHERE mgmt_no = '3040000-101-2020-00001'",
    )[0]
    assert tuple(record) == ("closed", "2026-09-30", newer)
    assert fetch_all(clean_db, "SELECT count(*) AS n FROM license_record")[0].n == 42


def test_needs_snapshots_and_legal_dong(clean_db: str, tmp_path: Path) -> None:
    with pytest.raises(NormalizeError, match="스냅샷"):
        normalize(clean_db)
    load_both(clean_db, tmp_path)
    execute(clean_db, "TRUNCATE legal_dong CASCADE")
    with pytest.raises(NormalizeError, match="legal_dong"):
        normalize(clean_db)
    assert fetch_all(clean_db, "SELECT count(*) AS n FROM license_record")[0].n == 0


def test_seoul_food3_normalizes_within_ten_minutes(clean_db: str) -> None:
    """T-016 수용 기준: 서울 식품 3종 전체 정규화 10분 이내."""
    missing = [path for path in [*REAL_FILES.values(), REAL_LEGAL_DONG] if not path.exists()]
    if missing:
        pytest.skip(f"원천 파일이 없어 건너뜀: {missing[0]} (data/README.md 참고)")
    with_engine(clean_db, lambda engine: legal_dong_file.ingest_file(engine, REAL_LEGAL_DONG))
    for license_type, path in REAL_FILES.items():
        ingest(clean_db, license_type, path)

    started = time.perf_counter()
    result = normalize(clean_db)
    seconds = time.perf_counter() - started

    assert seconds < 600
    assert result.applied and all(not s.validation["failed"] for s in result.snapshots)
    assert result.records == fetch_all(clean_db, "SELECT count(*) AS n FROM license_record")[0].n
    excluded = sum(s.validation["non_seoul_excluded"] for s in result.snapshots)
    isolated = sum(s.validation["checks"]["DV4"]["isolated"] for s in result.snapshots)
    assert (
        result.records
        == sum(s.validation["input_rows"] for s in result.snapshots) - excluded - isolated
    )
    print(f"\n서울 식품 3종 정규화: {result.records:,}건, {seconds:.1f}초")
