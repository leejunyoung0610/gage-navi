# 01. 아키텍처

## 1. 시스템 구성

```
                ┌──────────────────────── 오프라인 배치 (jobs/) ────────────────────────┐
                │                                                                        │
 공공데이터포털 ─┼─▶ [L1 인허가 수집] ─▶ [L2 정규화: PNU·층·호·좌표] ─▶ [L3 층 이력 빌드]  │
 (인허가 식품3종)│        raw 적재           license_record     floor_summary 등  │
                │                                                         │              │
 법정동코드 ─────┼──────────────────────────────▶ (조인)                    ▼              │
                │                                              [L4 기준율 통계]           │
                │                                               base_rate·model_card     │
                │                                                                        │
 기업마당 API ───┼─▶ [R1 공고 수집·변경 감지] ─▶ [R2 HWP/PDF 변환] ─▶ [R3 LLM 추출]        │
 기관 공고 페이지│        announcement            document             extraction_item     │
                │                                                         │              │
                └─────────────────────────────────────────────────────────┼──────────────┘
                                                                          ▼
                                                        [R4 검수 대기열] ◀── 관리자 화면 (사람)
                                                                          │ 승인
                                                                          ▼
                                                                [R5 규칙 저장소 · 버전]
                                                                          │
┌────────────── 온라인 (services/api, FastAPI) ───────────────────────────┼─────────────┐
│                                                                         ▼             │
│  /places/*  ─▶ location 조회 (floor_summary, base_rate)        rules.engine (결정론적) │
│  /funding/evaluate ─▶ funding 어댑터 ─▶ 3치 판정 ▶ 접수상태 ▶ 금액 ▶ 최적화 ▶ 타임라인 ▶ 설명
│  /closure/evaluate ─▶ closure 어댑터 ─┘                                               │
│  /address/search   ─▶ 도로명주소 API 프록시 (캐시)                                     │
└──────────────────────────────────────────────▲────────────────────────────────────────┘
                                               │ JSON (OpenAPI)
┌──────────────── 웹 (apps/web, Next.js) ──────┴───────────────────────────────────────┐
│  자리 페이지(서버 렌더링·ISR, 검색 색인)  ·  정책자금/폐업 마법사(클라이언트)            │
│  사업장 프로필 = 브라우저 저장소(localStorage), 서버에 저장하지 않음                     │
└──────────────────────────────────────────────────────────────────────────────────────┘
```

**경계 원칙**
- `location`과 `rules`는 서로 import하지 않는다. 공유는 `common`(기준일, 금액·단위 타입, 지역 코드)만.
- `funding`, `closure`는 `rules.engine`을 사용하는 **얇은 어댑터**다. 판단 로직을 어댑터에 쓰지 않는다.
- LLM 호출은 `rules/extraction` 패키지 안에서만 허용한다. 다른 패키지에서 LLM SDK import 시 CI 실패(import-linter).

## 2. 기술 스택

