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

- **요청 ID** (T-023, 2026-10-14 사용자 지시): 요청마다 **한 번** 만든다(ULID 26자). 같은 값을 성공·오류 응답의 `meta.request_id`, 응답 헤더 `X-Request-ID`, 그 요청에서 남기는 모든 로그(`request_id=…`), Sentry 이벤트 태그(T-082)에 쓴다. 사용자가 오류 화면의 ID를 알려 주면 그 값으로 로그를 찾는다. 클라이언트가 보낸 `X-Request-ID`는 쓰지 않는다(위조·충돌 방지)
- **접속 로그** (T-023): 요청마다 한 줄 `request_id=… method=… path=… status=… latency_ms=…`(로거 `app.access`). 경로는 쿼리스트링을 뺀 것이고 본문은 남기지 않는다(docs/01 §6)
- **`VALIDATION_ERROR`의 `details.fields`** (T-023): `{"<필드>": "<오류 종류>"}`. 필드는 요청 위치(`body`·`query`·`path`)를 뺀 경로를 `.`로 이은 것(`"message"`, `"items.0.code"`), 오류 종류는 Pydantic 오류 유형(`missing`, `string_too_long`, `extra_forbidden` 등) 또는 라우터가 정한 값(`invalid_format` 등). **입력값은 응답·로그에 되돌려 보내지 않는다**(FastAPI 기본 형식의 `input`을 쓰지 않는다 — 정정 요청 메시지에 연락처가 들어올 수 있다)
- **`INTERNAL`** (T-023): 처리되지 않은 예외는 `"일시적인 문제가 생겼어요. 잠시 후 다시 시도해 주세요."`로 응답한다. 로그에는 요청 ID·경로·예외 종류 이름만 남긴다(예외 메시지에 요청 값이 들어 있을 수 있다). DB 엔진도 오류 메시지에 SQL 인자를 넣지 않게 설정한다(`hide_parameters`)

**CORS** (T-032, 2026-10-19): 웹은 브라우저에서 공개 API를 바로 부른다(주소 검색·좌표 결과). 환경 변수 `CORS_ALLOWED_ORIGINS`(쉼표로 구분한 출처 목록, 예 `http://localhost:3000`)에 적힌 출처만 허용한다. 값이 없으면 어느 출처도 허용하지 않는다(기본값으로 `*`를 쓰지 않는다). 허용 메서드는 브라우저가 부르는 `GET`과 정정 요청(`POST /places/{pnu}/corrections`, T-033 정정 요청 시트)의 `POST`이고, 허용 요청 헤더는 JSON 본문용 `Content-Type`뿐이다(T-033, 2026-10-19). 자격 증명(쿠키)은 허용하지 않는다. 운영 도메인 등록은 T-081

