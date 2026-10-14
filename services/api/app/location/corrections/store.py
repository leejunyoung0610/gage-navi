"""정정 요청 DB 처리 (docs/30 §2·§3, docs/04 §2, docs/60 §3·§5).

요청 본문(`message`)은 로그에 남기지 않는다. 연락처 같은 개인정보가 들어올 수 있다.
함수는 모두 호출한 쪽의 트랜잭션 안에서 실행한다.
"""

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import Literal

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from app.location.history.job import rebuild_parcel

Kind = Literal["wrong_info", "remove_request", "other"]
Status = Literal["open", "resolved", "rejected"]
Action = Literal["suppress_record", "none"]


class CreateProblem(StrEnum):
    """접수할 수 없는 이유 (`details.fields`의 값)."""

    NO_PARCEL = "no_parcel"
    NOT_IN_PLACE = "not_in_place"
    NOT_RECORD_FLOOR = "not_record_floor"


class ResolveProblem(StrEnum):
    NOT_FOUND = "not_found"
    NOT_OPEN = "not_open"
    NO_RECORD = "no_record"


@dataclass(frozen=True)
class Correction:
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


@dataclass(frozen=True)
class Resolved:
    id: int
    status: Status
    paths: list[str]  # 웹 재생성 대상. 숨기지 않았으면 빈 목록


# 이력에 보이는 기록 (docs/10 §7.1의 `H`)
_VISIBLE_RECORD = """
SELECT r.floor FROM license_record r
WHERE r.id = :record_id AND r.pnu = :pnu AND NOT r.no_fixed_place
  AND NOT EXISTS (SELECT 1 FROM record_suppression x WHERE x.record_id = r.id)
"""
_INSERT = """
INSERT INTO correction_request (pnu, floor, record_id, kind, message)
VALUES (:pnu, :floor, :record_id, :kind, :message) RETURNING id
"""
_COLUMNS = """
id, pnu, floor, record_id, kind, message, status, resolution_note, created_at, resolved_at,
revalidated_at
"""
# 처리 후 1년이 지난 요청의 메시지를 지운다. 행과 처리 결과는 처리 기록으로 남긴다
_PURGE = """
UPDATE correction_request SET message = ''
WHERE resolved_at IS NOT NULL AND message <> ''
  AND resolved_at <= CAST(:now AS timestamptz) - interval '1 year'
"""
# `resolved`는 숨김 처리한 요청뿐이다 (`none` → `rejected`)
_PENDING_REVALIDATION = """
SELECT c.id, r.pnu, r.floor FROM correction_request c
JOIN license_record r ON r.id = c.record_id
WHERE c.status = 'resolved' AND c.revalidated_at IS NULL AND r.pnu IS NOT NULL
ORDER BY c.id
"""


def place_paths(pnu: str, floor: str | None) -> list[str]:
    """웹 재생성 대상 경로: 필지 페이지와 (층이 있으면) 층 페이지 (docs/30 §3)."""
    paths = [f"/place/{pnu}"]
    if floor is not None:
        paths.append(f"/place/{pnu}/{floor}")
    return paths


async def create(
    conn: AsyncConnection,
    pnu: str,
    floor: str | None,
    record_id: int | None,
    kind: Kind,
    message: str,
) -> int | CreateProblem:
    if (
        await conn.execute(text("SELECT 1 FROM parcel WHERE pnu = :pnu"), {"pnu": pnu})
    ).first() is None:
        return CreateProblem.NO_PARCEL
    if record_id is not None:
        row = (
            await conn.execute(text(_VISIBLE_RECORD), {"record_id": record_id, "pnu": pnu})
        ).first()
        if row is None:
            return CreateProblem.NOT_IN_PLACE
        if floor is not None and row[0] != floor:
            return CreateProblem.NOT_RECORD_FLOOR
    params = {
        "pnu": pnu,
        "floor": floor,
        "record_id": record_id,
        "kind": kind,
        "message": message,
    }
    return int((await conn.execute(text(_INSERT), params)).scalar_one())


async def purge_messages(conn: AsyncConnection, now: datetime) -> int:
    """처리 후 1년이 지난 요청의 `message`를 빈 문자열로. 지운 건수."""
    return int((await conn.execute(text(_PURGE), {"now": now})).rowcount)


async def list_requests(
    conn: AsyncConnection, status: Status | None, limit: int
) -> list[Correction]:
    where = "" if status is None else "WHERE status = :status"
    rows = await conn.execute(
        text(f"SELECT {_COLUMNS} FROM correction_request {where} ORDER BY id DESC LIMIT :limit"),
        {"status": status, "limit": limit},
    )
    return [Correction(*row) for row in rows]


async def resolve(
    conn: AsyncConnection, request_id: int, action: Action, note: str | None, now: datetime
) -> Resolved | ResolveProblem:
    """요청을 처리한다. 숨기면 같은 트랜잭션에서 그 필지의 요약을 다시 만든다(docs/10 §7.1)."""
    row = (
        await conn.execute(
            text(
                "SELECT status, record_id, kind FROM correction_request WHERE id = :id FOR UPDATE"
            ),
            {"id": request_id},
        )
    ).first()
    if row is None:
        return ResolveProblem.NOT_FOUND
    status, record_id, kind = row
    if status != "open":
        return ResolveProblem.NOT_OPEN
    paths: list[str] = []
    new_status: Status = "rejected"
    if action == "suppress_record":
        if record_id is None:
            return ResolveProblem.NO_RECORD
        pnu, floor = (
            await conn.execute(
                text("SELECT pnu, floor FROM license_record WHERE id = :id"), {"id": record_id}
            )
        ).one()
        # 이미 다른 요청으로 숨긴 기록이면 숨김은 그대로 두고 이 요청만 처리한다
        await conn.execute(
            text(
                "INSERT INTO record_suppression (record_id, reason, request_id) "
                "VALUES (:record_id, :reason, :request_id) ON CONFLICT (record_id) DO NOTHING"
            ),
            {"record_id": record_id, "reason": kind, "request_id": request_id},
        )
        if pnu is not None:
            await rebuild_parcel(conn, str(pnu))
            paths = place_paths(str(pnu), floor)
        new_status = "resolved"
    await conn.execute(
        text(
            "UPDATE correction_request SET status = :status, resolution_note = :note, "
            "resolved_at = :now WHERE id = :id"
        ),
        {"status": new_status, "note": note, "now": now, "id": request_id},
    )
    return Resolved(id=request_id, status=new_status, paths=paths)


async def pending_revalidations(conn: AsyncConnection) -> list[tuple[int, list[str]]]:
    """숨김 처리했지만 웹 재생성이 아직 성공하지 않은 요청과 대상 경로."""
    rows = await conn.execute(text(_PENDING_REVALIDATION))
    return [(int(rid), place_paths(str(pnu), floor)) for rid, pnu, floor in rows]


async def mark_revalidated(conn: AsyncConnection, request_id: int, now: datetime) -> None:
    await conn.execute(
        text("UPDATE correction_request SET revalidated_at = :now WHERE id = :id"),
        {"now": now, "id": request_id},
    )
