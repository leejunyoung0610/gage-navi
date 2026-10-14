"""장소 API 시드 DB 통합 테스트 (T-022, docs/30 §2). 필지·업소·날짜·기준율은 모두 가상 예시다.

`jobs.build_history`를 거치지 않고 요약 테이블(`parcel`·`floor_summary`)과 기준율을 직접 넣어
API가 테이블을 어떻게 읽고 고르는지만 본다. 빌드 자체는 test_build_history.py가 본다.
"""

import asyncio
import json
import re
from collections.abc import Iterator
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine
from sqlalchemy.pool import NullPool

from app.core.ratelimit import lookup_limiter
from app.location.places import queries
from app.main import app

P_MAIN = "1121510700100470001"
P_NO_FLOOR = "1121510700100480000"
P_MISSING = "1121510700100490000"
SNAPSHOT, METHOD = "2026-10", "2026.10.1"
AS_OF = "2026-10-07"
SEOUL, GU = "11", "11215"
PHONE_MARKER = "가상전화 000-0000-0000"  # 가상 예시: 원본 행(`license_raw`)에만 넣는다

# (id, 관리번호, 상태, 개업일, 폐업일, 층, 호, 급증일, 미갱신 의심, 고정된 자리 없음, 필지)
Row = tuple[int, str, str, str | None, str | None, str | None, str, bool, bool, bool, str]
RECORDS: list[Row] = [
    # 1층 (단독): 폐업 A1·A2·A4 중 급증일 A2와 숨김 A4는 세지 않는다 → 현재 과거 폐업 = A1 = 1
    (11, "A1", "closed", "2006-01-01", "2010-06-30", "1", "{101}", False, False, False, P_MAIN),
    (12, "A2", "closed", "2010-08-01", "2012-03-31", "1", "{101}", True, False, False, P_MAIN),
    (13, "A3", "open", "2012-04-01", None, "1", "{101,102}", False, True, False, P_MAIN),
    (14, "A4", "closed", "2004-01-01", "2005-06-30", "1", "{}", False, False, False, P_MAIN),
    (15, "A5", "open", "2013-01-01", None, "1", "{102}", False, False, True, P_MAIN),
    # 2층 (소형 복수): 폐업 없음 → 버킷 0
    (21, "B1", "open", "2015-01-01", None, "2", "{}", False, False, False, P_MAIN),
    (22, "B2", "open", "2015-02-01", None, "2", "{}", False, False, False, P_MAIN),
    # 3층 (대형)
    (31, "C1", "closed", "2016-01-01", "2017-01-01", "3", "{}", False, False, False, P_MAIN),
    # 지하 1층 (단독): 폐업 4건 → 버킷 4+, 서울 n < 200
    (41, "D1", "closed", "2005-01-01", "2006-01-01", "B1", "{}", False, False, False, P_MAIN),
    (42, "D2", "closed", "2006-02-01", "2007-01-01", "B1", "{}", False, False, False, P_MAIN),
    (43, "D3", "closed", "2007-02-01", "2008-01-01", "B1", "{}", False, False, False, P_MAIN),
    (44, "D4", "closed", "2008-02-01", "2009-01-01", "B1", "{}", False, False, False, P_MAIN),
    # 층 미상
    (51, "E1", "closed", "1998-05-11", "2003-02-28", None, "{}", True, False, False, P_MAIN),
    (52, "E2", "open", "2016-01-01", None, None, "{}", False, False, False, P_MAIN),
    (53, "E3", "closed", "1999-01-01", "2000-01-01", None, "{}", False, False, False, P_MAIN),
    (54, "E4", "open", "2001-01-01", None, None, "{}", False, False, True, P_MAIN),
    (61, "F1", "open", "2020-01-01", None, None, "{}", False, False, False, P_NO_FLOOR),
]  # fmt: skip
SUPPRESSED = (14, 53)
# (층, 기록 수, 2005년 이후, 영업 중, 중앙값, 동시 영업, 동시 최대)
SUMMARIES = [
    ("B1", 4, 4, 0, 334, False, 1),
    ("1", 4, 3, 1, 1611, False, 1),
    ("2", 2, 2, 2, None, True, 3),
    ("3", 1, 1, 0, 366, False, 12),
]
# (스냅샷, 규모, 범위, 버킷, n) — 비율은 n과 상관없는 가상 값
RATES = [
    (SNAPSHOT, "single", GU, "1", 250),
    (SNAPSHOT, "single", GU, "2", 9000),  # 숨김 A4를 세면 고르게 되는 행: 쓰이면 안 된다
    (SNAPSHOT, "single", GU, "0", 900),
    (SNAPSHOT, "single", SEOUL, "1", 21000),
    (SNAPSHOT, "single", SEOUL, "3", 500),
    (SNAPSHOT, "single", SEOUL, "0", 130000),
    (SNAPSHOT, "single", SEOUL, "4+", 150),
    (SNAPSHOT, "small", GU, "0", 150),
    (SNAPSHOT, "small", SEOUL, "0", 5000),
    (SNAPSHOT, "all", GU, "4+", 5000),
    (SNAPSHOT, "all", SEOUL, "4+", 30000),
    (SNAPSHOT, "all", SEOUL, "0", 130000),
    # 예전 카드의 대형 행: 최신 카드가 아니므로 쓰이면 안 된다
    ("2026-09", "large", SEOUL, "0", 9000),
]
HOLDS = {"single": True, "small": True, "large": False}