**호출 제한(IP 기준)**: 조회 120회/분(주소 검색 포함), 평가(`*/evaluate`) 20회/분, 정정 요청 5회/시간.
**압축**: 요청에 `Accept-Encoding: gzip`이 있고 응답 본문이 1,000바이트 이상이면 gzip으로 압축한다(T-022). 큰 목록(층 이력 `history`, 층 미상 기록 `history_without_floor`)을 자르지 않고 전부 내보내는 대신 압축한다.
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
  "has_history": true,
  "related_pnus": ["1121510700100040001", "1121510700100040003"],
  "related_with_history": [{"pnu": "1121510700100040001", "jibun_label": "서울특별시 광진구 화양동 4-1"}]
}], "page": 1, "total": 3}}
```
`has_history`: `parcel` 테이블 존재 여부.

- `related_pnus`(T-022, 2026-10-14): 같은 건물의 관련지번(대표 지번이 아닌 다른 필지) PNU 목록. 검색 호출에 `addInfoYn=Y`를 켜서 **같은 한 번의 호출**로 받은 `relJibun`에서 만든다. 새 호출·새 API는 없다
  - `relJibun`은 법정동 **이름**만 준다(`서울특별시 광진구 자양동 225-79,화양동 4-1,4-3`). 이름이 바뀔 때만 적혀 있어 앞 항목의 이름을 이어 쓰고, 이름 낱말이 시도로 시작하지 않으면 앞 이름의 끝 낱말을 그만큼 바꾼다(`화양동` → `서울특별시 광진구 화양동`). 그 이름으로 `legal_dong.full_name`을 찾아 코드를 정한다(docs/10 §2.1과 같은 조회: 현행 코드 하나 → 그 코드, 현행이 없고 폐지 코드 하나 → 그 코드, 그 밖에는 찾지 못함)
  - 코드를 찾지 못하거나 읽을 수 없는 항목은 뺀다(기본값으로 채우지 않는다, ADR-003). 대표 지번의 PNU와 같은 값과 중복은 빼고, `relJibun`에 나온 순서를 지킨다
  - `relJibun`이 없거나 형식이 달라도 검색은 실패시키지 않고 빈 목록이다(가이드: 추가 항목은 "추후 특정항목이 제거되거나 추가될 수 있다"). `pnu`가 `null`인 항목도 `related_pnus`는 따로 만든다
  - `related_with_history`(T-033, 2026-10-19): `related_pnus` 중 `parcel`에 있는(식품 업소 기록이 있는) 필지만 `{pnu, jibun_label}`로, `related_pnus`의 순서대로. `jibun_label`은 `parcel.jibun_label`(필지 응답과 같은 값). `related_pnus`가 `[]`이면 `[]`, `null`이면 `null`. `has_history`와 같은 조회 한 번(`parcel`)으로 만들고 캐시하지 않는다. 필지 페이지의 "같은 건물의 다른 필지 기록"(docs/40 §4.3)이 쓴다

- 한 페이지 최대 10건(docs/40 §4.2). `total`은 도로명주소 API가 알려준 전체 건수
- 응답 필드로 PNU를 만들 수 없는 항목(법정동코드·산 여부·본번·부번 중 하나라도 없거나 형식이 다름)은 `pnu`와 `has_history`가 둘 다 `null`이다. 기본값으로 채우지 않는다(ADR-003)
- 검색어 정제: 도로명주소 API가 차단하는 특수문자(`% = < > [ ] ' " + ;`)와 SQL 예약어(낱말 단위)를 지우고 공백을 하나로 줄인 뒤 보낸다(`data/README.md` "도로명주소 검색 API 이용 조건"). 정제한 뒤 2자 미만이면 422
- 오류: 검색어가 짧거나 도로명주소 API가 검색어를 받지 않으면(시도명만 입력 등) 422 `VALIDATION_ERROR`(`details.fields.q`에 `too_short` 또는 도로명주소 API 오류코드), `page`가 1 미만이면 422(`details.fields.page`), 호출 제한 429, 도로명주소 API 실패·승인키 없음 502 `UPSTREAM_UNAVAILABLE`, `parcel`·`legal_dong` 조회 실패 503
- 캐시: 정제한 검색어와 페이지가 같으면 24시간 동안 도로명주소 API를 다시 부르지 않는다. 캐시에는 검색어 → 도로명주소 API 결과만 있다(요청한 사람에 관한 값 없음, 프로세스 메모리). `has_history`는 캐시하지 않고 매번 조회한다
- **검색어는 로그에 남기지 않는다.** 접속 로그는 쿼리스트링을 지운 경로만 쓴다
- `meta`에는 `request_id`만 있다(`data_as_of` 없음 — 이 응답의 주소는 도로명주소 API의 현재 값이다)

### `GET /api/v1/address/reverse?lat={위도}&lng={경도}`
좌표 → 그 지점의 필지와 주소 (T-032). "현재 위치로 찾기"와 "지도에서 고르기"(docs/40 §4.2)가 같이 쓴다.
```json
{"data": {
  "pnu": "1121510700100010000",
  "items": [{
    "road_addr": "서울특별시 광진구 능동로 120",
    "jibun_addr": "서울특별시 광진구 화양동 1",
    "building_name": "○○빌딩",
    "pnu": "1121510700100010000",
    "has_history": true,
    "related_pnus": ["1121510700100040001"]
  }]
}, "meta": {"request_id": "01J…"}}
```
항목은 주소 검색과 같은 `AddressItem`이다.

