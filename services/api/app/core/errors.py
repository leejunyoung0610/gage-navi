"""공통 오류 응답 (docs/30 §1). 오류 코드는 문서의 표에 있는 것만 쓴다."""

from enum import StrEnum
from typing import Any

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

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


async def _handle_api_error(request: Request, exc: Exception) -> JSONResponse:
    assert isinstance(exc, ApiError)
    body = ErrorResponse(
        error=ErrorBody(code=exc.code, message=exc.message, details=exc.details),
        meta=ErrorMeta(request_id=new_request_id()),
    )
    return JSONResponse(
        status_code=HTTP_STATUS[exc.code],
        content=body.model_dump(mode="json"),
        headers=exc.headers,
    )


def register_error_handlers(app: FastAPI) -> None:
    app.add_exception_handler(ApiError, _handle_api_error)
