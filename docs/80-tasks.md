# 80. 작업 티켓

## 사용법 (Cursor·사람 공통)

- **티켓 하나 = 브랜치 하나 = PR 하나.** 브랜치명 `t-012-floor-parser`
- **주차 배정의 정본은 docs/70 §1 표.** 이 문서는 단계별로 묶여 있고, 같은 단계 안에서도 docs/70의 주차 순서를 따른다
- 시작 전: 티켓의 "참고" 문서를 읽는다. 문서끼리 또는 문서와 티켓이 충돌하면 **구현을 멈추고 사용자에게 확인한 뒤, 문서를 먼저 고치고** 진행한다 (AGENTS.md §1)
- 완료 = **수용 기준 전부 충족** + `make check` 통과. PR 설명에 수용 기준 체크리스트를 복사해 체크한다
- 티켓 범위 밖 수정 금지. 필요한 일은 하단 "제안 티켓"에 추가한다
- 표기: 🧑 사람이 해야 하는 작업(원문 확보·검수·판단), ⏱ 예상 시간

---

## 1단계 — 기반·수집 (W1~W2)

### T-001 저장소 골격 ⏱4h
- **할 일**: docs/01 §3 구조 생성. `services/api`(uv, Python 3.12, FastAPI·Pydantic v2·SQLAlchemy 2 async·asyncpg·Alembic·pandas·numpy·pyproj·statsmodels / dev: pytest·hypothesis·ruff·mypy·import-linter·mutmut). `apps/web`(pnpm, Next.js 15 App Router·TypeScript strict·Tailwind·ESLint·Prettier·Vitest·Playwright). `Makefile`(setup, check, test, dev, e2e, gen-api). pre-commit(ruff, prettier). `storage/` 폴더(gitignore)
- **import-linter 계약**: `app.location` ↛ `app.rules` / `app.rules` ↛ `app.location` / `anthropic` 패키지는 `app.rules.extraction`에서만 / `app.rules.engine` ↛ `sqlalchemy`, `fastapi`, `httpx`
- **수용 기준**
  - [ ] 새로 클론 후 `make setup && make check` 성공
  - [ ] 계약 위반 코드를 넣으면 `make check` 실패 (테스트용 커밋으로 확인 후 되돌림)
  - [ ] README "빠른 시작" 3줄 이내
- **참고**: docs/01

### T-002 Docker Compose · 헬스체크 ⏱2h
- **할 일**: `services/api/Dockerfile`, `docker-compose.yml`(이미 있는 초안 사용), `GET /api/v1/health`
- **수용 기준**
  - [ ] `docker compose up db api` 후 `/api/v1/health` → 200, `db: ok` (`web`은 Dockerfile이 생기는 T-030부터)
  - [ ] DB 중지 시 503 + 오류 코드 `SERVICE_UNAVAILABLE` (docs/30 §1)
- **참고**: docs/30 §1·2

### T-003 마이그레이션 0001: 위치 테이블 ⏱3h
- **할 일**: Alembic(async) 설정, `0001_location` = docs/04 §2 DDL 그대로
- **수용 기준**
  - [ ] `upgrade head` → `downgrade base` → `upgrade head` 왕복 테스트
  - [ ] CHECK 제약 위반 삽입이 실패하는 테스트 3개 이상
- **참고**: docs/04 §1·2

### T-005 마이그레이션 0002: 규칙·관리자 테이블 ⏱3h
- **할 일**: `0002_rules` = docs/04 §3 DDL 전부(`source_site` ~ `admin_user`, `rate_base` 포함)
- **수용 기준**
  - [ ] 왕복 테스트
  - [ ] `rule_one_approved` 부분 유니크 인덱스: 같은 프로그램에 approved 2개 삽입 실패
  - [ ] `review_log` CHECK: `field_edit`인데 `field_path` 없음 → 실패, `second_review`인데 `rule_id` 없음 → 실패
- **참고**: docs/04 §3

### T-004 CI ⏱2h
- **할 일**: GitHub Actions `api-check`, `api-integration`, `web-check`(이 시점에는 eslint·tsc·vitest만 — `gen:api` 차이 검사는 T-031, `check_copy`는 T-037에서 추가)
- **수용 기준**
  - [ ] PR에서 3개 작업 실행·통과
  - [ ] 린트 위반 PR이 실패함을 확인
