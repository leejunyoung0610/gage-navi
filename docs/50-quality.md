# 50. 품질: 테스트 · 평가 · 데이터 검증 · 공개 게이트

## 1. 테스트 구성

| 층위 | 위치 | 도구 | 기준 |
|---|---|---|---|
| 단위 | `services/api/tests/unit` | pytest | `rules/engine`, `location/normalize` 줄 커버리지 ≥ 90% |
| 속성 기반 | `tests/property` | Hypothesis | §4.2 속성 전부 |
| 시나리오 | `tests/scenario` | pytest + 가상 규칙 픽스처 | F-S1~S10, C-S1~S12 |
| 골든 | `tests/golden` | pytest + 실제 승인 규칙 | 사업별 사람 계산 사례 ≥ 2개 (§4.4) |
| 통합 | `tests/integration` | pytest + 테스트 DB(docker) | API 계약, 마이그레이션 |
| 뮤테이션 | CI 주 1회 | mutmut | `rules/engine` 점수 ≥ 80% |
| 프론트 단위 | `apps/web` | Vitest | `lib/format`, `profile-store` 마이그레이션 |
| E2E | `apps/web/tests/e2e` | Playwright (모바일 뷰포트 390×844) | §7 게이트 시나리오 |

## 2. 데이터 검증 (수집할 때마다, 결과는 `data_snapshot.validation`)

| ID | 검사 | 실패 조건 | 조치 |
|---|---|---|---|
| DV1 | 행 수 변화 | 전체 적재가 직전 대비 ±5% 초과 | 스냅샷 `failed`, 기존 데이터 유지, 경보 |
| DV2 | `관리번호` 고유 | 중복 존재 | 실패 |
| DV3 | `인허가일자` 파싱 | 성공률 < 99% | 실패 |
| DV4 | 날짜 역전 | `폐업일자 < 인허가일자` 1건 이상 | 해당 행 격리 + 경고 (W0 실측 0건) |
| DV5 | 영업상태 값 | 알려진 목록 밖의 값 | 실패 (매핑 추가 후 재실행) |
| DV6 | PNU 생성 실패율 (정의: docs/10 §2.1) | ≥ 0.5% | 실패 |
| DV7 | 층 정보 비율(2005년 이후 개업) | 직전 대비 ±3%p 초과 | 경고 |
| DV8 | 좌표 범위 | 좌표 있는 행 중 서울 경계 상자(위도 37.40~37.72, 경도 126.73~127.27) 밖 > 1% | 경고 |
| DV9 | 폐업 처리 급증일 | 탐지 날짜 수·기록 수 기록 | 기록만 |
| DV10 | 폐업인데 폐업일자 없음 | 비율 > 0.1% | 경고 (W0 실측 27건) |

- 실행: `jobs.normalize_licenses`(T-016). 종류별 최신 `loaded` 스냅샷을 한 번에 정규화한다. 결과는 스냅샷마다 `validation.normalize`에 적는다(적재 때 쓴 `validation.ingest`는 그대로 둔다)
- **실패**(DV1·2·3·5·6)가 하나라도 있으면 `license_record`·`closure_surge_day`를 바꾸지 않고, 실패한 스냅샷을 `failed`로 둔다. 모두 통과하면 `validated`
- 비교 대상("직전", DV1·DV7)은 같은 종류의 가장 최근 `validated` 스냅샷. 없으면(첫 적재) 비교하지 않고 값만 적는다
- DV4의 격리: 해당 행은 `license_record`에 넣지 않는다(테이블 CHECK와 같다). 수를 적는다
- DV8 경계 상자의 근거: 2026-10 세 파일의 변환 좌표 실측 범위(위도 37.4304~37.6921, 경도 126.7795~127.1827 — T-016 측정. 위도는 T-014·ADR-026의 37.43~37.69와 같다)를 감싸도록 잡은 상자다. 이 검사의 목적은 **좌표계 오류**를 잡는 것이다 — 좌표계를 잘못 읽으면 수십 km 이상 옮겨진다(EPSG:5186으로 읽으면 전 행이 위도 36.53~36.79, 약 100km 남쪽. ADR-026). 그래서 정밀한 행정 경계는 필요 없다
- 검사 말고 함께 적는 값: `non_seoul_excluded`(서울 밖 주소라 뺀 행), `no_fixed_place`(고정된 자리가 없는 업태), `floor_conflict`·`ho_conflict`(지번 꼬리와 도로명 상세가 서로 다른 층·호를 말한 기록, docs/10 §3·§4), 영업상태·업태 값별 건수, `parse_version`

## 3. 자리 통계 재현 테스트

- `tests/integration/test_w0_reproduction.py`: 서울 일반음식점 2026-10-08 스냅샷(UTF-8 변환 파일, 경로는 환경 변수 `W0_SEOUL_CSV` — 없으면 skip하고 사유 출력)으로 `method_version='w0'` 계산
- 기대값(docs/10 §7.4): 버킷별 n은 ±1%, 비율은 ±0.3%p 이내
- 로지스틱(W0 사양) 과거 폐업 1회당 OR 1.075 ± 0.005
- 식품 3종 `2026.10.1` 결과는 기대값 고정 없이 `model_card`에 기록하고, 방법론 페이지에 표시. **OR의 95% 신뢰구간 하한이 1 이하로 나오면** 기준율 카드 문구를 그대로 두되 방법론 페이지에 "식품 3종 통합 시 유의한 차이가 확인되지 않았어요"를 표시하고 ADR을 추가한다

