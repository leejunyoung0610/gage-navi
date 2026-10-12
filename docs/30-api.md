# 30. API 명세

- 기본 경로: 공개 `/api/v1`, 관리자 `/admin/v1`
- 형식: JSON(UTF-8). 날짜 `YYYY-MM-DD`, 시각 ISO 8601(+09:00 표기). 금액은 원 단위 정수. 퍼센트·비율은 문자열 소수(`"0.4340"`)
- 요청 모델은 Pydantic `extra="forbid"` — 알 수 없는 필드는 422
- OpenAPI는 FastAPI가 생성. 프론트 타입은 `pnpm gen:api`(openapi-typescript)로 생성하며, CI가 생성 결과와 커밋된 파일의 차이를 검사한다
- 아래 예시의 코드·수치·상호는 형식 설명용이다

## 1. 공통 응답

성공:
```json
{ "data": { }, "meta": { "request_id": "01J…", "data_as_of": "2026-11-01" } }
```
오류:
```json
{ "error": { "code": "NO_HISTORY", "message": "이 필지에는 식품 업소 인허가 기록이 없어요.", "details": {} }, "meta": { "request_id": "01J…" } }
```

| code | HTTP | 의미 |
|---|---|---|
| `VALIDATION_ERROR` | 422 | 입력 검증 실패 (`details.fields`) |
| `NOT_FOUND` | 404 | 리소스 없음 |
| `NO_HISTORY` | 404 | 필지·층은 유효하나 이력 없음 |
| `RATE_LIMITED` | 429 | 호출 제한 (`Retry-After` 헤더) |
| `UPSTREAM_UNAVAILABLE` | 502 | 도로명주소·지도 API 실패 |
| `SERVICE_UNAVAILABLE` | 503 | DB 등 내부 의존성 장애 (헬스체크 포함) |
| `UNAUTHORIZED` / `FORBIDDEN` | 401 / 403 | 관리자 인증 |
| `CONFLICT` | 409 | 규칙 승인 경합 등 |
| `INTERNAL` | 500 | 그 외 (메시지는 일반 문구, 상세는 Sentry) |

**호출 제한(IP 기준)**: 조회 120회/분, 평가(`*/evaluate`) 20회/분, 정정 요청 5회/시간.
**캐시**: 장소 조회 `Cache-Control: public, max-age=300` (API 앞에 CDN 없음) / 평가 `no-store`. 웹의 장소 페이지는 ISR(1일)이며, 관리자가 정정 요청으로 기록을 숨기면 API가 웹의 `POST /api/revalidate`(헤더 `x-revalidate-secret`)를 호출해 해당 `/place/{pnu}`·`/place/{pnu}/{floor}`를 즉시 재생성한다.

## 2. 공개 API

### `GET /api/v1/health`
`{"status": "ok", "db": "ok", "location_snapshot": "2026-11", "approved_rules": 14}`

- 공통 응답(§1)의 예외: 성공 응답을 `data`/`meta`로 감싸지 않는다 (모니터링 도구용). 오류는 §1 형식 그대로 503 `SERVICE_UNAVAILABLE`
- `location_snapshot`·`approved_rules`는 값을 알 수 없으면 `null` (해당 테이블이 없는 T-003·T-005 이전 포함)

### `GET /api/v1/address/search?q={검색어}&page={1}`
도로명주소 API 프록시. `q` 2자 이상.
```json
{"data": {"items": [{
  "road_addr": "서울특별시 광진구 능동로 120",
  "jibun_addr": "서울특별시 광진구 화양동 1",
  "building_name": "○○빌딩",
  "pnu": "1121510700100010000",
  "has_history": true
}], "page": 1, "total": 3}}
```
`has_history`: `parcel` 테이블 존재 여부.

### `GET /api/v1/address/reverse?lat={위도}&lng={경도}`
현재 위치 → 같은 형식 1건(카카오 좌표→주소 변환). T-032에서 구현, 실패 시 `UPSTREAM_UNAVAILABLE`.

### `GET /api/v1/places/{pnu}`
```json
{"data": {
  "pnu": "1121510700100470001",
  "jibun_label": "서울특별시 광진구 화양동 47-1",
  "road_addr": "서울특별시 광진구 ○○로 12",
  "location": {"lat": 37.54, "lng": 127.07},
  "floors": [{"floor": "B1", "record_count": 3, "open_now_count": 1},
             {"floor": "1",  "record_count": 7, "open_now_count": 1}],
  "records_without_floor": 4
}}
```
`records_without_floor`: 층 정보가 없어 층 이력에 포함되지 않은 기록 수(화면 고지용).