- **참고**: docs/50 §8

### T-051S 문서 변환 스파이크 ⏱4h 🧑
- **할 일**: 🧑 실제 공고 5건 확보(소진공 정책자금, 희망리턴패키지, 서울 공고 — HWP·HWPX·PDF 섞어서). HWPX XML 파싱, `hwp5txt`, pdfplumber로 변환해 본문 누락·표 보존 상태 비교
- **수용 기준**
  - [ ] `reports/conversion_spike.md`: 형식별 성공/실패, 표 처리 품질, 채택 방법
  - [ ] 형식별 go/no-go를 ADR로 기록 (no-go 형식은 "수동 텍스트" 경로)
- **참고**: docs/20 §10.2

### T-010 인허가 파일 로더 ⏱5h 🧑
- **할 일**:
  - 🧑 휴게음식점·제과점영업 데이터셋 ID·파일명·이용허락범위를 찾아 `data/README.md`에 기록(다운로드 날짜 포함)
  - `jobs.ingest_licenses --mode full --type {general_restaurant|rest_restaurant|bakery} --file PATH`: 인코딩 자동 판별(CP949 우선, 실패 시 UTF-8), `csv` 모듈로 파싱(**주소에 줄바꿈 포함 행 존재**), 서울 필터(`지번주소` 또는 `도로명주소`가 `서울특별시`로 시작), `data_snapshot` + `license_raw`(COPY) 적재
  - D2 API 조사: 변경분 조회 가능 여부·필드명·한도를 `data/README.md`에 기록. 가능하면 `--mode incremental` 구현, 불가하면 월 1회 전체 적재로 대체하고 ADR 추가
- **수용 기준**
  - [ ] 2026-10-08 서울 일반음식점 파일 적재 행 수 = 539,589
  - [ ] 줄바꿈 포함 주소 행 픽스처 파싱 테스트
  - [ ] 서울 외 행 제외 수 로그
  - [ ] 전체 적재 5분 이내 (로컬 기준)
- **참고**: docs/03 D1·D2

### T-011 법정동코드 · PNU ⏱3h
- **할 일**: `legal_dong` 적재(폐지 코드 포함), `app/address/pnu.py` — `parse_jibun(addr) -> JibunParts | None`, `to_pnu(parts) -> str | None`
- **수용 기준**
  - [ ] docs/10 §2.1 표 전부 + 추가 12개 이상 테스트
  - [ ] **PNU 생성 실패율 < 0.5%** (정의: docs/10 §2.1), 실패 상위 20개를 `reports/pnu_failures.md`로 저장
- **참고**: docs/10 §2

### T-014 좌표계 확정 · 변환 ⏱3h
- **할 일**: 후보 EPSG(2097, 5174, 5181, 5186) 중 원천 좌표계를 판별. 주소를 아는 기록 20건(서로 다른 구)의 좌표를 변환해 지도 서비스의 실제 위치와 비교
- **수용 기준**
  - [ ] 선택한 EPSG로 20건 중앙값 오차 < 30m, 결과표를 ADR에 첨부
  - [ ] `to_wgs84(x, y) -> (lat, lng)` 단위 테스트
- **참고**: docs/03 D1

### T-060a 공고 원문 확보 · 정답셋 분할 · 라벨링 시작 ⏱3h 🧑
- **할 일**:
  - 🧑 정책자금·폐업 지원 대상 공고(docs/21 §2, docs/22 §2) 원문 다운로드 → `storage/`에 저장, `source_site`·`announcement`·`document` 등록
  - `program` 테이블 시드: 대상 사업마다 `id`(연도 없는 안정 키), `module`, `name`, `agency`, `level`, `region_code`, `tags`, `official_url` — 🧑 `official_url`은 실제 공식 페이지만
  - 과거 연도·타 지역 유사 공고 포함 **후보 30건** 목록 `data/announcements.md`, **dev 18 / test 12 분할을 seed로 고정**해 표에 기록
  - `data/labeling-guide.md`: 라벨 JSON 구조(docs/20 §2.3 예시 구조), 근거 인용 규칙, "원문에 없으면 쓰지 않음". 라벨 파일 위치 `eval/labels/{dev,test}/{announcement_key}.json`
