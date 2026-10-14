"""관리자 인증: 잠금 계산, CSRF 헤더, 미인증 401 (docs/30 §3). DB가 필요한 흐름은 통합 테스트."""

from datetime import UTC, datetime, timedelta

from fastapi.testclient import TestClient

from app.admin.auth import (
    LOCK_DURATION,
    MAX_FAILURES,
    hash_password,
    register_failure,
    token_hash,
)
from app.main import app

T0 = datetime(2026, 10, 14, 9, 0, tzinfo=UTC)
client = TestClient(app, base_url="https://testserver")


def test_fifth_failure_within_ten_minutes_locks_for_fifteen() -> None:
    count, started = 0, None
    for i in range(MAX_FAILURES - 1):
        state = register_failure(count, started, T0 + timedelta(minutes=2 * i))
        assert state.locked_until is None
        count, started = state.count, state.started_at
    assert (count, started) == (4, T0)
    state = register_failure(count, started, T0 + timedelta(minutes=9, seconds=59))
    assert state.locked_until == T0 + timedelta(minutes=9, seconds=59) + LOCK_DURATION
    assert (state.count, state.started_at) == (0, None)


def test_failures_older_than_window_start_over() -> None:
    state = register_failure(4, T0, T0 + timedelta(minutes=10))
    assert state.locked_until is None
    assert (state.count, state.started_at) == (1, T0 + timedelta(minutes=10))


def test_password_hash_is_argon2id_and_token_hash_is_sha256() -> None:
    hashed = hash_password("가상 비밀번호 예시 12345")
    assert hashed.startswith("$argon2id$") and "가상" not in hashed
    assert len(token_hash("가상-토큰")) == 32


def test_admin_requires_session() -> None:
    response = client.get("/admin/v1/corrections")
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "UNAUTHORIZED"
    response = client.post(
        "/admin/v1/corrections/1/resolve",
        json={"action": "none"},
        headers={"X-Admin-Request": "1"},
    )
    assert response.status_code == 401


def test_state_changing_admin_requests_need_csrf_header() -> None:
    for path, body in (
        ("/admin/v1/login", {"username": "가상", "password": "가상"}),
        ("/admin/v1/logout", None),
        ("/admin/v1/corrections/1/resolve", {"action": "none"}),
    ):
        response = client.post(path, json=body)
        assert response.status_code == 403, path
        assert response.json()["error"]["code"] == "FORBIDDEN"
    wrong = client.post("/admin/v1/logout", headers={"X-Admin-Request": "yes"})
    assert wrong.status_code == 403
