---
paths:
  - "services/api/**"
---

<!-- .cursor/rules/10-backend.mdc 와 같은 내용. 수정 시 둘 다 고친다. -->

# 백엔드 규칙

- Python 3.12, `uv`로 의존성 관리. 새 의존성은 `docs/02-adr.md` 의존성 표에 기록.
- ruff(포맷·린트), mypy: `app/rules/**`, `app/location/**`는 strict.
- Pydantic v2 모델. 요청 모델은 `model_config = ConfigDict(extra="forbid")`.
- SQLAlchemy 2 async + asyncpg. 마이그레이션은 Alembic으로만, 스키마 정본은 `docs/04-data-model.md`.
- 모듈 경계(import-linter): `app.location` ↔ `app.rules` 서로 import 금지. 공유는 `app.common`만. `app.rules.engine`은 `sqlalchemy`·`fastapi`·`httpx`·`anthropic` import 금지(순수 함수).
- 기준일은 항상 인자(`as_of: date`)로 받는다. 엔진 안에서 `date.today()` 금지. API 계층에서만 `Asia/Seoul` 오늘을 기본값으로.
- 금액 `int`(원), 비율 `Decimal`, 면적 환산 `Fraction`(1평 = 400/121 ㎡).
- 응답 형식은 `docs/30-api.md` §1 공통 응답. 오류 코드는 표에 있는 것만.
- 로깅: 구조화 JSON. 요청 본문 로그 금지. `funding`/`closure` 라우터에 본문 로깅 미들웨어가 붙지 않았는지 테스트(`test_no_body_logging`).
- 배치 작업은 `jobs/` CLI(`python -m jobs.<name>`), 멱등(같은 입력 재실행 시 같은 결과), 실행 결과를 `data_snapshot`/리포트에 기록.
- 테스트 위치: `tests/{unit,property,scenario,golden,integration}`. 외부 API는 녹화 픽스처(`tests/fixtures/http/`). 예외: 카카오는 녹화하지 않고 공식 가이드 형식의 가상 픽스처("가상 예시" 표시)를 쓴다(AGENTS.md §3).
