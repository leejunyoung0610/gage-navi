"""사이트맵 API 통합 테스트 (T-035, docs/30 §2, docs/40 §9). 필지·업소·날짜는 모두 가상 예시다.

요약 테이블은 `jobs.build_history`로 만든다. 숨김 기록은 빌드 전에 넣어 두고, 숨김 때문에
2건이 되는 층이 사이트맵에 들어가지 않는지 본다. 관리자 숨김 처리 뒤의 재계산은
test_admin_corrections.py가 본다.
"""

import asyncio
from collections.abc import Iterator
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine
from sqlalchemy.pool import NullPool

from app.core.ratelimit import lookup_limiter
from app.location.history.job import build_history
from app.location.sitemap import router as sitemap_router
from app.main import app

GU, OTHER_GU = "11215", "11110"
P1 = "1121510700100470001"
P2 = "1121510700100480000"
P3 = "1111010100100010000"
INSERT = """
INSERT INTO license_record
  (id, license_type, mgmt_no, jurisdiction_code, name, biz_category, status, status_raw,
   opened_on, closed_on, road_addr, pnu, floor, geom, bulk_closure, no_fixed_place, parse_version)
VALUES ({id}, 'general_restaurant', 'M{id}', '3040000', '가상업소 {id}', '한식', '{status}',
        '{status}', '{opened}', {closed}, '서울특별시 가상구 가상로 {id}', '{pnu}', '{floor}',
        ST_GeomFromEWKT('SRID=4326;POINT(127.07 37.54)'), false, false, '2026.10.1')
"""
# (id, 상태, 개업일, 폐업일, 층, 필지)
RECORDS = [
    (1, "closed", "2010-01-01", "2014-06-30", "1", P1),  # P1 1층: 2건 → 들어간다
    (2, "open", "2015-01-01", None, "1", P1),
    (3, "closed", "2011-01-01", "2013-01-01", "2", P1),  # P1 2층: 숨김 4를 빼면 1건 → 빠진다
    (4, "open", "2014-01-01", None, "2", P1),
    (5, "open", "2016-01-01", None, "B1", P1),  # P1 지하 1층: 1건 → 빠진다
    (6, "closed", "2008-01-01", "2009-01-01", "1", P2),  # P2 1층: 3건
    (7, "closed", "2009-02-01", "2012-01-01", "1", P2),
    (8, "open", "2012-02-01", None, "1", P2),
    (9, "closed", "2012-01-01", "2013-01-01", "RF", P2),  # P2 옥탑: 2건
    (10, "open", "2013-02-01", None, "RF", P2),
    (11, "closed", "2015-01-01", "2016-01-01", "1", P3),  # 다른 구 P3 1층: 2건
    (12, "open", "2016-02-01", None, "1", P3),
]
SUPPRESSED = (4,)


def _run(url: str, *statements: str) -> None:
    async def go() -> None:
        engine = create_async_engine(url, poolclass=NullPool)
        try:
            async with engine.begin() as conn:
                for statement in statements:
                    await conn.execute(text(statement))
            await build_history(engine)
        finally:
            await engine.dispose()

    asyncio.run(go())


@pytest.fixture
def api(migrated_db_url: str, monkeypatch: pytest.MonkeyPatch) -> Iterator[TestClient]:
    statements = [
        "TRUNCATE license_record, floor_summary, parcel, record_prior, data_snapshot, "
        "legal_dong, record_suppression CASCADE",
        "INSERT INTO legal_dong (code, sido, sigungu, eupmyeondong, full_name) VALUES "
        "('1121510700', '서울특별시', '가상구', '가상동', '서울특별시 가상구 가상동'), "
        "('1111010100', '서울특별시', '가상이구', '가상이동', '서울특별시 가상이구 가상이동')",
        "INSERT INTO data_snapshot (source, license_type, row_count, status, source_updated_max) "
        "VALUES ('license_file', 'general_restaurant', 12, 'validated', '2026-10-07 22:47:53+09')",
    ]
    for rid, status, opened, closed, floor, pnu in RECORDS:
        statements.append(
            INSERT.format(
                id=rid,
                status=status,
                opened=opened,
                closed="NULL" if closed is None else f"'{closed}'",
                pnu=pnu,
                floor=floor,
            )
        )
    for rid in SUPPRESSED:
        statements.append(
            f"INSERT INTO record_suppression (record_id, reason) VALUES ({rid}, 'wrong_info')"
        )
    _run(migrated_db_url, *statements)
    engine: AsyncEngine = create_async_engine(migrated_db_url, poolclass=NullPool)
    monkeypatch.setattr(sitemap_router, "get_engine", lambda: engine)
    lookup_limiter.reset()
    with TestClient(app) as client:
        yield client
    lookup_limiter.reset()


def get(client: TestClient, path: str) -> Any:
    response = client.get(f"/api/v1{path}")
    assert response.status_code == 200, response.text
    assert response.headers["cache-control"] == "public, max-age=300"
    return response.json()


def test_sigungu_lists_codes_with_floor_counts(api: TestClient) -> None:
    body = get(api, "/sitemap/sigungu")
    assert body["data"] == {
        "sigungu": [
            {"code": OTHER_GU, "floor_count": 1},
            {"code": GU, "floor_count": 3},  # P1 1층, P2 1층·옥탑
        ]
    }
    assert set(body["meta"]) == {"request_id"}


def test_floors_have_two_or_more_records_and_hidden_records_do_not_count(api: TestClient) -> None:
    data = get(api, f"/sitemap/sigungu/{GU}")["data"]
    assert data == {
        "code": GU,
        "floors": [
            {"pnu": P1, "floor": "1"},
            {"pnu": P2, "floor": "1"},
            {"pnu": P2, "floor": "RF"},
        ],
    }
    # 숨김을 세면 2건인 P1 2층, 1건인 지하 1층은 없다
    assert {"pnu": P1, "floor": "2"} not in data["floors"]
    assert get(api, f"/sitemap/sigungu/{OTHER_GU}")["data"]["floors"] == [{"pnu": P3, "floor": "1"}]


def test_unknown_sigungu_is_empty(api: TestClient) -> None:
    assert get(api, "/sitemap/sigungu/11680")["data"] == {"code": "11680", "floors": []}


@pytest.mark.parametrize("code", ["1121", "112150", "abcde"])
def test_invalid_code_is_422(api: TestClient, code: str) -> None:
    response = api.get(f"/api/v1/sitemap/sigungu/{code}")
    assert response.status_code == 422
    error = response.json()["error"]
    assert error["code"] == "VALIDATION_ERROR"
    assert error["details"] == {"fields": {"code": "invalid_format"}}


def test_db_failure_is_503(api: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    def broken() -> AsyncEngine:
        raise ConnectionRefusedError("refused")

    monkeypatch.setattr(sitemap_router, "get_engine", broken)
    for path in ("/api/v1/sitemap/sigungu", f"/api/v1/sitemap/sigungu/{GU}"):
        response = api.get(path)
        assert response.status_code == 503
        assert response.json()["error"]["code"] == "SERVICE_UNAVAILABLE"
        assert "refused" not in response.text
