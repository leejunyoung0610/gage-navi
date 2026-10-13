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

**호출 제한(IP 기준)**: 조회 120회/분(주소 검색 포함), 평가(`*/evaluate`) 20회/분, 정정 요청 5회/시간.
**캐시**: 장소 조회 `Cache-Control: public, max-age=300` (API 앞에 CDN 없음) / 평가 `no-store`. 웹의 장소 페이지는 ISR(1일)이며, 관리자가 정정 요청으로 기록을 숨기면 API가 웹의 `POST /api/revalidate`(헤더 `x-revalidate-secret`)를 호출해 해당 `/place/{pnu}`·`/place/{pnu}/{floor}`를 즉시 재생성한다.

## 2. 공개 API

### `GET /api/v1/health`
`{"status": "ok", "db": "ok", "location_snapshot": "2026-11", "approved_rules": 14}`

- 공통 응답(§1)의 예외: 성공 응답을 `data`/`meta`로 감싸지 않는다 (모니터링 도구용). 오류는 §1 형식 그대로 503 `SERVICE_UNAVAILABLE`
- `location_snapshot`은 정규화까지 통과한(`validated`) 종류별 최신 스냅샷의 `source_updated_max` 중 가장 이른 값의 연-월(Asia/Seoul, `YYYY-MM`). 식품 3종 합산 통계의 기준일과 같은 날짜에서 나온다(T-019). `validated` 스냅샷이 하나도 없으면 `null`
- `location_snapshot`·`approved_rules`는 값을 알 수 없으면 `null`. 채우는 시점: `location_snapshot`은 T-016(`data_snapshot` 기록), `approved_rules`는 T-055(규칙 버전 배포). 그 전에는 항상 `null`

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