| 영역 | 선택 | 버전 기준 | 이유 |
|---|---|---|---|
| 백엔드 | Python, FastAPI, Pydantic v2, SQLAlchemy 2 (async), Alembic | Python 3.12 | 데이터·통계·규칙 엔진이 모두 Python. 기존 경험 재사용 |
| 패키지 관리 | uv | 최신 안정 | 빠른 잠금·재현 |
| 데이터 처리 | pandas, numpy, pyproj, statsmodels | — | W0 분석 코드 이식 |
| 최적화 | 자체 DFS(분기 한정) / 확장 시 OR-Tools CP-SAT | — | MVP 후보 수가 작음 (docs/20 §7) |
| 문서 변환 | HWP: olefile로 레코드 직접 파싱, PDF: pdfplumber(표는 셀 단위), HWPX: 판정 보류(수동 텍스트) | — | T-051S 스파이크로 확정 (ADR-024) |
| LLM | Anthropic Claude API, tool use로 JSON 스키마 강제 | — | 추출 전용 |
| DB | PostgreSQL + PostGIS | 16 / 3.4 | jsonb(규칙·근거), 공간 조회 |
| 프론트 | Next.js(App Router), React, TypeScript strict | 15 / 19 | 자리 페이지 서버 렌더링·검색 색인 |
| UI | Tailwind CSS, shadcn/ui(Radix) | — | 접근성 기본 제공 |
| 폼·검증 | react-hook-form, zod | — | 프로필 스키마 클라이언트 검증 |
| 서버 상태 | TanStack Query | v5 | 평가 요청 캐시·재시도 |
| API 타입 | openapi-typescript (백엔드 OpenAPI → TS 타입 생성) | — | 계약 불일치 방지 |
| PWA | Next.js `app/manifest.ts` + Serwist | — | 홈 화면 설치, 오프라인 셸 |
| 지도 | Kakao Maps JavaScript SDK | — | 국내 주소·지도 품질 |
| 테스트 | pytest, Hypothesis, mutmut / Vitest, Playwright | — | docs/50 |
| 린트·타입 | ruff, mypy(strict: `rules`, `location`) / ESLint, Prettier, tsc | — | |
| 관측 | 구조화 로그(JSON, 본문 마스킹), Sentry | — | |
| 배포 | 웹: Vercel / API·DB: 단일 VM + Docker Compose + Caddy(HTTPS) | — | 포트폴리오 비용 최소 |
| CI | GitHub Actions | — | lint·type·test·e2e |

새 의존성 추가 시 `docs/02-adr.md`에 한 줄 기록 (이름, 이유, 대안).

## 3. 저장소 구조

```
gage-navi/
├── AGENTS.md                      # AI·사람 공통 작업 규칙 (최우선)
├── README.md
├── .cursor/rules/*.mdc            # Cursor 규칙 (AGENTS.md 요약 + 영역별)
├── docs/                          # 설계 문서 (이 폴더)
├── analysis/                      # W0 검증 스크립트·결과 (참고용, 서비스 코드 아님)
├── eval/labels/{dev,test}/        # 규칙 추출 정답 라벨 JSON (커밋 대상)
├── docker-compose.yml
├── .env.example
├── Makefile                       # make setup | check | test | dev | e2e | gen-api
├── services/api/
│   ├── pyproject.toml
│   ├── alembic/
│   ├── app/
│   │   ├── main.py                # FastAPI 앱, 라우터 등록, 예외 핸들러
│   │   ├── core/                  # config, db 세션, logging(마스킹), security(관리자 인증), ratelimit
│   │   ├── common/                # AsOf, Money(KRW int), Area(value, unit, basis), RegionCode
│   │   ├── address/               # 도로명주소 API 클라이언트·캐시, PNU 생성
│   │   ├── location/
│   │   │   ├── ingest/            # 인허가 파일/API 로더, raw 적재
│   │   │   ├── normalize/         # floor_parser.py, ho_parser.py, coords.py, bulk_closure.py, stale.py, records.py(행 정규화)·validation.py(DV)·job.py(DB 반영). PNU 생성은 address/pnu.py
│   │   │   ├── history/           # parcel·floor_summary·record_prior 빌드
│   │   │   ├── stats/             # base_rate.py (Wilson CI), model_card.py
│   │   │   ├── matching/          # (게이트 전 비공개) 호실 연결 연구
│   │   │   ├── repo.py, schemas.py, api.py
│   │   ├── rules/
│   │   │   ├── dsl/               # Pydantic 규칙 모델, JSON Schema 내보내기
│   │   │   ├── engine/            # tri_logic, availability, amount, constraints, optimizer, timeline, explainer
│   │   │   ├── extraction/        # collector, converter, extractor(LLM), validators
│   │   │   ├── review/            # 검수 API
│   │   │   ├── store.py           # 규칙 버전 관리
│   │   │   └── eval/              # 정답셋, 정규화, 지표, 부트스트랩
│   │   ├── funding/               # 프로필→엔진 입력 어댑터, 목적함수 설정, api.py
│   │   ├── closure/               # 어댑터, 법정 기한 레지스트리, api.py
│   │   └── admin/                 # 관리자 라우터 모음
│   ├── jobs/                      # CLI: ingest_licenses, normalize_licenses, build_history, compute_base_rates, collect_announcements …
│   └── tests/{unit,property,scenario,golden,integration}/
├── apps/web/
│   ├── app/
│   │   ├── layout.tsx, page.tsx                  # 홈
│   │   ├── place/[pnu]/page.tsx                  # 건물(필지) 요약 + 층 목록
│   │   ├── place/[pnu]/[floor]/page.tsx          # 층 이력 (핵심 페이지)
│   │   ├── funding/page.tsx, funding/result/page.tsx
│   │   ├── closure/page.tsx, closure/result/page.tsx
│   │   ├── profile/page.tsx
│   │   ├── methodology/page.tsx
│   │   ├── admin/(protected)/...
│   │   ├── manifest.ts, sitemap.ts, robots.ts
│   ├── components/                # docs/40 §5 컴포넌트 목록
│   ├── lib/                       # api-client(생성 타입), profile-store, format(ko)
│   └── tests/e2e/
├── data/                          # 원천 데이터 파일 (gitignore). data/README.md에 출처·다운로드일 기록
└── storage/                       # 공고 첨부 원문 등 앱이 쓰는 파일 (gitignore, STORAGE_DIR)
```

