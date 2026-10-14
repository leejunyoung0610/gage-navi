"""관리자 인증·정정 요청 통합 테스트 (T-023, docs/30 §2·§3). 필지·업소·계정·날짜는 모두 가상 예시다.

요약 테이블은 `jobs.build_history`로 만든 뒤, 숨김 처리 때의 필지 재계산이 전체 빌드와 같은지 본다.
웹 재생성 호출은 HTTP 목(`MockTransport`)이다.
"""

import asyncio
import json
import logging
from collections.abc import Awaitable, Callable, Iterator
from datetime import UTC, datetime, timedelta
from typing import Any

import httpx2
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine
from sqlalchemy.pool import NullPool

from app.admin import auth, revalidate
from app.core import db
from app.core.ratelimit import correction_limiter, lookup_limiter
from app.location.history.job import build_history
from app.location.places import queries
from app.main import app
from jobs.correction_maintenance import maintain

P1 = "1121510700100470001"
P2 = "1121510700100480000"
USERNAME, PASSWORD = "admin", "가상-비밀번호-예시-1234"  # 가상 예시
CONTACT = "가상 연락처 010-0000-0000"  # 가상 예시: 로그에 남으면 안 되는 값
URL = "https://web.example.test/api/revalidate"  # 가상 예시
SECRET = "test-secret-virtual"  # 가상 예시
CSRF = {"X-Admin-Request": "1"}
T0 = datetime(2026, 10, 14, 9, 0, tzinfo=UTC)
INSERT = """
INSERT INTO license_record
  (id, license_type, mgmt_no, jurisdiction_code, name, biz_category, status, status_raw,
   opened_on, closed_on, road_addr, pnu, floor, geom, bulk_closure, no_fixed_place, parse_version)
VALUES ({id}, 'general_restaurant', '{mgmt}', '3040000', '가상업소 {mgmt}', '한식', '{status}',
        '{status}', '{opened}', {closed}, '서울특별시 가상구 가상로 {id}', '{pnu}', {floor},
        ST_GeomFromEWKT('SRID=4326;POINT(127.07 37.54)'), false, false, '2026.10.1')
"""
# (id, 관리번호, 상태, 개업일, 폐업일, 층, 필지)
RECORDS = [
    (1, "R1", "open", "2015-01-01", None, "1", P1),
    (2, "R2", "closed", "2010-01-01", "2014-06-30", "1", P1),
    (3, "R3", "open", "2016-01-01", None, "1", P1),  # R1과 동시 영업 → 숨기면 단독
    (4, "R4", "open", "2018-01-01", None, "2", P1),
    (5, "R5", "open", "2019-01-01", None, None, P1),  # 층 미상
    (6, "R6", "open", "2020-01-01", None, "1", P2),  # 숨기면 필지에 보이는 기록이 없다
]
SUMMARY_SQL = (
    "SELECT pnu, floor, record_count, records_since_2005, open_now_count, "
    "median_closed_tenure_days, has_concurrent, max_concurrent, method_version "
    "FROM floor_summary ORDER BY pnu, floor"
)
PARCEL_SQL = (
    "SELECT pnu, legal_dong_code, jibun_label, road_addr, ST_AsEWKT(geom), floors, record_count "
    "FROM parcel ORDER BY pnu"
)


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


def fetch(url: str, sql: str) -> list[tuple[Any, ...]]:
    async def work(engine: AsyncEngine) -> list[tuple[Any, ...]]:
        async with engine.connect() as conn:
            return [tuple(row) for row in await conn.execute(text(sql))]

    rows: list[tuple[Any, ...]] = with_engine(url, work)
    return rows


class Clock:
    def __init__(self) -> None:
        self.at = T0

    def __call__(self) -> datetime:
        return self.at

    def advance(self, **kwargs: float) -> None:
        self.at += timedelta(**kwargs)


@pytest.fixture
def clock(monkeypatch: pytest.MonkeyPatch) -> Clock:
    clock = Clock()
    monkeypatch.setattr(auth, "now", clock)
    return clock


