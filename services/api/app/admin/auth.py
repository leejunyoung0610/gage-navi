"""관리자 인증 (docs/30 §3, docs/01 §6, docs/04 §3 `admin_user`·`admin_session`).

- 비밀번호: argon2id 해시만 저장
- 세션: 쿠키에는 무작위 32바이트 토큰, DB에는 그 SHA-256 해시만. 로그인 후 8시간 또는 마지막
  요청 후 30분이 지나면 만료. 로그아웃·비밀번호 변경 시 서버에서 지운다
- 잠금: 첫 실패부터 10분 안에 5번 틀리면 15분. 재시작·여러 워커에서도 유지되도록 DB에 둔다
- CSRF: 상태를 바꾸는 요청은 `X-Admin-Request: 1` 헤더가 있어야 한다
"""

import hashlib
import math
import secrets
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError
from fastapi import Request
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from app.core import db
from app.core.errors import ApiError, ErrorCode

SESSION_COOKIE = "gn_admin_session"
COOKIE_PATH = "/admin/v1"
SESSION_ABSOLUTE = timedelta(hours=8)
SESSION_IDLE = timedelta(minutes=30)
MAX_FAILURES = 5
FAILURE_WINDOW = timedelta(minutes=10)
LOCK_DURATION = timedelta(minutes=15)
CSRF_HEADER = "X-Admin-Request"
_SAFE_METHODS = {"GET", "HEAD", "OPTIONS"}

UNAUTHORIZED_MESSAGE = "로그인이 필요해요."
LOGIN_FAILED_MESSAGE = "사용자 이름이나 비밀번호가 맞지 않아요."
LOCKED_MESSAGE = "로그인 시도가 너무 많아요. 잠시 후 다시 시도해 주세요."
CSRF_MESSAGE = "허용되지 않은 요청이에요."

_hasher = PasswordHasher()
# 없는 사용자명도 같은 시간이 걸리게 대신 검증하는 해시 (값은 의미 없다)
_DUMMY_HASH = _hasher.hash(secrets.token_hex(16))


def now() -> datetime:
    """현재 시각 (UTC). 테스트에서 바꾼다."""
    return datetime.now(UTC)


def hash_password(password: str) -> str:
    return _hasher.hash(password)


def _verify(password_hash: str, password: str) -> bool:
    try:
        return _hasher.verify(password_hash, password)
    except (VerificationError, InvalidHashError):
        return False


def token_hash(token: str) -> bytes:
    return hashlib.sha256(token.encode()).digest()


@dataclass(frozen=True)
class FailureState:
    count: int
    started_at: datetime | None
    locked_until: datetime | None


def register_failure(count: int, started_at: datetime | None, at: datetime) -> FailureState:
    """실패 한 번을 센다. 첫 실패부터 10분이 지났으면 새로 센다. 5번째면 15분 잠근다."""
    if started_at is None or at - started_at >= FAILURE_WINDOW:
        count, started_at = 0, at
    count += 1
    if count >= MAX_FAILURES:
        return FailureState(0, None, at + LOCK_DURATION)
    return FailureState(count, started_at, None)


@dataclass(frozen=True)
class Admin:
    id: int
    username: str


@dataclass(frozen=True)
class LoginOk:
    admin: Admin
    token: str
    expires_at: datetime


@dataclass(frozen=True)
class LoginFailed:
    pass


@dataclass(frozen=True)
class LoginLocked:
    retry_after_seconds: int


_USER = """
SELECT id, password_hash, failed_login_count, failed_login_started_at, locked_until
FROM admin_user WHERE username = :username FOR UPDATE
"""
_EXPIRED = "DELETE FROM admin_session WHERE expires_at <= :now OR last_seen_at <= :idle_cutoff"


