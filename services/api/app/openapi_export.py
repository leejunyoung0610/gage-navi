"""OpenAPI 스키마를 표준 출력에 JSON으로 쓴다 (T-031, docs/30 머리말).

`apps/web`의 `pnpm gen:api`가 이 출력을 받아 `lib/api/types.ts`를 만든다.
앱을 import만 하므로 DB·환경 변수 없이 동작한다. 로그는 표준 오류로 가서 JSON과 섞이지 않는다.
"""

import json
import sys
from typing import Any


def openapi_schema() -> dict[str, Any]:
    from app.main import app

    return app.openapi()


def main() -> None:
    # 한글 설명을 그대로 두고, 끝에 줄바꿈을 붙여 출력이 실행마다 같게 한다
    sys.stdout.write(json.dumps(openapi_schema(), ensure_ascii=False, indent=2) + "\n")


if __name__ == "__main__":
    main()