class Web:
    """웹 재생성 목. `status`를 바꾸면 응답 상태가 바뀐다."""

    def __init__(self) -> None:
        self.calls: list[httpx2.Request] = []
        self.status = 200

    def handler(self, request: httpx2.Request) -> httpx2.Response:
        self.calls.append(request)
        return httpx2.Response(self.status, json={})


@pytest.fixture
def web(monkeypatch: pytest.MonkeyPatch) -> Web:
    mock = Web()

    async def no_sleep(_: float) -> None:
        return None

    monkeypatch.setenv("WEB_REVALIDATE_URL", URL)
    monkeypatch.setenv("REVALIDATE_SECRET", SECRET)
    monkeypatch.setattr(revalidate, "transport", httpx2.MockTransport(mock.handler))
    monkeypatch.setattr(revalidate, "sleep", no_sleep)
    return mock


@pytest.fixture
def seeded(migrated_db_url: str) -> str:
    statements = [
        "TRUNCATE license_record, floor_summary, parcel, record_prior, data_snapshot, "
        "legal_dong, correction_request, record_suppression, admin_user, admin_session CASCADE",
        "INSERT INTO legal_dong (code, sido, sigungu, eupmyeondong, full_name) VALUES "
        "('1121510700', '서울특별시', '가상구', '가상동', '서울특별시 가상구 가상동')",
        "INSERT INTO data_snapshot (source, license_type, row_count, status, source_updated_max) "
        "VALUES ('license_file', 'general_restaurant', 6, 'validated', '2026-10-07 22:47:53+09')",
    ]
    for rid, mgmt, status, opened, closed, floor, pnu in RECORDS:
        statements.append(
            INSERT.format(
                id=rid,
                mgmt=mgmt,
                status=status,
                opened=opened,
                closed="NULL" if closed is None else f"'{closed}'",
                pnu=pnu,
                floor="NULL" if floor is None else f"'{floor}'",
            )
        )
    execute(migrated_db_url, *statements)
    with_engine(migrated_db_url, build_history)

    async def create_admin(engine: AsyncEngine) -> None:
        async with engine.begin() as conn:
            await auth.set_password(conn, USERNAME, PASSWORD)

    with_engine(migrated_db_url, create_admin)
    return migrated_db_url


@pytest.fixture
def client(
    seeded: str, monkeypatch: pytest.MonkeyPatch, clock: Clock, web: Web
) -> Iterator[TestClient]:
    engine = create_async_engine(seeded, poolclass=NullPool)
    monkeypatch.setattr(queries, "get_engine", lambda: engine)
    monkeypatch.setattr(db, "get_engine", lambda: engine)
    lookup_limiter.reset()
    correction_limiter.reset()
    # 세션 쿠키는 Secure라 https로 보낸다
    with TestClient(app, base_url="https://testserver") as test_client:
        yield test_client
    lookup_limiter.reset()
    correction_limiter.reset()


def login(client: TestClient, password: str = PASSWORD) -> Any:
    return client.post(
        "/admin/v1/login", json={"username": USERNAME, "password": password}, headers=CSRF
    )


def submit(client: TestClient, record_id: int | None, pnu: str = P1, **extra: Any) -> int:
    body = {"kind": "wrong_info", "message": CONTACT, "record_id": record_id, **extra}
    response = client.post(f"/api/v1/places/{pnu}/corrections", json=body)
    assert response.status_code == 201, response.text
    assert response.headers["cache-control"] == "no-store"
    assert response.headers["x-request-id"] == response.json()["meta"]["request_id"]
    correction_id: int = response.json()["data"]["id"]
    return correction_id


def resolve(client: TestClient, correction_id: int, action: str = "suppress_record") -> Any:
    return client.post(
        f"/admin/v1/corrections/{correction_id}/resolve",
        json={"action": action, "note": "가상 처리 메모"},
        headers=CSRF,
    )


# --- 인증 ---