- **수용 기준**
  - [ ] 공고 목록(공고명·기관·URL·형식·연도·split) 30건
  - [ ] `program` 시드 마이그레이션 또는 시드 스크립트 + 테스트
  - [ ] dev 라벨 3건
- **참고**: docs/70 §2, docs/50 §5

---

## 2단계 — 정규화 (W3)

### T-012 층 파서 ⏱3h
- **할 일**: `app/location/normalize/floor_parser.py` (docs/10 §3)
- **수용 기준**
  - [ ] docs/10 §3 표 전부 통과
  - [ ] 실제 데이터에서 무작위 40건 추출 → 사람이 기대값 작성 → 테스트 추가 (총 60개 이상)
  - [ ] 속성 테스트: 결과는 `None` 또는 `^(B[1-9]|[1-9][0-9]?|RF)$`
- **참고**: docs/10 §3

### T-013 호 파서 ⏱2h
- **수용 기준**
  - [ ] docs/10 §4 사례 + 실제 데이터 20건, 총 25개 이상 테스트
- **참고**: docs/10 §4

### T-015 행정 일괄 폐업일 탐지 ⏱2h
- **수용 기준**
  - [ ] 규칙 단위 테스트(경계: 정확히 30건, 정확히 중앙값 10배)
  - [ ] W0 방식이 일괄 폐업으로 분류한 기록 44,194건 중 새 규칙도 표시한 비율 ≥ 95%. 미달 시 임계값 조정 근거를 ADR로
- **참고**: docs/10 §5, ADR-020

### T-016 정규화 파이프라인 · 데이터 검증 ⏱5h
- **할 일**: `license_raw` → `license_record` upsert, 상태 매핑, 날짜·면적·PNU·층·호·좌표·일괄폐업 플래그, `parse_version`. DV1~DV10 실행 → `data_snapshot.validation`, 실패 시 `status='failed'`이고 기존 데이터 유지
- **수용 기준**
  - [ ] 영업상태 원문 값 전체 목록을 `data/README.md`에 기록, 매핑 누락 0
  - [ ] DV 검사별 실패 유도 픽스처 테스트
  - [ ] 서울 식품 3종 전체 정규화 10분 이내
- **참고**: docs/50 §2, docs/04 §2

### T-017 미갱신 의심 플래그 ⏱2h
- **수용 기준**
  - [ ] 같은 호 / 같은 면적(±1%) / 둘 다 아님 케이스 테스트
  - [ ] 서울 전체 플래그 수를 리포트
- **참고**: docs/10 §6, ADR-023

---

## 3단계 — 이력·통계·API (W4~W5)

### T-018 층 이력 · 과거 폐업 횟수 ⏱4h
- **할 일**: `parcel`, `floor_summary`, `record_prior` 빌드 (`jobs.build_history`). 과거 폐업 횟수는 층키별 정렬 + 이진 탐색으로 벡터화(`analysis/w0_location_signal.py`의 `prior_closures` 방식)
- **수용 기준**
  - [ ] 합성 층 픽스처: 동시 영업, 같은 날 개·폐업, 일괄 폐업 포함 기록 → 기대값 테스트
  - [ ] `has_concurrent`(30일 초과 겹침) 테스트
  - [ ] 서울 전체 3분 이내
- **참고**: docs/10 §7.1·7.2

### T-019 기준율 · 모형 카드 ⏱5h
- **할 일**: `jobs.compute_base_rates --method-version {2026.10.1|w0}`. Wilson CI, 서울·시군구 범위, 모형 카드(로지스틱+층키 클러스터 SE, 다른 층 통제, 시군구별, 시간 외 AUC, 민감도: 일괄폐업 중도절단·미갱신 제외)
- **수용 기준**
  - [ ] Wilson CI를 알려진 값(n=100, 사건 50 → 0.404~0.596)으로 검증
  - [ ] `model_card.payload`가 docs/10 §7.3 구조를 만족(Pydantic 검증)
  - [ ] 10분 이내