def _card(holds: dict[str, bool]) -> str:
    return json.dumps({"by_floor_scale": {k: {"holds": v} for k, v in holds.items()}})


def _seed_statements(with_card: bool) -> list[str]:
    statements = [
        "TRUNCATE license_record, floor_summary, parcel, data_snapshot, legal_dong, "
        "closure_surge_day, record_suppression, base_rate, model_card CASCADE",
        "INSERT INTO legal_dong (code, sido, sigungu, eupmyeondong, full_name) VALUES "
        "('1121510700', '서울특별시', '가상구', '가상동', '서울특별시 가상구 가상동'), "
        "('1121500000', '서울특별시', '가상구', NULL, '서울특별시 가상구')",
        "INSERT INTO data_snapshot (source, license_type, row_count, status, source_updated_max) "
        "VALUES ('license_file', 'rest_restaurant', 1, 'validated', '2026-10-07 22:47:53+09'), "
        "('license_file', 'bakery', 1, 'validated', '2026-10-08 09:00:00+09')",
        "INSERT INTO closure_surge_day (jurisdiction_code, closed_on, jurisdiction_label, "
        "closure_count, median_daily, parse_version) VALUES "
        "('3040000', '2012-03-31', '가상구', 412, 3.0, 'v'), "
        "('3040000', '2003-02-28', NULL, 230, 2.0, 'v')",
        "INSERT INTO parcel (pnu, legal_dong_code, jibun_label, road_addr, geom, floors, "
        f"record_count) VALUES ('{P_MAIN}', '1121510700', '서울특별시 가상구 가상동 47-1', "
        "'서울특별시 가상구 가상로 12', ST_GeomFromEWKT('SRID=4326;POINT(127.07 37.54)'), "
        "'{B1,1,2,3}', 15), "
        f"('{P_NO_FLOOR}', '1121510700', '서울특별시 가상구 가상동 48', NULL, NULL, '{{}}', 1)",
    ]
    for rid, mgmt, status, opened, closed, floor, ho, bulk, stale, mobile, pnu in RECORDS:
        values = ", ".join(
            [
                str(rid),
                "'general_restaurant'",
                f"'{mgmt}'",
                "'3040000'",
                f"'가상업소 {mgmt}'",
                "'한식'",
                f"'{status}'",
                f"'{status}'",
                "NULL" if opened is None else f"'{opened}'",
                "NULL" if closed is None else f"'{closed}'",
                f"'{pnu}'",
                "NULL" if floor is None else f"'{floor}'",
                f"'{ho}'",
                str(bulk).lower(),
                str(stale).lower(),
                str(mobile).lower(),
                "'v'",
            ]
        )
        statements.append(
            "INSERT INTO license_record (id, license_type, mgmt_no, jurisdiction_code, name, "
            "biz_category, status, status_raw, opened_on, closed_on, pnu, floor, ho_list, "
            f"bulk_closure, stale_suspect, no_fixed_place, parse_version) VALUES ({values})"
        )
    for rid in SUPPRESSED:
        statements.append(
            f"INSERT INTO record_suppression (record_id, reason) VALUES ({rid}, '가상 사유')"
        )
    for floor, count, since, open_now, median, concurrent, max_c in SUMMARIES:
        statements.append(
            "INSERT INTO floor_summary (pnu, floor, record_count, records_since_2005, "
            "open_now_count, median_closed_tenure_days, has_concurrent, max_concurrent, "
            f"method_version) VALUES ('{P_MAIN}', '{floor}', {count}, {since}, {open_now}, "
            f"{'NULL' if median is None else median}, {str(concurrent).lower()}, {max_c}, "
            f"'{METHOD}')"
        )
    for snapshot, scale, scope, bucket, n in RATES:
        statements.append(
            "INSERT INTO base_rate (snapshot_label, method_version, scope_code, floor_scale, "
            "prior_bucket, n, events, rate, ci_low, ci_high, cohort_from, cohort_to) VALUES "
            f"('{snapshot}', '{METHOD}', '{scope}', '{scale}', '{bucket}', {n}, 1, "
            "0.4310, 0.3920, 0.4710, '2005-01-01', '2023-10-08')"
        )
    statements.append(
        "INSERT INTO license_raw (snapshot_id, license_type, mgmt_no, payload) "
        "SELECT id, 'general_restaurant', 'A1', "
        f"jsonb_build_object('소재지전화', '{PHONE_MARKER}') FROM data_snapshot LIMIT 1"
    )
    if with_card:
        statements += [
            "INSERT INTO model_card (snapshot_label, method_version, payload) VALUES "
            f"('2026-09', '{METHOD}', '{_card({'single': True, 'small': True, 'large': True})}')",
            "INSERT INTO model_card (snapshot_label, method_version, payload) VALUES "
            f"('{SNAPSHOT}', '{METHOD}', '{_card(HOLDS)}')",
            # w0 재현 카드는 더 최근이어도 쓰지 않는다
            "INSERT INTO model_card (snapshot_label, method_version, payload) VALUES "
            f"('{SNAPSHOT}', 'w0', '{{}}')",
        ]
    return statements


