"""웹 재생성 호출 (docs/30 §3): 대상 경로, 비밀 헤더, 재시도. HTTP는 목(`MockTransport`)."""

import asyncio
import json
import logging

import httpx2
import pytest

from app.admin import revalidate

URL = "https://web.example.test/api/revalidate"  # 가상 예시
SECRET = "test-secret-virtual"  # 가상 예시
PATHS = ["/place/1121510700100470001", "/place/1121510700100470001/1"]


@pytest.fixture
def calls(monkeypatch: pytest.MonkeyPatch) -> list[httpx2.Request]:
    monkeypatch.setenv("WEB_REVALIDATE_URL", URL)
    monkeypatch.setenv("REVALIDATE_SECRET", SECRET)

    async def no_sleep(_: float) -> None:
        return None

    monkeypatch.setattr(revalidate, "sleep", no_sleep)
    return []


def _use(monkeypatch: pytest.MonkeyPatch, calls: list[httpx2.Request], statuses: list[int]) -> None:
    def handler(request: httpx2.Request) -> httpx2.Response:
        calls.append(request)
        status = statuses[min(len(calls), len(statuses)) - 1]
        if status == 0:
            raise httpx2.ConnectError("가상 연결 실패")
        return httpx2.Response(status, json={"revalidated": True})

    monkeypatch.setattr(revalidate, "transport", httpx2.MockTransport(handler))


def test_posts_two_paths_with_secret_header(
    monkeypatch: pytest.MonkeyPatch, calls: list[httpx2.Request]
) -> None:
    _use(monkeypatch, calls, [200])
    assert asyncio.run(revalidate.revalidate(PATHS, 55)) is True
    assert len(calls) == 1
    request = calls[0]
    assert request.method == "POST" and str(request.url) == URL
    assert request.headers["x-revalidate-secret"] == SECRET
    assert json.loads(request.content) == {"paths": PATHS}


def test_retries_until_success(
    monkeypatch: pytest.MonkeyPatch, calls: list[httpx2.Request]
) -> None:
    _use(monkeypatch, calls, [0, 503, 200])
    assert asyncio.run(revalidate.revalidate(PATHS, 55)) is True
    assert len(calls) == 3


def test_gives_up_after_three_attempts_and_logs_without_secret(
    monkeypatch: pytest.MonkeyPatch,
    calls: list[httpx2.Request],
    caplog: pytest.LogCaptureFixture,
) -> None:
    _use(monkeypatch, calls, [401])
    with caplog.at_level(logging.WARNING):
        assert asyncio.run(revalidate.revalidate(PATHS, 55)) is False
    assert len(calls) == revalidate.ATTEMPTS == 3
    assert "correction_id=55" in caplog.text and "status 401" in caplog.text
    assert SECRET not in caplog.text


def test_not_configured_is_failure(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    monkeypatch.delenv("WEB_REVALIDATE_URL", raising=False)
    monkeypatch.delenv("REVALIDATE_SECRET", raising=False)
    with caplog.at_level(logging.WARNING):
        assert asyncio.run(revalidate.revalidate(PATHS, 7)) is False
    assert "not configured" in caplog.text