- **참고**: docs/10 §7

### T-020 W0 재현 테스트 ⏱2h
- **수용 기준**
  - [ ] docs/50 §3 기준 통과 (환경 변수 `W0_SEOUL_CSV` 있을 때), 없으면 skip 사유 출력
  - [ ] 식품 3종 결과를 `analysis/README.md` §6에 추가
- **참고**: docs/50 §3

### T-021 주소 검색 프록시 ⏱3h
- **할 일**: 도로명주소 API 클라이언트, 응답 → PNU, `has_history`, 24시간 캐시, 호출 제한
- **수용 기준**
  - [ ] 실제 응답을 녹화한 픽스처로 계약 테스트 (CI는 실호출 없음)
  - [ ] 응답 필드명 확인 결과를 docs/03 D4에 반영(🔎 제거)
- **참고**: docs/30 §2, docs/10 §2.2

### T-022 장소 API ⏱4h
- **할 일**: `GET /places/{pnu}`, `GET /places/{pnu}/floors/{floor}` (docs/30). 기준율 선택(시군구 n≥200이면 주, 아니면 서울), 기준선(버킷 0), notices(docs/10 §7.1 조건표), 숨김 기록 제외
- **수용 기준**
  - [ ] 시드 DB 통합 테스트: 표시/숨김(n<200), 시군구/서울 선택, notices 4종 각각
  - [ ] 응답에 전화번호 필드 없음 테스트 (`test_place_response_no_phone`)
- **참고**: docs/30 §2, docs/10 §7

### T-023 관리자 인증 · 정정 요청 ⏱3h
- **할 일**: `admin_user`(argon2), 세션 쿠키, 로그인 잠금. `POST /places/{pnu}/corrections`, 관리자 `GET /corrections`, `POST /corrections/{id}/resolve`(숨김 처리 → 웹 `POST /api/revalidate` 호출, URL·비밀은 환경 변수 `WEB_REVALIDATE_URL`, `REVALIDATE_SECRET`)
- **수용 기준**
  - [ ] 미인증 401, 5회 실패 잠금 테스트
  - [ ] 숨김 처리 후 장소 API에서 해당 기록 제외
  - [ ] 재생성 호출 테스트(HTTP 목): 대상 경로 2개, 비밀 헤더 포함
- **참고**: docs/30 §1·3, docs/60 §3

### T-030 웹 기반 ⏱4h
- **할 일**: `apps/web/Dockerfile`(compose `web` 서비스), 서버 컴포넌트는 `API_INTERNAL_URL`, 브라우저는 `NEXT_PUBLIC_API_BASE_URL` 사용. 레이아웃·헤더·푸터·`BetaBanner`, 디자인 토큰(본문 17px), `lib/format.ts`, PWA manifest·Serwist, 전역 `noindex`(`INDEXING_ENABLED`), **`lib/profile-store.ts` 골격**(키 `gn.profile.v1`, 이 시점 스키마는 `region`만. T-061은 **optional 필드만 추가**하므로 `schema_version` 1 유지 — 기존 저장값이 그대로 유효), **`app/api/revalidate/route.ts`**(비밀 헤더 검증 후 `revalidatePath`)
- **수용 기준**
  - [ ] `lib/format` 테스트: docs/40 §6 예시 전부
  - [ ] `profile-store`: 저장·읽기·삭제, `localStorage` 예외 시에도 동작 테스트
  - [ ] 잘못된 비밀로 `/api/revalidate` → 401
  - [ ] Lighthouse PWA 설치 가능
- **참고**: docs/40 §1·2·3·6·8

### T-031 API 타입 생성 ⏱1h
- **수용 기준**
  - [ ] `pnpm gen:api` → `lib/api/types.ts`
  - [ ] `web-check`에 차이 검사 추가, 차이 있으면 실패
- **참고**: docs/30, docs/50 §8

### T-032 주소 검색 · 현재 위치 ⏱4h
- **수용 기준**
  - [ ] docs/40 §4.2 상태(로딩·없음·오류·이력 없음) 각각 컴포넌트 테스트
  - [ ] 위치 권한 거부 시 버튼 숨김