1. 카카오 `coord2regioncode`의 `region_type` `B`(법정동) 문서의 `code`(10자리)와, `coord2address`의 지번 주소 `mountain_yn`(산 여부)·`main_address_no`(본번)·`sub_address_no`(부번, 빈 문자열이면 0)로 PNU를 만든다(docs/10 §2.1과 같은 19자리). 이름으로 법정동을 찾지 않는다
2. 그 주소(도로명 주소가 있으면 도로명, 없으면 지번 주소 문자열)로 도로명주소 검색(§2 `address/search`와 같은 호출, 첫 페이지)을 한 번 더 부르고, **결과 중 `pnu`가 1의 PNU와 같은 항목만** 남긴다. "어느 것을 고를지" 규칙은 두지 않는다. 남은 항목의 `related_pnus`·`has_history`는 주소 검색과 같은 방법으로 만든다
3. 같은 항목이 여럿이면(한 필지에 건물 여러 개) 모두 돌려주고 사용자가 고른다
4. 같은 항목이 없거나 도로명주소 검색이 실패하면 카카오 응답으로 1건을 만든다: `road_addr`는 카카오 도로명 주소(없으면 `null` — "도로명 주소는 좌표에 따라 반환되지 않을 수 있습니다"), `jibun_addr`는 카카오 지번 주소, `building_name`은 카카오 건물명(없으면 `null`), **`related_pnus`·`related_with_history`는 `null`**(같은 건물의 다른 필지를 확인하지 못함 — 빈 목록 `[]`은 "확인했고 없음"이라 쓰지 않는다, ADR-003)
5. 법정동코드나 지번을 얻지 못하면(도로·하천·바다 등) `pnu`가 `null`이고 `items`는 빈 목록이다(UNKNOWN). 추측해서 채우지 않는다