## 4. 규칙 엔진

### 4.1 단위 테스트 필수 항목
3치 진리표 전부(all/any/not × 자식 조합), 모든 연산자 × (스칼라·구간·None), 경과 개월 경계(월말, 윤년), 접수 상태 경계일(시작일·마감일 당일), 금액 타입별 계산과 플래그, 평→㎡ 변환과 반올림, cap_group 최솟값 처리, DFS 동률 해소

### 4.2 속성 기반 테스트 (Hypothesis)
| ID | 속성 |
|---|---|
| P1 결정론 | 같은 (사실, 규칙, 기준일, 목적) → 같은 `Evaluation` (직렬화 비교) |
| P2 정보 단조성 | `None`인 사실을 아무 구체값으로 채워도, 원래 MET 또는 NOT_MET이던 사업 판정은 바뀌지 않는다 (구간을 좁히는 경우도 동일) |
| P3 구간 일관성 | 구간 `[x, x]`의 평가 = 스칼라 `x`의 평가 |
| P4 면적 단조 | `per_area` 금액은 면적에 대해 감소하지 않는다 |
| P5 상한 | `cap_krw`가 있는 모든 금액 ≤ `cap_krw` / `per_area` 금액 ≤ 견적 공급가액(있으면) |
| P6 충돌 | 어떤 계획에도 `apply` 충돌 쌍이 함께 없다 |
| P7 배분 | 각 `allocated ≤ 가용 한도(그 순서 기준)`, `need_cover`의 배분 합 ≤ 필요 금액, cap_group 합 ≤ cap − 기존 잔액 |
| P8 최적성 | 후보 ≤ 6개에서 DFS 결과의 목적함수 값 = 전수 열거의 최적값 |
| P9 위상 순서 | 타임라인 순서가 모든 `before/after` 간선을 지킨다 |
| P10 설명 완전성 | 생성된 모든 trace·경고 키에 템플릿이 존재한다 |

### 4.3 시나리오 테스트
docs/21 §8 (F-S1~S10), docs/22 §7 (C-S1~S12). 가상 규칙 픽스처는 `tests/fixtures/rules/`에 두고 파일 첫 줄 `"_comment": "가상 예시 — 실제 사업 아님"`.

### 4.4 골든 테스트 (실제 규칙)
승인된 실제 규칙마다 사람이 공고 원문만 보고 손으로 판정한 프로필 **최소 2개(충족 1, 불충족 1)** 를 `tests/golden/{program_id}.yaml`에 작성. 규칙 새 버전 승인 시 CI에서 전부 통과해야 배포.

### 4.5 호실 연결 연구 (docs/10 §8)
시군구 hold-out 평가 스크립트 `jobs.eval_unit_matching` → 쌍 P/R/F1, B-cubed를 리포트로 저장. 게이트: test 시군구에서 P ≥ 0.90, R ≥ 0.40.

## 5. 규칙 추출 평가

**중요**: 사용자에게 보이는 규칙은 전부 사람이 검수하므로(ADR-002), 추출 정확도는 *검수 비용*을 결정하는 지표이지 사용자 정확도를 보장하는 지표가 아니다. 사용자 정확도는 §4.4 골든 테스트와 §7 게이트가 보장한다.

| 항목 | 정의 |
|---|---|
| 정답셋 | 공고 30건(정책자금+폐업, 과거 연도·타 지역 유사 공고 포함). 라벨 파일은 `eval/labels/{dev,test}/{announcement_key}.json`(커밋 대상). 공고 단위로 **dev 18 / test 12** 분할. 분할은 T-060a에서 후보 목록을 만들 때 한 번 고정(seed 기록), dev부터 라벨링. test 12건은 신뢰구간이 넓다는 점을 리포트에 명시 |
| 정규화 | 조건 순서 무시, 동치 변환(`lte v` ↔ `not gt v`), 금액 원 단위, 날짜 ISO, 면적 ㎡ 환산 비교, `all` 중첩 평탄화 |
| 조건 P/R/F1 | 정규화된 리프 `(fact, op, value)` 일치 기준, 공고별 집계 후 전체 |
| 수치 정확도 | 금액·날짜·인원·개월·퍼센트 필드 완전 일치율 |
| 근거 지지율 | 근거 인용문이 그 조건을 실제로 뒷받침하는 비율 (사람이 50개 표본 판정) |
| unknown 적정성 | 원문에 없는 정보를 `unknown`/생략으로 둔 비율 (정답에 unknown인 필드 기준) |
| 표현 불가율 | `manual_notes`로 빠진 조건 비율 |
| 검수 시간 | 공고 1건당 `review_log.seconds_spent` 합 (중앙값) — 수작업 라벨링 시간과 비교 |
| 신뢰구간 | **공고 단위 부트스트랩** 1,000회, 95% 백분위 구간. 점추정만 보고 금지 |
| test 사용 규칙 | 프롬프트 버전을 "확정"할 때만 실행, 전체 기간 최대 3회, 모든 실행을 `eval_run`에 기록 |
| 라벨 일관성 | 1주 후 5건 재라벨링(`relabel_of`) → 조건 F1로 자기 일관성 보고 |