def test_unauthenticated_is_401(client: TestClient) -> None:
    assert client.get("/admin/v1/corrections").status_code == 401
    assert resolve(client, 1).status_code == 401
    client.cookies.set(auth.SESSION_COOKIE, "fake-token-virtual")
    assert client.get("/admin/v1/corrections").status_code == 401


def test_login_sets_strict_cookie_and_stores_only_hash(client: TestClient, seeded: str) -> None:
    response = login(client)
    assert response.status_code == 200, response.text
    assert response.json()["data"]["username"] == USERNAME
    cookie = response.headers["set-cookie"]
    for part in ("HttpOnly", "Secure", "SameSite=strict", "Path=/admin/v1", "Max-Age=28800"):
        assert part.lower() in cookie.lower(), part
    token = client.cookies[auth.SESSION_COOKIE]
    assert len(token) >= 43  # 32바이트 base64url
    rows = fetch(seeded, "SELECT token_hash, created_at, expires_at FROM admin_session")
    assert len(rows) == 1
    stored, created, expires = rows[0]
    assert bytes(stored) == auth.token_hash(token) and token.encode() not in bytes(stored)
    assert expires - created == timedelta(hours=8)
    assert client.get("/admin/v1/corrections").status_code == 200


def test_five_failures_lock_for_fifteen_minutes(client: TestClient, clock: Clock) -> None:
    for _ in range(5):
        response = login(client, "틀린-비밀번호-가상")
        assert response.status_code == 401
        assert response.json()["error"]["code"] == "UNAUTHORIZED"
        clock.advance(minutes=1)
    locked = login(client)  # 맞는 비밀번호도 잠금 중에는 거부
    assert locked.status_code == 429
    assert locked.json()["error"]["code"] == "RATE_LIMITED"
    assert 0 < int(locked.headers["retry-after"]) <= 15 * 60
    clock.advance(minutes=15)
    assert login(client).status_code == 200


def test_failures_spread_over_window_do_not_lock(client: TestClient, clock: Clock) -> None:
    for _ in range(4):
        assert login(client, "틀린-비밀번호-가상").status_code == 401
    clock.advance(minutes=10)
    assert login(client, "틀린-비밀번호-가상").status_code == 401  # 새 창의 1번째
    assert login(client).status_code == 200


def test_unknown_username_is_same_401(client: TestClient) -> None:
    response = client.post(
        "/admin/v1/login", json={"username": "없는-관리자", "password": PASSWORD}, headers=CSRF
    )
    assert response.status_code == 401
    assert response.json()["error"]["message"] == auth.LOGIN_FAILED_MESSAGE


def test_session_idle_timeout(client: TestClient, clock: Clock, seeded: str) -> None:
    assert login(client).status_code == 200
    clock.advance(minutes=29)
    assert client.get("/admin/v1/corrections").status_code == 200  # 마지막 요청 시각 갱신
    clock.advance(minutes=29)
    assert client.get("/admin/v1/corrections").status_code == 200
    clock.advance(minutes=30)
    assert client.get("/admin/v1/corrections").status_code == 401
    assert fetch(seeded, "SELECT count(*) FROM admin_session") == [(0,)]


def test_session_absolute_timeout(client: TestClient, clock: Clock) -> None:
    assert login(client).status_code == 200
    for _ in range(23):  # 20분마다 쓰면서 7시간 40분
        clock.advance(minutes=20)
        assert client.get("/admin/v1/corrections").status_code == 200
    clock.advance(minutes=20)  # 로그인 후 8시간
    assert client.get("/admin/v1/corrections").status_code == 401


def test_logout_deletes_session_on_server(client: TestClient, seeded: str) -> None:
    assert login(client).status_code == 200
    token = client.cookies[auth.SESSION_COOKIE]
    response = client.post("/admin/v1/logout", headers=CSRF)
    assert response.status_code == 204
    assert fetch(seeded, "SELECT count(*) FROM admin_session") == [(0,)]
    client.cookies.set(auth.SESSION_COOKIE, token)  # 지운 세션의 쿠키를 다시 보내도
    assert client.get("/admin/v1/corrections").status_code == 401


