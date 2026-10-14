"""관리자 계정 만들기·비밀번호 바꾸기 (docs/30 §3, T-023). 사람이 터미널에서 직접 실행한다.

    python -m jobs.set_admin_password <사용자명>

비밀번호는 화면에 보이지 않는 입력으로 두 번 받는다. 출력·로그·파일에 남기지 않고, DB에는
argon2id 해시만 저장한다. 계정이 있으면 비밀번호를 바꾸고 잠금을 풀고 그 관리자의 세션을 전부
지운다.
"""

import argparse
import asyncio
import getpass
import sys
from collections.abc import Callable

from app.admin.auth import PasswordSet, set_password
from app.core.db import get_engine

MIN_LENGTH = 12


async def run(username: str, password: str) -> PasswordSet:
    engine = get_engine()
    try:
        async with engine.begin() as conn:
            return await set_password(conn, username, password)
    finally:
        await engine.dispose()


def main(argv: list[str] | None = None, prompt: Callable[[str], str] = getpass.getpass) -> int:
    parser = argparse.ArgumentParser(
        prog="jobs.set_admin_password", description="관리자 계정 만들기·비밀번호 바꾸기"
    )
    parser.add_argument("username", help="관리자 사용자명")
    args = parser.parse_args(argv)
    username = args.username.strip()
    if not username:
        print("사용자명이 비어 있어요.", file=sys.stderr)
        return 2
    password = prompt("새 비밀번호: ")
    if len(password) < MIN_LENGTH:
        print(f"비밀번호는 {MIN_LENGTH}자 이상이어야 해요.", file=sys.stderr)
        return 2
    if prompt("한 번 더: ") != password:
        print("두 비밀번호가 달라요. 바꾸지 않았어요.", file=sys.stderr)
        return 2
    result = asyncio.run(run(username, password))
    if result.created:
        print(f"관리자 계정 {username}을(를) 만들었어요.")
    else:
        print(
            f"관리자 {username}의 비밀번호를 바꿨어요. 세션 {result.sessions_deleted}개를 지웠어요."
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