def _run(url: str, statements: list[str]) -> None:
    async def go() -> None:
        engine = create_async_engine(url, poolclass=NullPool)
        try:
            async with engine.begin() as conn:
                for statement in statements:
                    await conn.execute(text(statement))
        finally:
            await engine.dispose()

    asyncio.run(go())


def _client(url: str, monkeypatch: pytest.MonkeyPatch) -> Iterator[TestClient]:
    engine: AsyncEngine = create_async_engine(url, poolclass=NullPool)
    monkeypatch.setattr(queries, "get_engine", lambda: engine)
    lookup_limiter.reset()
    with TestClient(app) as client:
        yield client
    lookup_limiter.reset()


@pytest.fixture
def api(migrated_db_url: str, monkeypatch: pytest.MonkeyPatch) -> Iterator[TestClient]:
    _run(migrated_db_url, _seed_statements(with_card=True))
    yield from _client(migrated_db_url, monkeypatch)


@pytest.fixture
def api_without_card(migrated_db_url: str, monkeypatch: pytest.MonkeyPatch) -> Iterator[TestClient]:
    _run(migrated_db_url, _seed_statements(with_card=False))
    yield from _client(migrated_db_url, monkeypatch)


def place(client: TestClient, pnu: str = P_MAIN) -> Any:
    response = client.get(f"/api/v1/places/{pnu}")
    assert response.status_code == 200, response.text
    return response.json()


def floor(client: TestClient, name: str, pnu: str = P_MAIN) -> Any:
    response = client.get(f"/api/v1/places/{pnu}/floors/{name}")
    assert response.status_code == 200, response.text
    return response.json()["data"]


def test_place_lists_floors_and_floorless_history(api: TestClient) -> None:
    body = place(api)
    data = body["data"]
    assert body["meta"]["data_as_of"] == AS_OF  # 종류별 최신 스냅샷 중 가장 이른 날짜
    assert data["jibun_label"] == "서울특별시 가상구 가상동 47-1"
    assert data["road_addr"] == "서울특별시 가상구 가상로 12"
    assert data["location"] == {"lat": pytest.approx(37.54), "lng": pytest.approx(127.07)}
    assert [f["floor"] for f in data["floors"]] == ["B1", "1", "2", "3"]
    assert data["floors"][1] == {"floor": "1", "record_count": 4, "open_now_count": 1}
    # 숨김(E3)·고정된 자리 없음(E4)은 빠지고, 개업일 오름차순
    floorless = data["history_without_floor"]
    assert [r["record_id"] for r in floorless] == [51, 52]
    assert data["records_without_floor"] == len(floorless) == 2
    assert floorless[0] == {
        "record_id": 51,
        "name": "가상업소 E1",
        "license_type": "general_restaurant",
        "biz_category": "한식",
        "opened_on": "1998-05-11",
        "closed_on": "2003-02-28",
        "status": "closed",
        "tenure_days": 1754,
        "ho_list": [],
        "bulk_closure": True,
        # 관할 이름을 정할 수 없었던 날: 이름은 null, 건수는 그대로
        "bulk_closure_detail": {"jurisdiction_label": None, "closure_count": 230},
    }
    assert floorless[1]["tenure_days"] == 3932  # 영업 중: 기준일 2026-10-07까지
    assert floorless[1]["bulk_closure_detail"] is None
    assert "stale_suspect" not in floorless[0]


