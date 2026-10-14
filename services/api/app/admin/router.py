"""관리자 API `/admin/v1` — 로그인·로그아웃, 정정 요청 처리 (docs/30 §3).

정정 요청 본문(`message`)은 로그에 남기지 않는다.
"""

import logging
from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, Query, Request, Response
from pydantic import BaseModel, ConfigDict, Field, ValidationInfo, field_validator
from pydantic_core import PydanticCustomError

from app.admin import auth, revalidate
from app.admin.auth import Admin, LoginLocked, LoginOk
from app.core import db
from app.core.errors import ApiError, ErrorCode, ErrorResponse
from app.core.request_id import current_request_id
from app.location.corrections import store
from app.location.corrections.store import Action, ResolveProblem, Status

logger = logging.getLogger(__name__)

router = APIRouter(tags=["admin"], dependencies=[Depends(auth.check_csrf_header)])

NOTE_MAX = 1000
NOT_FOUND_MESSAGE = "정정 요청을 찾을 수 없어요."
NOT_OPEN_MESSAGE = "이미 처리한 정정 요청이에요."
NO_RECORD_MESSAGE = "숨길 기록이 지정되지 않은 요청이에요."
ERROR_RESPONSES: dict[int | str, dict[str, object]] = {
    code: {"model": ErrorResponse} for code in (401, 403, 404, 409, 422, 429)
}


class Meta(BaseModel):
    request_id: str


def _meta() -> Meta:
    return Meta(request_id=current_request_id())


class LoginIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    username: Annotated[str, Field(min_length=1, max_length=100)]
    password: Annotated[str, Field(min_length=1, max_length=1000)]


class LoginData(BaseModel):
    username: str
    expires_at: datetime


class LoginResponse(BaseModel):
    data: LoginData
    meta: Meta


class CorrectionItem(BaseModel):
    id: int
    pnu: str
    floor: str | None
    record_id: int | None
    kind: str
    message: str
    status: str
    resolution_note: str | None
    created_at: datetime
    resolved_at: datetime | None
    revalidated_at: datetime | None


class CorrectionList(BaseModel):
    data: list[CorrectionItem]
    meta: Meta


class ResolveIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    action: Action
    note: Annotated[str, Field(max_length=NOTE_MAX)] | None = Field(
        default=None, validate_default=True
    )

    @field_validator("note")
    @classmethod
    def _note_required_for_reject(cls, note: str | None, info: ValidationInfo) -> str | None:
        """`none`(→ `rejected`)은 거절 사유가 있어야 한다. 비었거나 공백뿐이면 422."""
        if info.data.get("action") == "none" and not (note or "").strip():
            raise PydanticCustomError("note_required", "거절 사유를 적어 주세요.")
        return note


class ResolveData(BaseModel):
    id: int
    status: Status
    revalidated: bool


class ResolveResponse(BaseModel):
    data: ResolveData
    meta: Meta


def _no_store(response: Response) -> None:
    response.headers["Cache-Control"] = "no-store"


@router.post("/login", responses=ERROR_RESPONSES)
async def login(body: LoginIn, response: Response) -> LoginResponse:
    async with db.get_engine().begin() as conn:
        # 실패 횟수·잠금도 커밋해야 하므로 오류는 트랜잭션이 끝난 뒤에 낸다
        result = await auth.login(conn, body.username, body.password)
    if isinstance(result, LoginLocked):
        raise ApiError(
            ErrorCode.RATE_LIMITED,
            auth.LOCKED_MESSAGE,
            headers={"Retry-After": str(result.retry_after_seconds)},
        )
    if not isinstance(result, LoginOk):
        raise ApiError(ErrorCode.UNAUTHORIZED, auth.LOGIN_FAILED_MESSAGE)
    response.set_cookie(
        auth.SESSION_COOKIE,
        result.token,
        max_age=int(auth.SESSION_ABSOLUTE.total_seconds()),
        path=auth.COOKIE_PATH,
        secure=True,
        httponly=True,
        samesite="strict",
    )
    _no_store(response)
    return LoginResponse(
        data=LoginData(username=result.admin.username, expires_at=result.expires_at),
        meta=_meta(),
    )


@router.post("/logout", status_code=204, responses=ERROR_RESPONSES)
async def logout(request: Request) -> Response:
    token = request.cookies.get(auth.SESSION_COOKIE)
    if token:
        async with db.get_engine().begin() as conn:
            await auth.logout(conn, token)
    response = Response(status_code=204)
    response.delete_cookie(
        auth.SESSION_COOKIE,
        path=auth.COOKIE_PATH,
        secure=True,
        httponly=True,
        samesite="strict",
    )
    return response


@router.get("/corrections", responses=ERROR_RESPONSES)
async def list_corrections(
    response: Response,
    _admin: Annotated[Admin, Depends(auth.require_admin)],
    status: Status | None = None,
    limit: Annotated[int, Query(ge=1, le=500)] = 100,
) -> CorrectionList:
    async with db.get_engine().begin() as conn:
        # 처리 후 1년이 지난 메시지는 보여주기 전에 지운다 (docs/60 §5)
        await store.purge_messages(conn, auth.now())
        items = await store.list_requests(conn, status, limit)
    _no_store(response)
    return CorrectionList(data=[CorrectionItem(**item.__dict__) for item in items], meta=_meta())


@router.post("/corrections/{correction_id}/resolve", responses=ERROR_RESPONSES)
async def resolve_correction(
    correction_id: int,
    body: ResolveIn,
    response: Response,
    _admin: Annotated[Admin, Depends(auth.require_admin)],
) -> ResolveResponse:
    async with db.get_engine().begin() as conn:
        result = await store.resolve(conn, correction_id, body.action, body.note, auth.now())
        if result is ResolveProblem.NOT_FOUND:
            raise ApiError(ErrorCode.NOT_FOUND, NOT_FOUND_MESSAGE)
        if result is ResolveProblem.NOT_OPEN:
            raise ApiError(ErrorCode.CONFLICT, NOT_OPEN_MESSAGE)
        if result is ResolveProblem.NO_RECORD:
            raise ApiError(
                ErrorCode.VALIDATION_ERROR, NO_RECORD_MESSAGE, {"fields": {"action": "no_record"}}
            )
    assert isinstance(result, store.Resolved)
    # 웹 재생성은 커밋 뒤에 부른다. 실패해도 숨김은 그대로 두고 `revalidated_at`을 비워 둔다
    revalidated = False
    if result.paths:
        revalidated = await revalidate.revalidate(result.paths, result.id)
        if revalidated:
            async with db.get_engine().begin() as conn:
                await store.mark_revalidated(conn, result.id, auth.now())
    _no_store(response)
    return ResolveResponse(
        data=ResolveData(id=result.id, status=result.status, revalidated=revalidated),
        meta=_meta(),
    )