## 4. 런타임 흐름

### 4.1 자리 페이지 요청
1. 사용자가 주소 검색 → `/api/v1/address/search` (도로명주소 API 프록시, 24시간 캐시) → 결과에서 PNU 생성
2. `/place/{pnu}` 서버 렌더링: `GET /api/v1/places/{pnu}` → 층 목록
3. `/place/{pnu}/{floor}` 서버 렌더링(ISR, `revalidate=86400`): `GET /api/v1/places/{pnu}/floors/{floor}` → 이력 + 기준율 + 데이터 기준일

### 4.2 정책자금·폐업 평가 요청
1. 프로필은 브라우저 저장소에서 읽음 → `POST /api/v1/funding/evaluate` 본문으로 전송
2. 서버: 프로필 검증 → 현재 승인 규칙 스냅샷 로드 → 엔진 실행 → 결과 반환 (저장 없음)
3. 응답 `meta`에 `as_of`, `rule_versions`, `engine_version` 포함 → 같은 입력 재현 가능

## 5. 환경과 배포

| 환경 | 구성 |
|---|---|
| local | `docker compose up` (db, api), `pnpm dev` (web). `.env`는 `.env.example` 복사 |
| ci | GitHub Actions: services/api(ruff, mypy, pytest, import-linter), apps/web(eslint, tsc, vitest, playwright with mock API) |
| prod | web → Vercel. api + db → 단일 VM, Docker Compose, Caddy 자동 HTTPS. DB 일 1회 백업(pg_dump → 외부 저장소, 7일 보관) |

공고 첨부 원문은 `STORAGE_DIR`(기본 `./storage`)에 저장하고 DB와 함께 백업한다. 배치 작업은 VM의 cron이 `docker compose run --rm api python -m jobs.<name>` 실행. 일정은 docs/03 §5.

## 6. 보안

- 관리자 화면·API: 단일 관리자 계정, 비밀번호 해시(argon2) + 세션 쿠키(HttpOnly, Secure, SameSite=Strict). `/admin/*` 외부 IP 제한 옵션
- 공개 API: IP 기준 호출 제한(평가 API 분당 20회, 조회 API 분당 120회), CORS 허용 도메인 고정
- 요청 본문 로그 금지. 로그에는 요청 ID, 경로, 상태 코드, 지연 시간만. `funding`·`closure` 요청 본문이 로그에 찍히지 않는지 테스트로 검증 (docs/50 §6)
- 비밀 값은 환경 변수로만. 저장소에 키 커밋 시 CI 실패(gitleaks)

## 7. 관측

- 지표: API 지연(p50/p95), 오류율, 배치 성공/실패, 데이터 스냅샷 날짜, 승인 규칙 수
- 경보: 배치 2회 연속 실패, 데이터 검증 실패(docs/50 §2), 5xx 비율 1% 초과