def test_password_change_deletes_all_sessions(client: TestClient, seeded: str) -> None:
    assert login(client).status_code == 200
    assert login(client).status_code == 200

    async def change(engine: AsyncEngine) -> auth.PasswordSet:
        async with engine.begin() as conn:
            return await auth.set_password(conn, USERNAME, "새-가상-비밀번호-5678")

    result = with_engine(seeded, change)
    assert result.created is False and result.sessions_deleted == 2
    assert client.get("/admin/v1/corrections").status_code == 401
    assert login(client).status_code == 401
    assert login(client, "새-가상-비밀번호-5678").status_code == 200


def test_resolve_without_csrf_header_is_403(client: TestClient) -> None:
    correction_id = submit(client, 3)
    assert login(client).status_code == 200
    response = client.post(
        f"/admin/v1/corrections/{correction_id}/resolve", json={"action": "suppress_record"}
    )
    assert response.status_code == 403
    assert (
        client.get("/api/v1/places/" + P1 + "/floors/1").json()["data"]["summary"]["record_count"]
        == 3
    )


# --- 정정 요청 ---


def test_create_checks_parcel_and_record(client: TestClient) -> None:
    def post(pnu: str, **body: Any) -> Any:
        return client.post(
            f"/api/v1/places/{pnu}/corrections",
            json={"kind": "other", "message": "가상", **body},
        )

    assert post("1121510700100490000").json()["error"]["code"] == "NO_HISTORY"
    wrong_place = post(P1, record_id=6)
    assert wrong_place.status_code == 422
    assert wrong_place.json()["error"]["details"] == {"fields": {"record_id": "not_in_place"}}
    wrong_floor = post(P1, record_id=4, floor="1")
    assert wrong_floor.json()["error"]["details"] == {"fields": {"floor": "not_record_floor"}}
    assert post(P1, record_id=4, floor="2").status_code == 201
    assert post(P1).status_code == 201  # 기록을 고르지 않은 요청


def test_correction_rate_limit_five_per_hour(client: TestClient) -> None:
    for _ in range(5):
        submit(client, None)
    response = client.post(
        f"/api/v1/places/{P1}/corrections", json={"kind": "other", "message": "가상"}
    )
    assert response.status_code == 429
    assert "retry-after" in response.headers


def test_correction_body_not_logged(client: TestClient, caplog: pytest.LogCaptureFixture) -> None:
    with caplog.at_level(logging.DEBUG):
        correction_id = submit(client, 3)
        assert login(client).status_code == 200
        assert client.get("/admin/v1/corrections").status_code == 200
        assert resolve(client, correction_id).status_code == 200
    assert "010-0000-0000" not in caplog.text and CONTACT not in caplog.text


def test_suppress_hides_record_and_rebuilds_parcel(
    client: TestClient, web: Web, seeded: str
) -> None:
    before = client.get(f"/api/v1/places/{P1}/floors/1").json()["data"]
    assert [r["record_id"] for r in before["history"]] == [2, 1, 3]
    assert before["summary"]["record_count"] == 3 and before["summary"]["max_concurrent"] == 2
    correction_id = submit(client, 3, floor="1")
    assert login(client).status_code == 200
    listed = client.get("/admin/v1/corrections?status=open").json()["data"]
    assert [(c["id"], c["message"], c["status"]) for c in listed] == [
        (correction_id, CONTACT, "open")
    ]

    response = resolve(client, correction_id)
    assert response.status_code == 200, response.text
    assert response.json()["data"] == {
        "id": correction_id,
        "status": "resolved",
        "revalidated": True,
    }

    after = client.get(f"/api/v1/places/{P1}/floors/1").json()["data"]
    assert [r["record_id"] for r in after["history"]] == [2, 1]
    assert after["summary"]["record_count"] == 2
    assert after["summary"]["has_concurrent"] is False and after["summary"]["max_concurrent"] == 1
    assert after["base_rate"] is None or after["base_rate"]["floor_scale"] == "single"
    place = client.get(f"/api/v1/places/{P1}").json()["data"]
    assert {"floor": "1", "record_count": 2, "open_now_count": 1} in place["floors"]
    rows = fetch(
        seeded,
        f"SELECT status, resolution_note, resolved_at IS NOT NULL, revalidated_at IS NOT NULL "
        f"FROM correction_request WHERE id = {correction_id}",
    )
    assert rows == [("resolved", "가상 처리 메모", True, True)]
    assert fetch(seeded, "SELECT record_id, reason, request_id FROM record_suppression") == [
        (3, "wrong_info", correction_id)
    ]


