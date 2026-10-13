"""도로명주소 검색 API의 실제 응답을 테스트 픽스처로 녹화한다 (T-021).

    cd services/api && uv run --env-file ../../.env python -m jobs.record_juso_fixtures

- 승인키는 환경 변수 `JUSO_CONFM_KEY`에서만 읽고, 출력하지 않는다
- 픽스처에는 검색어·페이지와 응답 본문만 쓴다. 요청 본문(승인키 포함)은 쓰지 않는다
- 쓰기 전에 응답에서 승인키 문자열을 지우고(`scrub`), 쓴 뒤에 파일을 다시 읽어 키가 없는지 확인한다
- 같은 이름의 픽스처가 있으면 덮어쓴다(`--only 이름…`으로 일부만 녹화할 수 있다)
- 녹화일은 인자로 받는다(시계를 직접 읽지 않는다)
"""

import argparse
import asyncio
import json
import os
import sys
from pathlib import Path
from typing import Any

import httpx2

from app.address.juso import COUNT_PER_PAGE, JUSO_SEARCH_URL, JusoClient, JusoError

FIXTURE_DIR = Path(__file__).resolve().parents[1] / "tests" / "fixtures" / "http" / "juso"
REDACTED = "<REDACTED>"
PAUSE_SECONDS = 1.0  # 호출 사이 간격. 공식 문서에 호출 한도가 없어 넉넉히 둔다

# (파일 이름, 검색어, 페이지). 주소는 공개된 건물 주소이고 사용자 입력이 아니다.
# 이름이 `_add_info`로 끝나면 추가 항목(`addInfoYn=Y`, 관련지번)을 함께 받는다.
ADD_INFO_SUFFIX = "_add_info"
CASES: list[tuple[str, str, int]] = [
    ("guide_sample", "서울특별시 마포구 성암로 301", 1),  # 공식 가이드의 예시 주소
    ("single_parcel", "서울특별시 광진구 능동로 120", 1),
    ("mountain_lot", "서울특별시 관악구 관악로 1", 1),  # 산 번지
    ("many_results_p1", "능동로", 1),
    ("many_results_p2", "능동로", 2),
    ("no_result", "가나다라마바사 99999", 1),
    ("keyword_too_broad", "서울특별시", 1),  # 시도명만 — 오류코드 응답
    ("single_parcel_add_info", "서울특별시 광진구 능동로 120", 1),  # T-021b: 관련지번 형식
    ("mountain_lot_add_info", "서울특별시 관악구 관악로 1", 1),
]


def scrub(text: str, secret: str) -> str:
    """`text`에서 승인키 문자열을 지운다."""
    return text.replace(secret, REDACTED) if secret else text


def fixture_text(keyword: str, page: int, recorded_on: str, payload: Any, secret: str) -> str:
    document = {
        "source": JUSO_SEARCH_URL,
        "recorded_on": recorded_on,
        "request": {"keyword": keyword, "currentPage": page, "countPerPage": COUNT_PER_PAGE},
        "response": payload,
    }
    return scrub(json.dumps(document, ensure_ascii=False, indent=2) + "\n", secret)


async def record(
    secret: str, recorded_on: str, out_dir: Path, only: frozenset[str] | None = None
) -> int:
    out_dir.mkdir(parents=True, exist_ok=True)
    failures = 0
    async with httpx2.AsyncClient() as http:
        client = JusoClient(secret, http)
        for name, keyword, page in CASES:
            if only is not None and name not in only:
                continue
            try:
                payload = await client.fetch(keyword, page, add_info=name.endswith(ADD_INFO_SUFFIX))
            except JusoError as exc:
                failures += 1
                print(f"{name}: 실패 ({exc})")
                continue
            path = out_dir / f"{name}.json"
            path.write_text(
                fixture_text(keyword, page, recorded_on, payload, secret), encoding="utf-8"
            )
            if secret in path.read_text(encoding="utf-8"):
                path.unlink()
                raise SystemExit(f"{name}: 픽스처에 승인키가 남아 파일을 지웠습니다")
            print(f"{name}: 저장 ({path.name})")
            await asyncio.sleep(PAUSE_SECONDS)
    return failures


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--recorded-on", required=True, help="녹화일 YYYY-MM-DD")
    parser.add_argument("--out-dir", type=Path, default=FIXTURE_DIR)
    parser.add_argument("--only", nargs="*", help="이 이름의 픽스처만 다시 녹화한다")
    args = parser.parse_args()
    secret = os.environ.get("JUSO_CONFM_KEY", "")
    if not secret:
        print("JUSO_CONFM_KEY가 없습니다. .env에 넣은 뒤 --env-file로 실행하세요.")
        return 2
    only = frozenset(args.only) if args.only else None
    return 1 if asyncio.run(record(secret, args.recorded_on, args.out_dir, only)) else 0


if __name__ == "__main__":
    sys.exit(main())