- `AddressItem`의 `road_addr`와 `related_pnus`·`related_with_history`는 `null`일 수 있다(2026-10-19). **주소 검색(`address/search`)은 모두 항상 값을 준다** — `null`은 이 API의 4번 경우에만 나온다
- 오류: `lat`·`lng`가 없거나 숫자가 아니거나 범위(위도 −90~90, 경도 −180~180) 밖이면 422 `VALIDATION_ERROR`(`details.fields`), 호출 제한 429(조회 API 한도를 같이 쓴다), 카카오 실패·REST 키 없음 502 `UPSTREAM_UNAVAILABLE`, `parcel`·`legal_dong` 조회 실패 503
- **캐시하지 않는다.** 카카오 응답(가공한 값 포함)은 요청을 처리하는 동안 한 번만 쓰고 저장·캐시·로그하지 않는다(`data/README.md` "카카오 지도·로컬 API 이용 조건"). 2번의 도로명주소 검색도 이 경로에서는 캐시를 읽지도 쓰지도 않는다(검색어가 카카오 응답에서 나온다)
- **좌표는 로그에 남기지 않는다**(ADR-014). 접속 로그는 쿼리스트링을 지운 경로만 쓰고, 로그에는 실패 종류만 쓴다
- `meta`에는 `request_id`만 있다

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
    "ho_list": [], "bulk_closure": false, "bulk_closure_detail": null
  }]
}, "meta": {"request_id": "01J…", "data_as_of": "2026-11-01"}}
```
- 오류: PNU가 19자리 숫자가 아니면 422 `VALIDATION_ERROR`(`details.fields.pnu`), `parcel`에 없으면 404 `NO_HISTORY`, DB 실패 503
- `jibun_label`·`road_addr`·`location`은 `parcel`(docs/10 §7.1 빌드). `location`은 좌표가 없으면 `null`
- `floors`: `parcel.floors` 순서(B2, B1, 1, 2, …, RF)의 층마다 `floor_summary`의 `record_count`·`open_now_count`
- `meta.data_as_of`: 이력 기준일 = `validated` 스냅샷의 `source_updated_max` 중 가장 이른 날짜(Asia/Seoul) — `jobs.build_history`의 기본 기준일과 같다. 진행 일수 `tenure_days`도 이 날짜로 센다
- `records_without_floor`: 층 정보가 없어 층 이력에 포함되지 않은 기록 수
- `history_without_floor`: 그 기록들의 목록(T-018에서 결정, 2026-10-13). `opened_on` 오름차순, 항목은 층 이력의 `history`와 같되 `stale_suspect`는 없다(층키가 있어야 판정한다). 숨김 기록(`record_suppression`)과 `no_fixed_place` 기록은 뺀다. 기준율(`base_rate`)·`notices`는 주지 않는다. `len(history_without_floor) = records_without_floor`
  - **응답 크기 제한은 두지 않는다**(T-022에서 결정, 2026-10-14). 층 이력 `history`도 같은 원칙으로 전부 내보낸다. 큰 응답은 압축하고(§1), 화면은 처음 일부만 그리고 나머지는 "전체 보기"로 그린다(데이터는 다 받는다, T-033)
  - 측정(2026-10 데이터): 층 미상 기록이 있는 필지 115,086곳, 필지당 99번째 백분위 16건, 최대 617건. 50건 넘는 필지 113곳, 100건 넘는 29곳, 200건 넘는 6곳. 압축 전후 크기는 아래 "응답 크기"
  - **응답 크기**(2026-10-14 측정, 개발 DB 2026-10 데이터, gzip은 서버 압축 그대로 전송된 바이트):

    | 응답 | 항목 수 | 압축 전 | gzip |
    |---|---|---|---|
    | 가장 큰 층 이력 (`/places/{pnu}/floors/{floor}`) | `history` 2,370건 | 670,545바이트 (약 655KB) | 55,295바이트 (약 54KB) |
    | 가장 큰 층 미상 목록 (`/places/{pnu}`) | `history_without_floor` 617건 | 166,492바이트 (약 163KB) | 16,303바이트 (약 16KB) |

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
    "ho_list": ["101"], "bulk_closure": true, "stale_suspect": false,
    "bulk_closure_detail": {"jurisdiction_label": "광진구", "closure_count": 412}
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
- 오류: PNU 형식 422(`details.fields.pnu`), 층 형식(`B1`~`B9`, `1`~`99`, `RF`)이 아니면 422(`details.fields.floor`), 필지 또는 그 층의 `floor_summary`가 없으면 404 `NO_HISTORY`, DB 실패 503. `meta.data_as_of`는 필지 응답과 같다
- `summary`: `floor_summary`(docs/10 §7.1)
- `history`: 층 이력(docs/10 §7.1). 응답 크기 제한 없음(위 필지 응답과 같은 원칙). 한 층키의 기록은 최대 2,370건이다(2026-10 데이터)
- `bulk_closure_detail`(T-022, 2026-10-14): `bulk_closure = true`인 기록에 `closure_surge_day`의 그날(관할 = 기록의 `jurisdiction_code`, 날짜 = `closed_on`) `jurisdiction_label`·`closure_count`. 화면 배지 설명 "이날 {관할 이름}에서 … 처리됐어요({n}건)"(docs/40 §4.4)에 쓴다. `bulk_closure = false`이면 `null`. 관할 이름을 정할 수 없었으면(`jurisdiction_label`이 NULL) `jurisdiction_label: null`이고 건수는 그대로 준다. 필지 응답의 `history_without_floor`에도 같은 필드가 있다
- `ho_groups`: 이 층 이력에서 `ho_list`의 같은 원소를 가진 기록이 2건 이상인 호마다 1개, `record_ids`는 이력 순서. `ho` 문자열 오름차순
- `base_rate`: 기준율 모형 카드가 아직 계산되지 않았으면(`method_version='w0'`이 아닌 `model_card`가 없으면) `null`. 쓰는 카드는 그런 카드 중 가장 최근 것(`id` 최대)이고, `base_rate` 행은 그 카드와 같은 `snapshot_label`·`method_version`이다
  - `prior_closures_now`: 이 층의 현재 과거 폐업 횟수(docs/10 §7.2 "화면의 이 층의 현재 과거 폐업 횟수": `F`에서 급증일 폐업과 숨김 기록(`record_suppression`)을 뺀 폐업 수 — 화면 이력과 같은 기록만 센다), `bucket`은 그 버킷(`0`~`3`, `4+`). `display`와 상관없이 준다
  - 기준율 선택(`display=true`): `primary` = 같은 규모·같은 버킷의 시군구(PNU 앞 5자리) 행이 `n ≥ 200`이면 그 행, 아니면 서울(`11`) 행. `secondary` = `primary`가 시군구일 때만 서울 행, 아니면 `null`. `baseline` = `primary`와 같은 범위의 같은 규모 `0` 버킷 행이 `n ≥ 200`이면 그 행, 아니면 서울 `0` 버킷 행
  - `snapshot_label`·`method_version`: 쓴 카드의 값. `display=false`여도 준다
- `floor_scale`: 이 층의 규모 `single`(동시에 영업한 최대 점포 수 1) / `small`(2~9) / `large`(10 이상). `summary.max_concurrent`로 정한다(docs/10 §7.2). `primary`·`baseline`·`secondary`는 **이 규모의 기준율**(`base_rate.floor_scale`)이다 (T-019b, 응답 구현은 T-022)
- `display=false`이면 `hidden_reason`은 둘 중 하나다. 이때 `primary`·`baseline`·`secondary`는 `null`
  - `"not_confirmed_for_floor_scale"`: 이 규모에서 결론 유지 판정 (a)(b)가 깨졌다(최신 `model_card.payload.by_floor_scale.{규모}.holds = false`, docs/10 §7.3). 화면 문구는 docs/40 §4.4. 규모로 나누지 않은 값으로 대신하지 않는다. 이 값이 먼저다
  - `"insufficient_sample"`: 이 규모의 해당 버킷 n < 200(시군구·서울 모두). 행이 없는 경우도 여기에 든다
- `notices` 값과 발생 조건: docs/10 §7.1
- `stale_suspect`는 같은 호 근거만이다. 면적 근거 `stale_area_match`는 응답에 넣지 않는다 (docs/10 §6)
- 숨김 처리된 기록(`record_suppression`)은 응답에서 제외
- 응답에 전화번호 등 개인정보 필드 없음

### `POST /api/v1/places/{pnu}/corrections`
요청 `{"floor": "1", "record_id": 1032, "kind": "wrong_info", "message": "…"}` → 201 `{"data": {"id": 55}, "meta": {"request_id": "01J…"}}`. 연락처 필드 없음.
- `kind`: `wrong_info` | `remove_request` | `other`. `message`: 1~1,000자(필수). `floor`(층 형식, docs/10 §3)·`record_id`는 선택
- `record_id`를 주면 그 필지에서 이력에 보이는 기록이어야 한다(아니면 422 `details.fields.record_id = "not_in_place"`). `floor`도 주면 기록의 층과 같아야 한다(아니면 `details.fields.floor = "not_record_floor"`)
- 필지가 없으면 404 `NO_HISTORY`. 호출 제한 5회/시간(IP), `Cache-Control: no-store`
- **요청 본문은 로그에 남기지 않는다.** 자유 입력 `message`에 연락처 같은 개인정보가 들어올 수 있다. 처리 후 1년이 지나면 `message`를 지운다(docs/60 §5, docs/04)

### `GET /api/v1/stats/model-card`
방법론 페이지(docs/40 §4.9) 데이터. 모형 카드와 검색 일치율을 함께 준다(T-034, 2026-10-19 사용자 결정 — 화면이 한 번에 읽는다)
```json
{"data": {
  "method_version": "2026.10.1",
  "model_card": {"data": {"snapshot_label": "2026-10", "as_of": "2026-10-07"}, "base_rates": [], "logit": {}, "out_of_time": {}},
  "search_match": {
    "measured_on": "2026-10-14", "seed": 20261013, "remeasure": false,
    "population": 407816, "sample_size": 2000,
    "judged": {"matched": 1917, "rate": "0.9585", "ci": ["0.9488", "0.9664"]},
    "reference": {"matched": 1885, "rate": "0.9425", "ci": ["0.9314", "0.9519"]},
    "related_only": {"count": 32, "share": "0.0160"},
    "failures": [{"type": "jibun_changed", "count": 31, "share": "0.0155"}],
    "by_open_year": [{"band": "1999년 이전", "n": 170, "matched": 156, "rate": "0.9176", "ci": ["0.8665", "0.9503"], "reference_rate": "0.9000"}]
  }},
 "meta": {"request_id": "01J…"}}