- 한 페이지 최대 10건(docs/40 §4.2). `total`은 도로명주소 API가 알려준 전체 건수
- 응답 필드로 PNU를 만들 수 없는 항목(법정동코드·산 여부·본번·부번 중 하나라도 없거나 형식이 다름)은 `pnu`와 `has_history`가 둘 다 `null`이다. 기본값으로 채우지 않는다(ADR-003)
- 검색어 정제: 도로명주소 API가 차단하는 특수문자(`% = < > [ ] ' " + ;`)와 SQL 예약어(낱말 단위)를 지우고 공백을 하나로 줄인 뒤 보낸다(`data/README.md` "도로명주소 검색 API 이용 조건"). 정제한 뒤 2자 미만이면 422
- 오류: 검색어가 짧거나 도로명주소 API가 검색어를 받지 않으면(시도명만 입력 등) 422 `VALIDATION_ERROR`(`details.fields.q`에 `too_short` 또는 도로명주소 API 오류코드), `page`가 1 미만이면 422(`details.fields.page`), 호출 제한 429, 도로명주소 API 실패·승인키 없음 502 `UPSTREAM_UNAVAILABLE`, `parcel` 조회 실패 503
- 캐시: 정제한 검색어와 페이지가 같으면 24시간 동안 도로명주소 API를 다시 부르지 않는다. 캐시에는 검색어 → 도로명주소 API 결과만 있다(요청한 사람에 관한 값 없음, 프로세스 메모리). `has_history`는 캐시하지 않고 매번 조회한다
- **검색어는 로그에 남기지 않는다.** 접속 로그는 쿼리스트링을 지운 경로만 쓴다
- `meta`에는 `request_id`만 있다(`data_as_of` 없음 — 이 응답의 주소는 도로명주소 API의 현재 값이다)

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
  "records_without_floor": 4,
  "history_without_floor": [{
    "record_id": 880, "name": "○○식당", "license_type": "general_restaurant", "biz_category": "한식",
    "opened_on": "1998-05-11", "closed_on": "2003-02-28", "status": "closed", "tenure_days": 1754,
    "ho_list": [], "bulk_closure": false
  }]
}}
```
- `records_without_floor`: 층 정보가 없어 층 이력에 포함되지 않은 기록 수
- `history_without_floor`: 그 기록들의 목록(T-018에서 결정, 2026-10-13). `opened_on` 오름차순, 항목은 층 이력의 `history`와 같되 `stale_suspect`는 없다(층키가 있어야 판정한다). 숨김 기록(`record_suppression`)과 `no_fixed_place` 기록은 뺀다. 기준율(`base_rate`)·`notices`는 주지 않는다. `len(history_without_floor) = records_without_floor`
  - 한 필지의 층 미상 기록은 99번째 백분위 16건, 최대 617건이다(2026-10 데이터). 응답 크기 제한이 필요한지는 T-022에서 정한다
- `floors`가 비어 있고 `records_without_floor > 0`인 필지도 정상 응답이다(층 정보가 하나도 없는 필지)

### `GET /api/v1/places/{pnu}/floors/{floor}`
```json
{"data": {
  "pnu": "1121510700100470001", "floor": "1", "jibun_label": "서울특별시 광진구 화양동 47-1",
  "summary": {"record_count": 7, "records_since_2005": 5, "open_now_count": 1,
              "median_closed_tenure_days": 812, "has_concurrent": false, "max_concurrent": 1},
  "history": [{
    "record_id": 1032, "name": "○○분식", "license_type": "general_restaurant", "biz_category": "분식",
    "opened_on": "2011-03-02", "closed_on": "2013-08-30", "status": "closed", "tenure_days": 912,
    "ho_list": ["101"], "bulk_closure": false, "stale_suspect": false
  }],
  "ho_groups": [{"ho": "101", "record_ids": [1032, 2210]}],
  "base_rate": {
    "display": true, "hidden_reason": null, "floor_scale": "single",
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
- `floor_scale`: 이 층의 규모 `single`(동시에 영업한 최대 점포 수 1) / `small`(2~9) / `large`(10 이상). `summary.max_concurrent`로 정한다(docs/10 §7.2). `primary`·`baseline`·`secondary`는 **이 규모의 기준율**(`base_rate.floor_scale`)이다 (T-019b, 응답 구현은 T-022)
- `display=false`이면 `hidden_reason`은 둘 중 하나다. 이때 `primary`·`baseline`·`secondary`는 `null`
  - `"not_confirmed_for_floor_scale"`: 이 규모에서 결론 유지 판정 (a)(b)가 깨졌다(최신 `model_card.payload.by_floor_scale.{규모}.holds = false`, docs/10 §7.3). 화면 문구는 docs/40 §4.4. 규모로 나누지 않은 값으로 대신하지 않는다. 이 값이 먼저다
  - `"insufficient_sample"`: 이 규모의 해당 버킷 n < 200(시군구·서울 모두)
- `notices` 값과 발생 조건: docs/10 §7.1
- `stale_suspect`는 같은 호 근거만이다. 면적 근거 `stale_area_match`는 응답에 넣지 않는다 (docs/10 §6)
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
`{"quote": "…", "loc": "p3:l12-14", "document": {"file_name": "….pdf"}, "announcement": {"title": "…", "url": "https://…"}, "checked_on": "2026-11-20"}`

`loc` 형식 (문서 형식별, ADR-024):

| 형식 | `loc` | 예 | 뜻 |
|---|---|---|---|
| PDF | `p{쪽}:l{줄}` | `p3:l12-14` | 3쪽의 12~14번째 줄. 쪽은 1부터 |
| HWP | `s{섹션}:l{줄}` | `s0:l120-123` | 섹션 0의 120~123번째 줄. HWP는 쪽 정보가 없어 본문 섹션(`BodyText/Section{n}`, 0부터)을 쓴다 |

줄 번호는 그 쪽·섹션 안에서 1부터 세고, 한 줄이면 `l12`, 범위면 `l12-14`.

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