- **참고**: docs/40 §4.2, docs/30 `/address/*`

---

## 4단계 — 자리 이력 웹 · Gate 1 (W6)

### T-033 필지 · 층 이력 페이지 ⏱6h
- **할 일**: `/place/[pnu]`, `/place/[pnu]/[floor]` (SSR+ISR), `FloorTimeline`, `BaseRateCard`, notices, 정정 요청 시트, "이 자리로 정책자금 알아보기"(`profile-store`에 `region.sido_code`, `region.sigungu_code` 저장)
- **수용 기준**
  - [ ] 기준율 표시·숨김 두 상태 스냅샷 테스트
  - [ ] 같은 호수 그룹 색 일치
  - [ ] 360px에서 가로 스크롤 없음
- **참고**: docs/40 §4.3·4.4

### T-034 방법론 페이지 ⏱3h
- **수용 기준**
  - [ ] docs/40 §4.9 섹션 전부, 수치는 `/stats/model-card`에서 렌더(하드코딩 금지)
  - [ ] "개별 예측력은 매우 작다"는 AUC 결과 포함
- **참고**: docs/40 §4.9, docs/10 §7.3

### T-035 검색 노출 기반 ⏱1h
- **수용 기준**
  - [ ] `INDEXING_ENABLED`가 `true`가 아니면 모든 페이지 `noindex`, robots 차단
  - [ ] `true`면 기록 2건 이상 층 페이지만 sitemap 포함(시군구 분할)
- **참고**: docs/40 §9

### T-036 E2E: 자리 이력 ⏱2h
- **수용 기준**
  - [ ] (목 API) 검색 → 필지 → 층 → 근거·방법론 → 정정 요청 제출, 모바일 뷰포트
- **참고**: docs/50 §1·7

### T-037 Gate 1 판정 · 프리뷰 배포 · 수요 검증 ⏱4h 🧑
- **할 일**: `scripts/check_copy.py`(금지어 검사)와 `web-check` 연결, `e2e-full`(실제 스택) 작업 추가 — 정정 요청 → 숨김 → 재생성 → 화면 반영, Gate 1 체크리스트 수행, 프리뷰 배포, 🧑 수요 검증 공유
- **수용 기준**
  - [ ] `e2e-full` 정정 흐름 통과
  - [ ] docs/50 §7 Gate 1 전 항목 결과를 `reports/gate1.md`에 기록
  - [ ] 공유 글·날짜·채널 기록 (docs/70 §5)
- **참고**: docs/50 §7·8, docs/70 §5

---

## 5단계 — 규칙 엔진 ①~③ (W7)

### T-040 DSL 모델 · 검증 ⏱4h
- **할 일**: `app/rules/dsl` Pydantic 모델(docs/20 §2), `jobs.export_dsl_schema`, 승인 전 검증 함수(ev 필수, 사실 레지스트리, op/value 타입, `deduct_balance.of`는 태그만, procedure DAG). 가상 규칙 픽스처 `tests/fixtures/rules/{funding,closure}_example_*.json`. 그때까지 만든 라벨 JSON을 전부 검증해 고친다
- **수용 기준**
  - [ ] 잘못된 규칙 15종 이상이 구체적 오류 메시지로 거부 (`exists` 연산자 사용 포함)
  - [ ] 가상 픽스처가 DSL 모든 기능(op 전부, 금액 타입 전부, 충돌 2종, cap_group, limit_adjustment, procedure, manual_notes)을 최소 1회 사용
  - [ ] 기존 라벨 전부 스키마 통과
- **참고**: docs/20 §2·3

### T-041 사실 레지스트리 · 3치 평가기 ⏱5h
- **할 일**: `Facts`(스칼라·구간·날짜 구간·None), 레지스트리, `elapsed_months`, `tri_logic.evaluate_condition`, `decisive`, `missing_facts`, `lifetime_once`, `manual_notes` 강등
- **수용 기준**
  - [ ] 진리표 전부, 연산자 × (스칼라·구간·None) 테스트
  - [ ] `elapsed_months` 경계 7개(docs/20 §2.2) 테스트
  - [ ] 속성 P2·P3 통과 (P1은 T-045·T-047)