### `GET /api/v1/places/{pnu}/floors/{floor}`
```json
{"data": {
  "pnu": "1121510700100470001", "floor": "1", "jibun_label": "서울특별시 광진구 화양동 47-1",
  "summary": {"record_count": 7, "records_since_2005": 5, "open_now_count": 1,
              "median_closed_tenure_days": 812, "has_concurrent": false},
  "history": [{
    "record_id": 1032, "name": "○○분식", "license_type": "general_restaurant", "biz_category": "분식",
    "opened_on": "2011-03-02", "closed_on": "2013-08-30", "status": "closed", "tenure_days": 912,
    "ho_list": ["101"], "bulk_closure": false, "stale_suspect": false
  }],
  "ho_groups": [{"ho": "101", "record_ids": [1032, 2210]}],
  "base_rate": {
    "display": true, "hidden_reason": null,
    "prior_closures_now": 4, "bucket": "4+",
    "primary":   {"scope_code": "11215", "scope_label": "광진구", "rate": "0.4310", "ci": ["0.3920", "0.4710"], "n": 612},
    "baseline":  {"scope_code": "11215", "bucket": "0", "rate": "0.2950", "ci": ["0.2810", "0.3090"], "n": 4012},
    "secondary": {"scope_code": "11", "scope_label": "서울", "rate": "0.4340", "ci": ["0.4260", "0.4420"], "n": 14532},
    "snapshot_label": "2026-11", "method_version": "2026.10.1"
  },
  "notices": ["multiple_units_possible", "bulk_closure_present"],
  "data_as_of": "2026-11-01"
}}
```
- `display=false`이면 `hidden_reason = "insufficient_sample"`(해당 버킷 n < 200, 시군구·서울 모두)
- `notices` 값과 발생 조건: docs/10 §7.1
- 숨김 처리된 기록(`record_suppression`)은 응답에서 제외
- 응답에 전화번호 등 개인정보 필드 없음

### `POST /api/v1/places/{pnu}/corrections`
요청 `{"floor": "1", "record_id": 1032, "kind": "wrong_info", "message": "…"}` → 201 `{"data": {"id": 55}}`. 연락처 필드 없음.

### `GET /api/v1/stats/model-card`
최신 `model_card.payload` (docs/10 §7.3).

### `GET /api/v1/programs?module=funding|closure`
```json
{"data": {"items": [{
  "program_id": "sbiz.general_stability", "name": "…", "agency": "소상공인시장진흥공단",
  "availability": "OPEN", "budget_limited": true, "official_url": "https://…",
  "rule_version": 3, "checked_on": "2026-11-20", "under_review": false
}]}}
```
`under_review`: 열린 `change_event` 존재.

### `GET /api/v1/programs/{program_id}`
위 항목 + `rule_summary`(조건 목록을 템플릿 문장으로) + `evidence`(키별 인용문·위치).

### `GET /api/v1/evidence/{program_id}/{rule_version}/{ev_key}`
`{"quote": "…", "loc": "p3:l12-14", "document": {"file_name": "….hwpx"}, "announcement": {"title": "…", "url": "https://…"}, "checked_on": "2026-11-20"}`

### `GET /api/v1/funding/credit-bands`
`{"data": {"bands": [{"id": "cs_0_799", "lo": 0, "hi": 799, "label": "799점 이하"}, {"id": "cs_800_899", …}], "rule_versions": {…}}}`

### `POST /api/v1/funding/evaluate`
요청:
```json
{
  "profile": { "schema_version": 1, "...": "docs/21 §3 필드" },
  "as_of": "2026-11-20",
  "plans": ["need_cover", "max_limit"]
}
```
- `profile.owner.credit_score`는 `{"band_id": "cs_800_899"}` 또는 `null`. 정확한 점수 필드는 받지 않는다. 현재 구간 목록에 없는 ID는 `meta.warnings`에 `credit_band_stale` (docs/20 §3.2)
- 응답 `data` = docs/20 §1 `Evaluation` + `explanations`(완성 문장). `meta` = `{as_of, engine_version, dsl_version, rule_versions, rate_bases_as_of, warnings}`
- 서버는 요청 본문을 저장·로그하지 않는다

### `POST /api/v1/closure/evaluate`
`funding/evaluate`와 같은 형식. `plans` 기본 `["max_benefit", "certainty_first"]`.

## 3. 관리자 API (`/admin/v1`, 세션 쿠키 필요)

| Method | Path | 설명 |
|---|---|---|
| POST | `/login`, `/logout` | 세션 (로그인 실패 5회/10분 → 15분 잠금) |
| GET | `/queue?status=pending` | 검수 대기 `extraction_item` |
| GET | `/extraction-items/{id}` | 추출 결과 + 문서 텍스트·`line_index` + `auto_checks` |
| PATCH | `/extraction-items/{id}` | 본문 `{"json_patch": [RFC 6902 ops], "seconds_spent": 42}` → `review_log` 기록 |
| POST | `/extraction-items/{id}/approve` | `{"program_id", "valid_from", "valid_to"?}` → 승인 전 검증(docs/20 §11) → 새 규칙 버전 |
| POST | `/extraction-items/{id}/reject` | `{"reason"}` |
| POST | `/announcements/{id}/extract` | 재추출 |
| POST | `/documents/{id}/manual-text` | 변환 실패 문서 수동 텍스트 |
| GET | `/changes` · POST `/changes/{id}/resolve` | 변경 감지 처리 |
| POST | `/eval/run` | `{"split": "dev"|"test", "prompt_version"?}` → `eval_run` |
| GET | `/eval/runs` | 지표 이력 |
| GET | `/corrections` · POST `/corrections/{id}/resolve` | `{"action": "suppress_record"|"none", "note"}` → 숨김 시 웹 재생성 호출 |
| PUT | `/rate-bases` | `{"name": "policy_base_rate", "annual_pct": "3.00", "as_of": "2026-11-01", "source_url": "https://…"}` → `rate_base` 테이블 |
| POST | `/rules/{rule_id}/second-review` | `{"note", "seconds_spent"}` → `review_log(review_kind='second_review')`. 첫 승인 후 24시간 미만이면 409 |

`test` split 평가는 하루 1회로 제한하고 실행 기록을 남긴다(과적합 방지, docs/50 §5).
