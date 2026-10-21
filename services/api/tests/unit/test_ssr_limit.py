"""서버 렌더링 공유 한도 (docs/30 §1, ADR-031). 비밀 값은 가상 예시."""

import logging
from collections.abc import Iterator

import pytest
from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient

from app.core.errors import register_error_handlers
from app.core.ratelimit import (
    LOOKUP_LIMIT_PER_MINUTE,
    SSR_LOOKUP_LIMIT_PER_MINUTE,
    SSR_SECRET_HEADER,
    limit_lookup,
    lookup_limiter,
    ssr_limiter,
)

SECRET = "virtual-example-ssr-secret"  # 가상 예시 (헤더 값은 ASCII)
URL = "/limited"

app = FastAPI()
register_error_handlers(app)


@app.get(URL, dependencies=[Depends(limit_lookup)])
def limited() -> dict[str, str]:
    return {"ok": "yes"}


client = TestClient(app)


@pytest.fixture(autouse=True)
def fresh_limits(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    monkeypatch.setenv("API_SSR_SECRET", SECRET)
    lookup_limiter.reset()
    ssr_limiter.reset()
    yield
    lookup_limiter.reset()
    ssr_limiter.reset()


def _codes(n: int, headers: dict[str, str] | None = None) -> list[int]:
    return [client.get(URL, headers=headers).status_code for _ in range(n)]


def test_limit_matches_adr() -> None:
    assert SSR_LOOKUP_LIMIT_PER_MINUTE == 600
    assert SSR_SECRET_HEADER == "x-ssr-secret"


def test_matching_secret_uses_shared_limit_instead_of_ip() -> None:
    codes = _codes(SSR_LOOKUP_LIMIT_PER_MINUTE, {SSR_SECRET_HEADER: SECRET})
    assert codes == [200] * SSR_LOOKUP_LIMIT_PER_MINUTE  # IP 한도(120)를 넘어도 통과
    assert len(lookup_limiter) == 0  # IP로 세지 않았다
    over = client.get(URL, headers={SSR_SECRET_HEADER: SECRET})
    assert over.status_code == 429
    assert over.json()["error"]["code"] == "RATE_LIMITED"
    assert int(over.headers["Retry-After"]) >= 1


def test_shared_limit_has_one_key_for_all_web_servers() -> None:
    client.get(URL, headers={SSR_SECRET_HEADER: SECRET})
    assert len(ssr_limiter) == 1
    assert "testclient" not in str(ssr_limiter._windows)  # 접속 주소를 키로 쓰지 않는다


def test_browser_requests_still_count_per_ip() -> None:
    assert _codes(LOOKUP_LIMIT_PER_MINUTE + 1)[-1] == 429
    assert len(ssr_limiter) == 0


def test_wrong_secret_falls_back_to_ip_limit_not_401() -> None:
    codes = _codes(LOOKUP_LIMIT_PER_MINUTE + 1, {SSR_SECRET_HEADER: "virtual-example-wrong"})
    assert codes[:-1] == [200] * LOOKUP_LIMIT_PER_MINUTE
    assert codes[-1] == 429
    assert len(ssr_limiter) == 0


def test_header_ignored_when_api_has_no_secret(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("API_SSR_SECRET")
    assert _codes(LOOKUP_LIMIT_PER_MINUTE + 1, {SSR_SECRET_HEADER: ""})[-1] == 429
    assert len(ssr_limiter) == 0


def test_secret_not_in_response_or_logs(caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.DEBUG)
    response = client.get(URL, headers={SSR_SECRET_HEADER: SECRET})
    assert SECRET not in response.text
    assert SECRET not in "".join(response.headers.values())
    assert SECRET not in caplog.text