- **참고**: docs/20 §2.2·3·4, docs/50 §4

### T-042 접수 상태 ⏱1h
- **수용 기준**
  - [ ] 시작일·마감일 당일, `apply_end` 없음, `apply_start` 없음(`availability_unknown`), `valid_to` 경과 테스트
- **참고**: docs/20 §5

### T-043 금액 · 금리 ⏱4h
- **할 일**: 금액 타입 5종, `Fraction` 면적 환산, 반올림·플래그, `RateInfo`와 `rate_bases` 입력(변동금리 계산)
- **수용 기준**
  - [ ] 금액 타입별·플래그별 테스트, 평↔㎡ 계산
  - [ ] 변동금리 = 기준값 + 가산, 기준값 없으면 `type=unknown` 처리
  - [ ] 속성 P4·P5 통과
- **참고**: docs/20 §6

### T-044 제약: 충돌 · 한도 그룹 · 한도 차감 ⏱3h
- **수용 기준**
  - [ ] 한쪽만 선언한 충돌의 양방향 적용, scope unknown → apply 테스트
  - [ ] cap_group 상충 선언 → 최솟값 + `cap_conflict`
  - [ ] 잔액 사실 `None` → `balance_unknown` 플래그
- **참고**: docs/20 §6.4, ADR-008

---

## 6단계 — 규칙 엔진 ④~⑥ (W8)

### T-045 최적화기 ⏱6h
- **수용 기준**
  - [ ] 목적함수 4종(docs/20 §7.3)과 동률 해소 테스트
  - [ ] 속성 P6~P8 통과 (P8: 후보 ≤6 전수 열거와 비교), P1(계획까지)
  - [ ] F-S1~S8·S10, C-S1·S6·S7·S8 통과
  - [ ] 엔진 `evaluate` 최악 경우(후보 8개) 500ms 이내 (API p95 800ms 예산 안)
- **참고**: docs/20 §7, ADR-017·022

### T-046 타임라인 · 법정 기한 레지스트리 ⏱4h
- **할 일**: StepId enum(모듈별), 계획별 `Timeline`(docs/20 §1 모델), DAG·위상 정렬, `legal_deadlines.py`(`vat_closure_final_return`), 경고
- **수용 기준**
  - [ ] 속성 P9, F-S9, C-S2·S10·S12 통과
  - [ ] 부가세 기한: 월말·12월·윤년 2월 폐업일 테스트
- **참고**: docs/20 §8, docs/22 §5

### T-047 설명 템플릿 ⏱3h
- **수용 기준**
  - [ ] 속성 P10(docs/20 §7.4 경고 키 전체 포함, 누락 0), P1(설명 문장까지 전체 `Evaluation`)
  - [ ] `check_copy.py`가 템플릿 파일을 검사해 통과
- **참고**: docs/20 §7.4·9, docs/40 §6

### T-048 속성 테스트 정비 · 뮤테이션 ⏱2h
- **수용 기준**
  - [ ] Hypothesis 전략(사실·규칙 생성기) 공용화
  - [ ] mutmut `rules/engine` 점수 측정, 80% 미만이면 살아남은 변이 목록과 보강 계획을 `reports/mutation.md`에
- **참고**: docs/50 §4

---

## 7단계 — 수집·추출·검수 (W9~W10)

### T-050 공고 수집기 · 변경 감지 ⏱4h
- **수용 기준**
  - [ ] 기업마당 API·페이지 감시 녹화 픽스처 테스트, 첨부 해시 변경 → `change_event`
  - [ ] 사이트당 초당 1회 이하, robots 준수 테스트
- **참고**: docs/03 R1, docs/20 §11

### T-051 문서 변환 구현 ⏱4h
- **수용 기준**
  - [ ] T-051S에서 채택한 방법으로 형식별 변환 + `line_index`
  - [ ] 실패 → `convert_status='failed'`, 수동 텍스트 업로드 경로 동작
- **참고**: docs/20 §10.2