def test_parcel_without_any_floor_is_normal(api: TestClient) -> None:
    data = place(api, P_NO_FLOOR)["data"]
    assert data["floors"] == [] and data["location"] is None and data["road_addr"] is None
    assert data["records_without_floor"] == 1
    assert [r["record_id"] for r in data["history_without_floor"]] == [61]


def test_floor_history_summary_and_groups(api: TestClient) -> None:
    data = floor(api, "1")
    assert data["data_as_of"] == AS_OF
    # 숨김(A4)·고정된 자리 없음(A5)은 빠진다
    assert [r["record_id"] for r in data["history"]] == [11, 12, 13]
    assert data["summary"] == {
        "record_count": 4,
        "records_since_2005": 3,
        "open_now_count": 1,
        "median_closed_tenure_days": 1611,
        "has_concurrent": False,
        "max_concurrent": 1,
    }
    bulk = data["history"][1]
    assert bulk["bulk_closure"] is True
    assert bulk["bulk_closure_detail"] == {"jurisdiction_label": "가상구", "closure_count": 412}
    assert data["history"][0]["bulk_closure_detail"] is None
    assert data["history"][2]["stale_suspect"] is True
    assert data["ho_groups"] == [{"ho": "101", "record_ids": [11, 12, 13]}]  # 102는 1건뿐


def test_single_scale_uses_sigungu_when_n_is_enough(api: TestClient) -> None:
    rate = floor(api, "1")["base_rate"]
    assert rate["display"] is True and rate["hidden_reason"] is None
    assert rate["floor_scale"] == "single"
    # 과거 폐업: A1만. 급증일 폐업 A2와 숨김 A4는 세지 않는다 (docs/10 §7.2 화면 정의)
    assert rate["prior_closures_now"] == 1 and rate["bucket"] == "1"
    assert rate["primary"] == {
        "scope_code": GU,
        "scope_label": "가상구",
        "rate": "0.4310",
        "ci": ["0.3920", "0.4710"],
        "n": 250,
    }
    assert rate["secondary"]["scope_code"] == SEOUL and rate["secondary"]["scope_label"] == "서울"
    assert rate["secondary"]["n"] == 21000
    assert rate["baseline"] == {
        "scope_code": GU,
        "bucket": "0",
        "rate": "0.4310",
        "ci": ["0.3920", "0.4710"],
        "n": 900,
    }
    assert rate["snapshot_label"] == SNAPSHOT and rate["method_version"] == METHOD


def test_small_scale_falls_back_to_seoul(api: TestClient) -> None:
    rate = floor(api, "2")["base_rate"]
    assert rate["floor_scale"] == "small" and rate["bucket"] == "0"
    assert rate["display"] is True
    assert rate["primary"]["scope_code"] == SEOUL and rate["primary"]["n"] == 5000
    assert rate["secondary"] is None
    assert rate["baseline"]["scope_code"] == SEOUL and rate["baseline"]["n"] == 5000


def test_large_scale_is_hidden_as_not_confirmed(api: TestClient) -> None:
    # 최신 카드에서 대형은 깨졌다. 예전 카드의 대형 행도, 'all' 행도 대신 쓰지 않는다
    rate = floor(api, "3")["base_rate"]
    assert rate["floor_scale"] == "large"
    assert rate["display"] is False
    assert rate["hidden_reason"] == "not_confirmed_for_floor_scale"
    assert rate["primary"] is None and rate["baseline"] is None and rate["secondary"] is None
    assert rate["prior_closures_now"] == 1 and rate["bucket"] == "1"


def test_insufficient_sample_is_hidden(api: TestClient) -> None:
    # 단독 4+: 시군구 행 없음, 서울 n = 150 < 200. 'all'의 4+ 행(n 충분)은 쓰지 않는다
    rate = floor(api, "B1")["base_rate"]
    assert rate["floor_scale"] == "single" and rate["bucket"] == "4+"
    assert rate["display"] is False and rate["hidden_reason"] == "insufficient_sample"
    assert rate["primary"] is None and rate["baseline"] is None and rate["secondary"] is None


def test_notices_each_kind(api: TestClient) -> None:
    assert floor(api, "1")["notices"] == [
        "bulk_closure_present",
        "stale_suspect_present",
        "pre_2005_floor_missing",  # 같은 필지의 층 미상 기록 E1(1998년 개업)
    ]
    assert floor(api, "2")["notices"] == ["multiple_units_possible", "pre_2005_floor_missing"]


