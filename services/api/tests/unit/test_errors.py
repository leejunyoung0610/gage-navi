"""422·500 공통 오류 형식 (docs/30 §1). 입력값·예외 메시지를 응답과 로그에 내지 않는다."""

import logging

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import BaseModel, ConfigDict, Field

from app.core.errors import INTERNAL_MESSAGE, register_error_handlers
from app.core.logging import configure_logging

configure_logging()

SECRET_INPUT = "가상 연락처 010-0000-0000"  # 가상 예시


class Body(BaseModel):
    model_config = ConfigDict(extra="forbid")
    message: str = Field(max_length=5)
    count: int


def _app() -> FastAPI:
    app = FastAPI()
    register_error_handlers(app)

    @app.post("/echo")
    async def echo(body: Body, page: int = 1) -> dict[str, int]:
        return {"page": page}

    @app.get("/boom")
    async def boom() -> None:
        raise RuntimeError(f"db failed with params {SECRET_INPUT}")

    return app


client = TestClient(_app())


def test_validation_error_format_lists_fields_without_input() -> None:
    response = client.post("/echo?page=x", json={"message": SECRET_INPUT, "extra": SECRET_INPUT})
    assert response.status_code == 422
    body = response.json()
    assert body["error"]["code"] == "VALIDATION_ERROR"
    assert body["error"]["details"] == {
        "fields": {
            "page": "int_parsing",
            "message": "string_too_long",
            "count": "missing",
            "extra": "extra_forbidden",
        }
    }
    assert len(body["meta"]["request_id"]) == 26
    assert SECRET_INPUT not in response.text and "010" not in response.text


def test_validation_error_for_non_json_body() -> None:
    response = client.post(
        "/echo", content=b"not json", headers={"content-type": "application/json"}
    )
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "VALIDATION_ERROR"


def test_unhandled_exception_is_internal_with_generic_message(
    caplog: pytest.LogCaptureFixture,
) -> None:
    with caplog.at_level(logging.DEBUG):
        response = client.get("/boom")
    assert response.status_code == 500
    body = response.json()
    assert body["error"] == {"code": "INTERNAL", "message": INTERNAL_MESSAGE, "details": {}}
    assert SECRET_INPUT not in response.text
    # 로그에는 요청 ID·경로·예외 종류만
    errors = [r for r in caplog.records if r.name == "app.core.errors"]
    assert "RuntimeError" in caplog.text
    assert [r.request_id for r in errors] == [body["meta"]["request_id"]]  # type: ignore[attr-defined]
    assert SECRET_INPUT not in caplog.text