### T-052 LLM 추출기 ⏱6h
- **할 일**: 프롬프트 파일(버전 = 해시), `emit_rules` 도구 스키마 = DSL 스키마, 자동 검증(docs/20 §10.4)
- **수용 기준**
  - [ ] 녹화된 LLM 응답 픽스처로 테스트(CI 실호출 없음)
  - [ ] 수치 파서 테스트: `3천만원`, `1억 2천만 원`, `30,000,000원`, `4.5%`, `연 4.5퍼센트`, `6개월`, `2026. 3. 2.`
  - [ ] 근거 정규화 테스트: 줄바꿈·공백·전각 문자 차이는 `similarity ≥ 0.92`, 단어 바뀜은 미달
- **참고**: docs/20 §10

### T-053 검수 API ⏱3h
- **할 일**: docs/30 §3 검수 엔드포인트 + `POST /rules/{rule_id}/second-review` + `PUT /rate-bases`
- **수용 기준**
  - [ ] `ev` 누락·레지스트리 밖 사실 키·사이클 있는 규칙 승인 → 거부
  - [ ] 프로그램당 approved 1개 보장, 이전 버전 retired
  - [ ] `review_log`에 종류·필드·소요 시간 기록, 24시간 전 2차 검수 → 409
- **참고**: docs/30 §3, docs/20 §11, docs/04 §3

### T-054 관리자 검수 화면 ⏱6h
- **수용 기준**
  - [ ] 원문 하이라이트 ↔ 필드 연결, `needs_review` 표시, 타이머
  - [ ] 공고 1건 검수 흐름 E2E
- **참고**: docs/40 §4.10

### T-055 규칙 버전 배포 ⏱2h
- **수용 기준**
  - [ ] 승인 즉시 평가 API가 새 버전 사용(캐시 무효화), 응답 `meta.rule_versions` 반영
  - [ ] 열린 `change_event` → `/programs`의 `under_review=true`
- **참고**: docs/20 §11

### T-056 정답셋 · 평가 러너 ⏱4h
- **할 일**: `eval/labels/` 라벨 JSON → `eval_case` 적재(T-060a의 split 그대로), 정규화기, 지표, 공고 단위 부트스트랩
- **수용 기준**
  - [ ] 정규화 동치 테스트(docs/50 §5)
  - [ ] 부트스트랩(seed 고정) 결과 재현
  - [ ] test split 실행 하루 1회·총 3회 제한
  - [ ] dev 지표 v1을 `eval_run`에 기록
- **참고**: docs/50 §5

### T-061 정책자금 어댑터 · 프로필 스키마 ⏱4h 🧑
- **할 일**: `BusinessProfile`(Pydantic `extra="forbid"`) + zod 스키마(`profile-store` 확장), `profile_to_facts`, `credit_bands`, 업종 카탈로그(KSIC 기반 내부 목록), 🧑 소상공인 판정 기준표를 법령 원문으로 확인(불가 시 "확인서 발급 가능" 질문으로 대체)
- **수용 기준**
  - [ ] 파생 사실 경계 테스트(개업 당월, 연·월만 입력 → 날짜 구간, 기준일=개업일)
  - [ ] 알 수 없는 필드 422, 잘못된 신용 구간 ID 422, 사라진 구간 ID → `credit_band_stale`
  - [ ] 추가 필드 전부 optional: T-030 시점 형식(`region`만)으로 저장된 프로필이 그대로 검증 통과
- **참고**: docs/21 §3·4, docs/20 §3

---

## 8단계 — 정책자금 · Gate 2 (W11)

### T-060b 정책자금 규칙 확정 ⏱6h 🧑
- **할 일**: 🧑 추출 → 검수 → 승인 → **24시간 이후 2차 검수**(`/rules/{id}/second-review`) → 사업별 골든 테스트 2개 이상
- **수용 기준**
  - [ ] 대상 사업 전부 approved + 2차 검수 기록
  - [ ] `tests/golden/{program_id}.yaml` 통과
- **참고**: docs/21 §2, docs/50 §4.4

### T-062 `POST /funding/evaluate` · `/funding/credit-bands` ⏱2h
- **수용 기준**
  - [ ] 응답 `meta` 재현 정보 포함, 본문 로그 없음 테스트(`test_no_body_logging`)