def test_pre_2005_notice_ignores_hidden_records(api: TestClient, migrated_db_url: str) -> None:
    _run(
        migrated_db_url, ["INSERT INTO record_suppression (record_id, reason) VALUES (51, '가상')"]
    )
    # E1이 숨겨지면 남은 2005년 전 층 미상 기록은 숨김 E3·고정된 자리 없음 E4뿐이다
    assert floor(api, "2")["notices"] == ["multiple_units_possible"]


def test_base_rate_is_null_without_model_card(api_without_card: TestClient) -> None:
    data = floor(api_without_card, "1")
    assert data["base_rate"] is None
    assert [r["record_id"] for r in data["history"]] == [11, 12, 13]


def test_errors(api: TestClient) -> None:
    for path, field in (
        ("/api/v1/places/123", "pnu"),
        ("/api/v1/places/12345678901234567890", "pnu"),
        ("/api/v1/places/123/floors/1", "pnu"),
        (f"/api/v1/places/{P_MAIN}/floors/0", "floor"),
        (f"/api/v1/places/{P_MAIN}/floors/b1", "floor"),
        (f"/api/v1/places/{P_MAIN}/floors/B10", "floor"),
    ):
        response = api.get(path)
        assert response.status_code == 422, path
        assert response.json()["error"]["details"] == {"fields": {field: "invalid_format"}}
    for path in (
        f"/api/v1/places/{P_MISSING}",
        f"/api/v1/places/{P_MISSING}/floors/1",
        f"/api/v1/places/{P_MAIN}/floors/7",
        f"/api/v1/places/{P_NO_FLOOR}/floors/1",
    ):
        response = api.get(path)
        assert response.status_code == 404, path
        assert response.json()["error"]["code"] == "NO_HISTORY"


def test_cache_header(api: TestClient) -> None:
    for path in (f"/api/v1/places/{P_MAIN}", f"/api/v1/places/{P_MAIN}/floors/1"):
        assert api.get(path).headers["Cache-Control"] == "public, max-age=300"


def test_db_failure_is_503(api: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    def broken() -> AsyncEngine:
        raise ConnectionRefusedError("refused")

    monkeypatch.setattr(queries, "get_engine", broken)
    for path in (f"/api/v1/places/{P_MAIN}", f"/api/v1/places/{P_MAIN}/floors/1"):
        response = api.get(path)
        assert response.status_code == 503
        assert response.json()["error"]["code"] == "SERVICE_UNAVAILABLE"
        assert "refused" not in response.text


_PHONE_KEY = re.compile(r"phone|tel|mobile|contact|전화|연락", re.I)


def _keys(value: Any) -> Iterator[str]:
    if isinstance(value, dict):
        for key, item in value.items():
            yield key
            yield from _keys(item)
    elif isinstance(value, list):
        for item in value:
            yield from _keys(item)


def test_place_response_no_phone(api: TestClient) -> None:
    # 원본 행(`license_raw.payload`)에만 있는 전화번호가 응답으로 나오지 않는다 (AGENTS.md §2-7)
    responses = [api.get(f"/api/v1/places/{P_MAIN}")] + [
        api.get(f"/api/v1/places/{P_MAIN}/floors/{f}") for f in ("B1", "1", "2", "3")
    ]
    for response in responses:
        assert response.status_code == 200
        assert not [key for key in _keys(response.json()) if _PHONE_KEY.search(key)]
        assert PHONE_MARKER not in response.text and "000-0000-0000" not in response.text
    schema = json.dumps(api.get("/openapi.json").json()["components"]["schemas"])
    assert re.search(r'"(phone|tel)\w*"', schema, re.I) is None


def test_hidden_record_changes_bucket(api: TestClient, migrated_db_url: str) -> None:
    # 지하 1층: 폐업 4건 → 4+ (서울 n 150, 숨김). D4를 숨기면 3건 → 버킷 3 (서울 n 500, 표시)
    before = floor(api, "B1")["base_rate"]
    assert before["bucket"] == "4+" and before["hidden_reason"] == "insufficient_sample"
    _run(
        migrated_db_url, ["INSERT INTO record_suppression (record_id, reason) VALUES (44, '가상')"]
    )
    data = floor(api, "B1")
    after = data["base_rate"]
    assert after["prior_closures_now"] == 3 and after["bucket"] == "3"
    assert after["display"] is True and after["primary"]["n"] == 500
    # 화면 이력에서 빠진 기록 수와 숫자가 맞는다
    closed = [r for r in data["history"] if r["status"] == "closed" and not r["bulk_closure"]]
    assert len(closed) == after["prior_closures_now"]
