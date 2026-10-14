"""공통 오류 응답 (docs/30 §1). 오류 코드는 문서의 표에 있는 것만 쓴다.

요청 검증 실패(422)와 처리되지 않은 예외(500)도 같은 형식으로 낸다. 어느 쪽도 입력값이나
예외 메시지를 응답·로그에 넣지 않는다(정정 요청 메시지에 연락처가 들어올 수 있다).
"""

import logging
from enum import StrEnum
from typing import Any

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from app.core.request_id import new_request_id


class ErrorCode(StrEnum):
    VALIDATION_ERROR = "VALIDATION_ERROR"
    NOT_FOUND = "NOT_FOUND"
    NO_HISTORY = "NO_HISTORY"
    RATE_LIMITED = "RATE_LIMITED"
    UPSTREAM_UNAVAILABLE = "UPSTREAM_UNAVAILABLE"
    SERVICE_UNAVAILABLE = "SERVICE_UNAVAILABLE"
    UNAUTHORIZED = "UNAUTHORIZED"
    FORBIDDEN = "FORBIDDEN"
    CONFLICT = "CONFLICT"
    INTERNAL = "INTERNAL"


HTTP_STATUS: dict[ErrorCode, int] = {
    ErrorCode.VALIDATION_ERROR: 422,
    ErrorCode.NOT_FOUND: 404,
    ErrorCode.NO_HISTORY: 404,
    ErrorCode.RATE_LIMITED: 429,
    ErrorCode.UPSTREAM_UNAVAILABLE: 502,
    ErrorCode.SERVICE_UNAVAILABLE: 503,
    ErrorCode.UNAUTHORIZED: 401,
    ErrorCode.FORBIDDEN: 403,
    ErrorCode.CONFLICT: 409,
    ErrorCode.INTERNAL: 500,
}


class ErrorBody(BaseModel):
    code: ErrorCode
    message: str
    details: dict[str, Any] = Field(default_factory=dict)


class ErrorMeta(BaseModel):
    request_id: str


class ErrorResponse(BaseModel):
    error: ErrorBody
    meta: ErrorMeta


class ApiError(Exception):
    def __init__(
        self,
        code: ErrorCode,
        message: str,
        details: dict[str, Any] | None = None,
        headers: dict[str, str] | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.details = details or {}
        self.headers = headers


logger = logging.getLogger(__name__)

VALIDATION_MESSAGE = "입력한 내용을 확인해 주세요."
INTERNAL_MESSAGE = "일시적인 문제가 생겼어요. 잠시 후 다시 시도해 주세요."
_LOCATIONS = {"body", "query", "path", "header", "cookie"}


def _response(
    code: ErrorCode,
    message: str,
    details: dict[str, Any] | None = None,
    headers: dict[str, str] | None = None,
    request_id: str | None = None,
) -> JSONResponse:
    body = ErrorResponse(
        error=ErrorBody(code=code, message=message, details=details or {}),
        meta=ErrorMeta(request_id=request_id or new_request_id()),
    )
    return JSONResponse(
        status_code=HTTP_STATUS[code], content=body.model_dump(mode="json"), headers=headers
    )


async def _handle_api_error(request: Request, exc: Exception) -> JSONResponse:
    assert isinstance(exc, ApiError)
    return _response(exc.code, exc.message, exc.details, exc.headers)


def validation_fields(errors: Any) -> dict[str, str]:
    """Pydantic 오류 목록 → `{"필드 경로": "오류 종류"}`. 입력값(`input`)은 버린다."""
    fields: dict[str, str] = {}
    for error in errors:
        loc = [str(part) for part in error.get("loc", ())]
        if loc and loc[0] in _LOCATIONS:
            loc = loc[1:]
        fields.setdefault(".".join(loc) or "body", str(error.get("type", "invalid")))
    return fields


async def _handle_validation_error(request: Request, exc: Exception) -> JSONResponse:
    assert isinstance(exc, RequestValidationError)
    return _response(
        ErrorCode.VALIDATION_ERROR,
        VALIDATION_MESSAGE,
        {"fields": validation_fields(exc.errors())},
    )


class UnhandledErrorMiddleware:
    """처리되지 않은 예외 → 500 `INTERNAL`.

    Starlette의 `Exception` 처리기는 응답 뒤에 예외를 다시 던져 서버가 트레이스백(예외 메시지
    포함)을 로그에 남긴다. 예외 메시지에는 요청 값이 들어 있을 수 있어 여기서 삼키고 종류
    이름만 남긴다.
    """

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        started = False

        async def send_tracking(message: Message) -> None:
            nonlocal started
            if message["type"] == "http.response.start":
                started = True
            await send(message)

        try:
            await self.app(scope, receive, send_tracking)
        except Exception as exc:
            request_id = new_request_id()
            logger.error(
                "unhandled %s request_id=%s path=%s",
                type(exc).__name__,
                request_id,
                scope.get("path", ""),
            )
            if not started:
                response = _response(ErrorCode.INTERNAL, INTERNAL_MESSAGE, request_id=request_id)
                await response(scope, receive, send)


def register_error_handlers(app: FastAPI) -> None:
    app.add_exception_handler(ApiError, _handle_api_error)
    app.add_exception_handler(RequestValidationError, _handle_validation_error)
    app.add_middleware(UnhandledErrorMiddleware)