async def login(
    conn: AsyncConnection, username: str, password: str
) -> LoginOk | LoginFailed | LoginLocked:
    """로그인 시도. 실패 횟수·잠금을 갱신한다(호출한 쪽이 커밋한다)."""
    at = now()
    row = (await conn.execute(text(_USER), {"username": username})).first()
    if row is None:
        _verify(_DUMMY_HASH, password)
        return LoginFailed()
    user_id, password_hash, count, started_at, locked_until = row
    if locked_until is not None and locked_until > at:
        return LoginLocked(max(1, math.ceil((locked_until - at).total_seconds())))
    if not _verify(password_hash, password):
        state = register_failure(count, started_at, at)
        await conn.execute(
            text(
                "UPDATE admin_user SET failed_login_count = :count, "
                "failed_login_started_at = :started, locked_until = :locked WHERE id = :id"
            ),
            {
                "count": state.count,
                "started": state.started_at,
                "locked": state.locked_until,
                "id": user_id,
            },
        )
        return LoginFailed()
    new_hash = hash_password(password) if _hasher.check_needs_rehash(password_hash) else None
    await conn.execute(
        text(
            "UPDATE admin_user SET failed_login_count = 0, failed_login_started_at = NULL, "
            "locked_until = NULL, password_hash = coalesce(:new_hash, password_hash) "
            "WHERE id = :id"
        ),
        {"new_hash": new_hash, "id": user_id},
    )
    await conn.execute(text(_EXPIRED), {"now": at, "idle_cutoff": at - SESSION_IDLE})
    token = secrets.token_urlsafe(32)
    expires_at = at + SESSION_ABSOLUTE
    await conn.execute(
        text(
            "INSERT INTO admin_session (token_hash, admin_user_id, created_at, last_seen_at, "
            "expires_at) VALUES (:hash, :user_id, :at, :at, :expires_at)"
        ),
        {"hash": token_hash(token), "user_id": user_id, "at": at, "expires_at": expires_at},
    )
    return LoginOk(Admin(int(user_id), username), token, expires_at)


async def logout(conn: AsyncConnection, token: str) -> None:
    await conn.execute(
        text("DELETE FROM admin_session WHERE token_hash = :hash"), {"hash": token_hash(token)}
    )


async def session_admin(conn: AsyncConnection, token: str) -> Admin | None:
    """유효한 세션의 관리자. 만료된 세션은 지우고 `None`. 유효하면 마지막 요청 시각을 갱신한다."""
    at = now()
    hashed = token_hash(token)
    row = (
        await conn.execute(
            text(
                "SELECT u.id, u.username, s.expires_at, s.last_seen_at FROM admin_session s "
                "JOIN admin_user u ON u.id = s.admin_user_id WHERE s.token_hash = :hash"
            ),
            {"hash": hashed},
        )
    ).first()
    if row is None:
        return None
    user_id, username, expires_at, last_seen_at = row
    if expires_at <= at or last_seen_at + SESSION_IDLE <= at:
        await conn.execute(
            text("DELETE FROM admin_session WHERE token_hash = :hash"), {"hash": hashed}
        )
        return None
    await conn.execute(
        text("UPDATE admin_session SET last_seen_at = :at WHERE token_hash = :hash"),
        {"at": at, "hash": hashed},
    )
    return Admin(int(user_id), str(username))


@dataclass(frozen=True)
class PasswordSet:
    created: bool
    sessions_deleted: int


async def set_password(conn: AsyncConnection, username: str, password: str) -> PasswordSet:
    """계정이 없으면 만들고, 있으면 비밀번호를 바꾸고 잠금을 풀고 그 관리자의 세션을 전부 지운다."""
    hashed = hash_password(password)
    row = (
        await conn.execute(
            text("SELECT id FROM admin_user WHERE username = :username FOR UPDATE"),
            {"username": username},
        )
    ).first()
    if row is None:
        await conn.execute(
            text("INSERT INTO admin_user (username, password_hash) VALUES (:username, :hash)"),
            {"username": username, "hash": hashed},
        )
        return PasswordSet(created=True, sessions_deleted=0)
    await conn.execute(
        text(
            "UPDATE admin_user SET password_hash = :hash, failed_login_count = 0, "
            "failed_login_started_at = NULL, locked_until = NULL WHERE id = :id"
        ),
        {"hash": hashed, "id": row[0]},
    )
    deleted = await conn.execute(
        text("DELETE FROM admin_session WHERE admin_user_id = :id"), {"id": row[0]}
    )
    return PasswordSet(created=False, sessions_deleted=int(deleted.rowcount))


def check_csrf_header(request: Request) -> None:
    """상태를 바꾸는 관리자 요청은 `X-Admin-Request: 1`이 있어야 한다 (없으면 403)."""
    if request.method not in _SAFE_METHODS and request.headers.get(CSRF_HEADER) != "1":
        raise ApiError(ErrorCode.FORBIDDEN, CSRF_MESSAGE)


async def require_admin(request: Request) -> Admin:
    """세션 쿠키가 유효한 관리자. 없거나 만료되면 401."""
    token = request.cookies.get(SESSION_COOKIE)
    if not token:
        raise ApiError(ErrorCode.UNAUTHORIZED, UNAUTHORIZED_MESSAGE)
    async with db.get_engine().begin() as conn:
        admin = await session_admin(conn, token)
    if admin is None:
        raise ApiError(ErrorCode.UNAUTHORIZED, UNAUTHORIZED_MESSAGE)
    return admin