```
- `model_card`: 최신 `model_card.payload`(docs/10 §7.3 형식 그대로). 고르는 카드는 `places/{pnu}/floors/{floor}`의 `base_rate`와 같다(`method_version='w0'`이 아닌 카드 중 `id` 최대). 없으면 `model_card`·`method_version`이 `null`
- `search_match`: 최신 `search_match_result.payload`(`id` 최대, docs/04). 없으면 `null`. 정의는 docs/50 §7
  - `judged` = 판정용 일치(대표 지번이 같거나 관련지번에 있다), `reference` = 참고용 일치(대표 지번만). `rate`·`ci`(Wilson 95%)는 소수 4자리 문자열
  - `related_only` = 관련지번으로만 일치한 건(`judged.matched − reference.matched`)
  - `failures` = 판정용으로 일치하지 않은 건의 유형별 건수(`keyword_error`·`transport_error`·`no_result`·`jibun_changed`·`other`, docs/50 §7 순서, 0건 포함)
  - `by_open_year` = 개업연도 구간별(`1999년 이전`·`2000~2009`·`2010~2015`·`2016~2020`·`2021년 이후`, 개업일 없는 기록이 있으면 `개업일 없음`). 표본이 없는 구간은 빠진다
  - 건별 결과(기록 키·주소)는 내보내지 않는다
- `Cache-Control: public, max-age=300`. DB 오류는 503 `SERVICE_UNAVAILABLE`

### `GET /api/v1/sitemap/sigungu`
웹 사이트맵 색인(docs/40 §9) 데이터. 사이트맵에 넣을 층 페이지 — `floor_summary.record_count ≥ 2`인 층 — 이 있는 시군구(PNU 앞 5자리)와 층 수(T-035, 2026-10-19 사용자 결정)
```json
{"data": {"sigungu": [{"code": "11215", "floor_count": 1234}]}, "meta": {"request_id": "01J…"}}
```
- `floor_summary.record_count`는 숨김 기록을 뺀 값이다(숨김 처리 때 그 필지의 요약을 다시 만든다, docs/10 §7.1). 그래서 숨긴 기록 때문에 2건이 되는 층은 들어가지 않는다
- `code` 오름차순. 층 페이지가 하나도 없는 시군구는 빠진다

### `GET /api/v1/sitemap/sigungu/{code}`
그 시군구의 사이트맵 층 페이지 목록. 조건은 위와 같다
```json
{"data": {"code": "11215", "floors": [{"pnu": "1121510700100470001", "floor": "1"}]}, "meta": {"request_id": "01J…"}}
```
- `code`: 숫자 5자리(아니면 422 `details.fields.code = "invalid_format"`). 해당 층이 없으면 빈 목록
- `pnu`, `floor` 문자열(바이트) 오름차순
- 두 API 모두 호출 제한은 조회와 같고(120회/분), `Cache-Control: public, max-age=300`. DB 오류는 503 `SERVICE_UNAVAILABLE`

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

**인증** (T-023, docs/01 §6)
- 계정은 API 서버에서 사람이 직접 실행하는 명령으로만 만든다: `python -m jobs.set_admin_password <사용자명>`(없으면 만들고, 있으면 비밀번호를 바꾼다). 비밀번호는 화면에 보이지 않는 입력으로 두 번 받고, 출력·로그·파일에 남기지 않는다. 비밀번호를 바꾸면 그 관리자의 세션을 전부 지운다. 환경 변수로 만드는 초기 계정은 없다
- `POST /login` `{"username", "password"}` → 200 `{"data": {"username", "expires_at"}}` + 쿠키 `gn_admin_session`(`HttpOnly; Secure; SameSite=Strict; Path=/admin/v1; Max-Age=28800`). 쿠키 값은 무작위 32바이트 토큰이고 DB(`admin_session`)에는 SHA-256 해시만 둔다. 세션은 **로그인 후 8시간** 또는 **마지막 요청 후 30분**이 지나면 만료
- 틀린 사용자명·비밀번호는 같은 401 `UNAUTHORIZED`. 첫 실패부터 10분 안에 5번 틀리면 15분 잠금 — 잠긴 동안은 맞는 비밀번호도 429 `RATE_LIMITED` + `Retry-After`. 실패 횟수·잠금은 DB(`admin_user`)에 둔다
- `POST /logout` → 204, 서버에서 세션을 지운다
- 세션 쿠키가 없거나 만료되면 401 `UNAUTHORIZED`
- **CSRF**: 상태를 바꾸는 요청(`POST`·`PATCH`·`PUT`·`DELETE`, `/login` 포함)은 헤더 `X-Admin-Request: 1`이 있어야 한다. 없으면 403 `FORBIDDEN`(쿠키 `SameSite=Strict`와 함께, 다른 사이트의 폼 전송은 이 헤더를 붙일 수 없다)


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

**정정 요청 처리** (T-023)
- `GET /corrections?status=open|resolved|rejected&limit=100` — 최근 접수 순. `status`를 빼면 전부, `limit` 1~500. 항목: `id, pnu, floor, record_id, kind, message, status, resolution_note, created_at, resolved_at, revalidated_at`. 목록을 읽기 전에 처리 후 1년이 지난 요청의 `message`를 지운다(`jobs.correction_maintenance`와 같은 함수)
- `POST /corrections/{id}/resolve` `{"action", "note"}`(`note` 1,000자 이하. `suppress_record`는 선택, `none`(→ `rejected`)은 거절 사유로 필수 — 비었거나 공백뿐이면 422 `{"fields": {"note": "note_required"}}`) → 200 `{"data": {"id", "status", "revalidated"}}`
  - `suppress_record` → `status='resolved'`, `record_suppression(record_id, reason=kind, request_id)`. 같은 트랜잭션에서 그 필지의 `parcel`·`floor_summary`를 월간 `jobs.build_history`와 **같은 빌드 함수로** 다시 만든다(docs/10 §7.1). 요청에 `record_id`가 없으면 422 `details.fields.action = "no_record"`. 이미 숨긴 기록이면 숨김은 그대로 두고 요청만 처리한다
  - `none` → `status='rejected'`. 숨기지 않고 재생성도 하지 않는다
  - `status`가 `open`이 아니면 409 `CONFLICT`
  - **웹 재생성은 커밋 뒤에** 호출한다: `WEB_REVALIDATE_URL`에 `POST`, 헤더 `x-revalidate-secret: REVALIDATE_SECRET`, 본문 `{"paths": ["/place/{pnu}", "/place/{pnu}/{floor}"]}`(숨긴 기록에 층이 없으면 첫 경로만). 실패(연결 오류·2xx 아님)하면 최대 3번까지 시도하고, 그래도 실패하면 `revalidated: false`로 응답하고 경고 로그(요청 id·실패 종류)를 남긴다. `revalidated_at`이 비어 있는 숨김 처리 요청은 `jobs.correction_maintenance`가 다시 호출한다. 재생성이 실패해도 숨김 처리는 취소하지 않는다(웹 페이지는 ISR 1일 안에 갱신된다)