`eval_run.metrics` 형식:
```json
{"n_announcements": 12, "condition": {"p": [0.91, 0.86, 0.95], "r": [0.84, 0.78, 0.89], "f1": [0.87, 0.83, 0.91]},
 "numeric_accuracy": [0.96, 0.93, 0.98], "unknown_appropriateness": [0.8, 0.7, 0.9],
 "inexpressible_rate": 0.07, "review_seconds_median": 540}
```
(배열 = [점추정, CI 하한, CI 상한], 값은 형식 예시)

## 6. 개인정보·보안 테스트

- `test_no_body_logging`: `funding/evaluate`, `closure/evaluate` 호출 후 로그 캡처에 프로필 값(테스트용 고유 문자열·금액)이 없어야 함
- `test_place_response_no_phone`: 장소 응답 스키마에 전화번호 필드 없음
- `test_profile_extra_forbid`: 알 수 없는 프로필 필드(예: `credit_score_exact`) → 422
- 관리자 API 인증 없는 접근 → 401, 로그인 잠금 동작
- gitleaks(비밀 커밋 방지), 의존성 취약점 스캔(pip-audit, pnpm audit) 주 1회

## 7. 공개 게이트

### Gate 1 — 자리 이력 공개
- [ ] 최신 스냅샷 데이터 검증 DV1~DV10 통과
- [ ] W0 재현 테스트 통과 (§3)
- [ ] 식품 3종 모형 카드 생성, 방법론 페이지에 표시 (AUC 한계 포함)
- [ ] 층 파서 테스트 ≥ 60개 통과, PNU 생성 실패율 < 0.5%
- [ ] 검색 일치율 리포트 (보고 의무)
- [ ] 정정 요청 → 관리자 숨김 처리 → on-demand 재생성 → 화면 반영 E2E (**실제 API**, `e2e-full`)
- [ ] 금지 표현 검사(`scripts/check_copy.py`: 템플릿·화면 문자열에서 docs/40 §6 금지어 탐지) 통과
- [ ] E2E: 주소 검색 → 필지 → 층 이력 → 근거/방법론
- [ ] Lighthouse 모바일: 성능 ≥ 80, 접근성 ≥ 95
- [ ] §6 중 자리 이력 해당 항목 통과(`test_place_response_no_phone`, 관리자 인증·잠금, gitleaks)

### Gate 2 — 정책자금 공개
- [ ] 모든 승인 규칙: 전 항목 근거 존재, **2차 검수 완료**(첫 승인 후 24시간 이상 지나 원문과 다시 대조, `review_log.review_kind='second_review'`)
- [ ] §6 개인정보·보안 테스트 전체 통과
- [ ] 사업별 골든 테스트 ≥ 2개 통과
- [ ] F-S1~S10, P1~P10 통과, 뮤테이션 점수 ≥ 80%
- [ ] 추출 평가 test 결과를 신뢰구간과 함께 리포트 (통과 기준 아님, 보고 의무)
- [ ] docs/60 §2 체크리스트 전부 확인
- [ ] **docs/60 §2.3 법률 검토 완료** (검토자·날짜·결론 기록). 완료 전에는 다른 항목을 다 채워도 베타 배너 + 비공개 링크로만 둔다 (docs/70 §4)
- [ ] 브로커 주의 안내의 공식 링크·번호 확인 완료

### Gate 3 — 폐업 지원 공개
- [ ] Gate 2와 같은 규칙 품질 항목
- [ ] C-S1~S12 통과, 부가세 기한 테스트에 조문 인용 주석
- [ ] 경영개선 지원 카드 노출 확인

## 8. CI (GitHub Actions)

| 작업 | 트리거 | 내용 |
|---|---|---|
| `api-check` | PR | `make check-api` — ruff(check·format --check), mypy, import-linter(모듈 경계·LLM import 제한), pytest(unit·property·scenario·golden) |
| `api-integration` | PR | docker postgres로 마이그레이션 + 통합 테스트 |
| `web-check` | PR | `make check-web` — eslint, tsc, prettier --check, vitest (T-004). `gen:api` 차이 검사는 T-031, `check_copy`는 T-037에서 추가 |
| `e2e` | PR(라벨) · main | Playwright (API 목 서버) |
| `e2e-full` | main · 게이트 판정 시 | docker compose(db+api+web) 실제 스택 Playwright — 정정 요청·재생성 흐름 |
| `mutation` | 주 1회 | mutmut `rules/engine` |
| `security` | 주 1회 | gitleaks, pip-audit, pnpm audit |
