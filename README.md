# 가게내비 (가칭)

> 사장님이 가장 큰 돈을 잃기 쉬운 세 번의 결정 — **자리를 계약할 때, 자금을 빌릴 때, 문을 닫을 때** — 를 공공데이터와 검증 가능한 규칙으로 돕는 웹 서비스.

| 모듈 | 질문 | 답하는 방식 |
|---|---|---|
| **자리 이력** (`location`) | "계약하려는 이 자리, 전에 어떤 가게들이 있었고 어떻게 됐나?" | 인허가 이력 + 비슷한 이력 자리들의 실제 3년 내 폐업률 |
| **정책자금** (`funding`) | "내 조건에서 어떤 정책자금을, 어떤 순서로 신청하면 필요한 돈을 가장 싸게 마련하나?" | 공고 원문 기반 규칙 엔진: 자격 3치 판정 → 조합·순서 최적화 → 원문 근거 |
| **폐업 지원** (`closure`) | "문 닫을 때 받을 수 있는 지원을 놓치지 않으려면 무엇을 언제 해야 하나?" | 같은 규칙 엔진 + 행정 타임라인 |

## 빠른 시작

```
cp .env.example .env                  # 값 채우기
make setup && make check              # uv, pnpm, Node 20+ 필요
docker compose up -d db && make dev   # API :8000, 웹 :3000
```

## 이 저장소에서 작업을 시작하는 법 (사람·AI 공통)

**Claude Code**: 이 폴더에서 `claude` 실행 → `/ticket T-001`. 규칙(`CLAUDE.md` → `AGENTS.md`, `.claude/rules/`)은 자동으로 읽힌다. 게이트 점검은 `/gate-review 1`.

1. [`AGENTS.md`](AGENTS.md) — 작업 규칙 (반드시 먼저)
2. [`docs/00-product.md`](docs/00-product.md) — 무엇을, 왜, 어디까지
3. [`docs/80-tasks.md`](docs/80-tasks.md) — 순서대로 처리할 작업 티켓과 수용 기준
4. 티켓이 가리키는 설계 문서

## 문서 지도

| 문서 | 내용 |
|---|---|
| [00-product](docs/00-product.md) | 목표, 사용자, 범위, 비목표, 성공 기준 |
| [01-architecture](docs/01-architecture.md) | 시스템 구성, 기술 스택, 저장소 구조 |
| [02-adr](docs/02-adr.md) | 설계 결정 기록 (ADR-001 ~) |
| [03-data-sources](docs/03-data-sources.md) | 외부 데이터·API, 수집 방식, 확인 필요 항목 |
| [04-data-model](docs/04-data-model.md) | DB 스키마 |
| [10-module-location](docs/10-module-location.md) | 자리 이력: 주소 정규화, 층·호 파싱, 이력, 통계 |
| [20-rule-engine](docs/20-rule-engine.md) | 공통 규칙 엔진: DSL, 3치 판정, 최적화, 타임라인, 설명 |
| [21-module-funding](docs/21-module-funding.md) | 정책자금 모듈 |
| [22-module-closure](docs/22-module-closure.md) | 폐업 지원 모듈 |
| [30-api](docs/30-api.md) | REST API 명세 |
| [40-frontend](docs/40-frontend.md) | 화면 구조, 화면별 명세, 문구 규칙 |
| [50-quality](docs/50-quality.md) | 테스트·평가·데이터 검증, 공개 게이트 |
| [60-legal-compliance](docs/60-legal-compliance.md) | 법적 가드레일 (금지 사항) |
| [70-roadmap](docs/70-roadmap.md) | 13주 일정, 단계별 게이트, 축소 규칙 |
| [80-tasks](docs/80-tasks.md) | 작업 티켓 |
| [90-glossary](docs/90-glossary.md) | 용어집 (코드 식별자 대응) |
| [analysis/](analysis/README.md) | W0 데이터 검증 결과와 재현 스크립트 |

## 상태

- 2026-10-08: W0 데이터 검증 완료 (서울 일반음식점 539,589건). 결과는 [`analysis/README.md`](analysis/README.md)
- 2026-10-12: 설계 v1.1 (독립 검토 반영, 13주 일정: 2026-10-19 ~ 2027-01-15)
- 2026-10-12: `T-001` 저장소 골격
- 2026-10-12: `T-002` Docker Compose · 헬스체크
- 다음: `T-003` 마이그레이션 0001
