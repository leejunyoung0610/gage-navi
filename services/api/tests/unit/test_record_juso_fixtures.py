"""녹화 잡: 픽스처에 승인키를 남기지 않는다 (T-021). 승인키·응답은 가상 예시다."""

import asyncio
import json
from pathlib import Path
from typing import Any

import httpx2
import pytest

from jobs import record_juso_fixtures as job

FAKE_KEY = "TEST-KEY-가상-0123456789"


def test_scrub() -> None:
    assert job.scrub(f"a {FAKE_KEY} b {FAKE_KEY}", FAKE_KEY) == "a <REDACTED> b <REDACTED>"
    assert job.scrub("그대로", "") == "그대로"


def test_fixture_text_has_no_key_even_if_response_echoes_it() -> None:
    echoed = {"results": {"common": {"errorMessage": f"key={FAKE_KEY}"}, "juso": []}}
    text = job.fixture_text("가상로 1", 1, "2026-10-13", echoed, FAKE_KEY)
    assert FAKE_KEY not in text
    document = json.loads(text)
    assert set(document) == {"source", "recorded_on", "request", "response"}
    assert document["request"] == {"keyword": "가상로 1", "currentPage": 1, "countPerPage": 10}
    assert "confmKey" not in text


def test_record_writes_scrubbed_files(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    def handler(request: httpx2.Request) -> httpx2.Response:
        body: dict[str, Any] = {
            "results": {
                "common": {"errorCode": "0", "errorMessage": FAKE_KEY, "totalCount": "0"},
                "juso": [],
            }
        }
        return httpx2.Response(200, json=body)

    real_client = httpx2.AsyncClient
    monkeypatch.setattr(
        job.httpx2, "AsyncClient", lambda: real_client(transport=httpx2.MockTransport(handler))
    )
    monkeypatch.setattr(job, "PAUSE_SECONDS", 0.0)
    failures = asyncio.run(job.record(FAKE_KEY, "2026-10-13", tmp_path))
    assert failures == 0
    files = sorted(tmp_path.glob("*.json"))
    assert [f.stem for f in files] == sorted(name for name, _, _ in job.CASES)
    for path in files:
        assert FAKE_KEY not in path.read_text(encoding="utf-8")
    assert FAKE_KEY not in capsys.readouterr().out


def test_main_without_key_prints_no_secret(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.delenv("JUSO_CONFM_KEY", raising=False)
    monkeypatch.setattr("sys.argv", ["record_juso_fixtures", "--recorded-on", "2026-10-13"])
    assert job.main() == 2
    assert "JUSO_CONFM_KEY" in capsys.readouterr().out