def test_revalidate_called_after_commit_with_two_paths_and_secret(
    client: TestClient, web: Web
) -> None:
    correction_id = submit(client, 3)
    assert login(client).status_code == 200
    assert resolve(client, correction_id).status_code == 200
    assert len(web.calls) == 1
    request = web.calls[0]
    assert str(request.url) == URL
    assert request.headers["x-revalidate-secret"] == SECRET
    assert json.loads(request.content) == {"paths": [f"/place/{P1}", f"/place/{P1}/1"]}


def test_floorless_record_revalidates_place_page_only(client: TestClient, web: Web) -> None:
    correction_id = submit(client, 5)
    assert login(client).status_code == 200
    assert resolve(client, correction_id).status_code == 200
    assert json.loads(web.calls[0].content) == {"paths": [f"/place/{P1}"]}
    data = client.get(f"/api/v1/places/{P1}").json()["data"]
    assert data["records_without_floor"] == 0 and data["history_without_floor"] == []


def test_revalidate_failure_keeps_suppression_and_is_retried(
    client: TestClient, web: Web, seeded: str
) -> None:
    web.status = 500
    correction_id = submit(client, 3)
    assert login(client).status_code == 200
    response = resolve(client, correction_id)
    assert response.status_code == 200
    assert response.json()["data"]["revalidated"] is False
    assert len(web.calls) == revalidate.ATTEMPTS
    assert fetch(seeded, "SELECT count(*) FROM record_suppression") == [(1,)]
    assert fetch(seeded, "SELECT revalidated_at FROM correction_request") == [(None,)]
    history = client.get(f"/api/v1/places/{P1}/floors/1").json()["data"]["history"]
    assert 3 not in [r["record_id"] for r in history]

    web.status = 200
    result = with_engine(seeded, lambda engine: maintain(engine, T0))
    assert (result.revalidation_pending, result.revalidated) == (1, 1)
    assert json.loads(web.calls[-1].content)["paths"] == [f"/place/{P1}", f"/place/{P1}/1"]
    assert fetch(seeded, "SELECT revalidated_at IS NOT NULL FROM correction_request") == [(True,)]
    again = with_engine(seeded, lambda engine: maintain(engine, T0))
    assert again.revalidation_pending == 0


def test_none_rejects_without_hiding_and_conflicts_after(
    client: TestClient, web: Web, seeded: str
) -> None:
    correction_id = submit(client, 3)
    no_record = submit(client, None)
    assert login(client).status_code == 200
    response = resolve(client, correction_id, "none")
    assert response.json()["data"] == {
        "id": correction_id,
        "status": "rejected",
        "revalidated": False,
    }
    assert web.calls == [] and fetch(seeded, "SELECT count(*) FROM record_suppression") == [(0,)]
    assert resolve(client, correction_id).status_code == 409
    missing = resolve(client, no_record)
    assert missing.status_code == 422
    assert missing.json()["error"]["details"] == {"fields": {"action": "no_record"}}
    assert resolve(client, 999999).status_code == 404