- **참고**: docs/30 §2

### T-063 정책자금 화면 ⏱8h 🧑
- **할 일**: 마법사(docs/21 §3), 결과(docs/40 §4.6), `BrokerNotice` — 🧑 공식 신고 경로 URL·1357 번호·제도 설명 문구를 공식 자료로 확인
- **수용 기준**
  - [ ] 단계별 "모름" → 결과의 `MissingFactsPrompt` 딥링크 동작
  - [ ] 참고안 기본 접힘 + `debt_increase` 경고
  - [ ] 근거 시트가 `(program_id, rule_version, ev)`로 열림
  - [ ] 확인되지 않은 링크·번호·수치 0개
- **참고**: docs/21 §5·6, docs/40 §4.5·4.6

### T-064 정책자금 E2E · Gate 2 판정 ⏱3h 🧑
- **수용 기준**
  - [ ] E2E: 마법사 → 결과 → 근거 시트
  - [ ] 추출 평가 test 1회 실행·리포트(신뢰구간)
  - [ ] `reports/gate2.md`에 docs/50 §7 Gate 2 체크 결과
- **참고**: docs/50 §7

---

## 9단계 — 폐업 지원 · 통합 · 배포 (W12~W13)

### T-070 폐업 지원 규칙 ⏱6h 🧑
- **수용 기준**
  - [ ] 희망리턴패키지 + 서울 사업 approved, 2차 검수, 골든 테스트 2개 이상씩
  - [ ] docs/22 §4 검수 체크리스트 사업별 기록
- **참고**: docs/22

### T-071 `POST /closure/evaluate` · 부가세 기한 검증 ⏱3h 🧑
- **수용 기준**
  - [ ] 🧑 부가가치세법 조문 원문 대조 후 테스트에 조문 인용 주석, docs/03 R3 🔎 제거
  - [ ] C-S1~S12 통과
- **참고**: docs/22 §5·7

### T-072 폐업 지원 화면 ⏱6h
- **수용 기준**
  - [ ] 계획 2안 탭, 날짜 있는/없는 타임라인 노드, 함정 체크리스트, 경영개선 카드
  - [ ] E2E 1개
- **참고**: docs/40 §4.7

### T-080 홈 통합 · 프로필 공유 ⏱4h
- **수용 기준**
  - [ ] 자리 페이지 → 정책자금 → 폐업으로 같은 프로필이 이어짐
  - [ ] `/profile` 삭제 후 저장소 비어 있음
- **참고**: docs/40 §4.1·4.8

### T-081 운영 배포 ⏱4h
- **수용 기준**
  - [ ] Vercel + VM(Compose, Caddy HTTPS), cron 배치(docs/03 §5) 동작
  - [ ] DB와 `storage/` 백업, 백업에서 복원 1회 실제 수행 기록
- **참고**: docs/01 §5

### T-082 관측 · 보안 점검 ⏱2h
- **수용 기준**
  - [ ] Sentry 연결, 경보 3종(docs/01 §7), gitleaks·audit 통과
- **참고**: docs/01 §6·7

### T-083 포트폴리오 문서 ⏱6h 🧑
- **수용 기준**
  - [ ] README(문제→해결→아키텍처→지표→설계 결정, 30초 안에 이해)
  - [ ] `docs/eval-report.md`: 추출 dev 버전별 변화 + test 최종(신뢰구간) + 실패 사례 분석, 자리 통계 결과와 한계
  - [ ] 2분 데모 영상 스크립트·녹화, 면접용 1분 설명
- **참고**: docs/00 §7

---

## 확장

### T-090 호실 연결 연구 ⏱8h
- **수용 기준**
  - [ ] docs/10 §8.3 방법으로 시군구 hold-out 평가, 리포트 `reports/unit_matching.md`
  - [ ] 게이트(P ≥ 0.90, R ≥ 0.40) 판정. 통과 시 화면 표시를 위한 새 ADR 제안
- **참고**: docs/10 §8

---

## 제안 티켓 (작업 중 발견한 일은 여기에 추가)

| ID | 제목 | 이유 | 제안일 |
|---|---|---|---|
| | | | |