def test_reject_requires_note(client: TestClient, web: Web, seeded: str) -> None:
    """`none`(→ `rejected`)은 사유가 비었거나 공백뿐이면 422, 요청은 그대로 `open`."""
    correction_id = submit(client, 3)
    assert login(client).status_code == 200
    url = f"/admin/v1/corrections/{correction_id}/resolve"
    for body in (
        {"action": "none"},
        {"action": "none", "note": None},
        {"action": "none", "note": ""},
        {"action": "none", "note": " \n\t "},
    ):
        response = client.post(url, json=body, headers=CSRF)
        assert response.status_code == 422, body
        error = response.json()["error"]
        assert error["code"] == "VALIDATION_ERROR"
        assert error["details"] == {"fields": {"note": "note_required"}}
        assert response.headers["X-Request-ID"] == response.json()["meta"]["request_id"]
    assert fetch(seeded, "SELECT status, resolution_note FROM correction_request") == [
        ("open", None)
    ]
    # 숨김(`suppress_record`)은 메모 없이도 된다
    assert client.post(url, json={"action": "suppress_record"}, headers=CSRF).status_code == 200


def test_rebuild_matches_full_build(client: TestClient, seeded: str) -> None:
    """숨긴 기록이 있는 필지: 즉시 재계산 결과 = 전체 `build_history` 결과 (docs/10 §7.1)."""
    ids = [submit(client, 3), submit(client, 5), submit(client, 6, pnu=P2)]
    assert login(client).status_code == 200
    for correction_id in ids:
        assert resolve(client, correction_id).status_code == 200
    rebuilt = (fetch(seeded, PARCEL_SQL), fetch(seeded, SUMMARY_SQL))
    assert [row[0] for row in rebuilt[0]] == [P1]  # P2는 보이는 기록이 없어 빠졌다
    assert client.get(f"/api/v1/places/{P2}").json()["error"]["code"] == "NO_HISTORY"

    with_engine(seeded, build_history)
    assert (fetch(seeded, PARCEL_SQL), fetch(seeded, SUMMARY_SQL)) == rebuilt


def test_messages_deleted_one_year_after_resolution(client: TestClient, seeded: str) -> None:
    def insert(status: str, resolved: datetime | None) -> str:
        at = "NULL" if resolved is None else f"'{resolved.isoformat()}'"
        return (
            "INSERT INTO correction_request (pnu, kind, message, status, resolved_at) "
            f"VALUES ('{P1}', 'other', '{CONTACT}', '{status}', {at})"
        )

    execute(
        seeded,
        insert("resolved", T0 - timedelta(days=366)),
        insert("rejected", T0 - timedelta(days=364)),
        insert("open", None),
    )
    assert login(client).status_code == 200
    listed = client.get("/admin/v1/corrections").json()["data"]
    messages = {c["status"]: c["message"] for c in listed}
    assert messages == {"resolved": "", "rejected": CONTACT, "open": CONTACT}
    # 행과 처리 결과는 남는다
    assert fetch(
        seeded, "SELECT count(*) FROM correction_request WHERE resolved_at IS NOT NULL"
    ) == [(2,)]


def test_error_id_shown_to_user_finds_server_log(
    client: TestClient, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    """사용자가 오류 화면의 ID를 알려 주면 그 요청의 로그를 찾을 수 있다 (docs/30 §1)."""
    from app.location.corrections import store

    async def broken(*_: Any) -> int:
        raise RuntimeError("가상 DB 장애")

    submit(client, None)
    monkeypatch.setattr(store, "create", broken)
    with caplog.at_level(logging.INFO, logger="app"):
        response = client.post(
            f"/api/v1/places/{P1}/corrections", json={"kind": "other", "message": CONTACT}
        )
    assert response.status_code == 503
    shown = response.json()["meta"]["request_id"]
    assert response.headers["x-request-id"] == shown
    found = [r for r in caplog.records if getattr(r, "request_id", None) == shown]
    names = {r.name for r in found}
    assert {"app.location.corrections.router", "app.access"} <= names
    assert any("RuntimeError" in r.getMessage() for r in found)
    assert all(CONTACT not in r.getMessage() for r in caplog.records)
