# 04. 데이터 모델 (PostgreSQL 16 + PostGIS)

> 마이그레이션은 Alembic으로만. §2 = `0001_location`(T-003) + `0003_normalize`(T-016: `license_record.no_fixed_place`, `closure_surge_day`) + `0004_stale_area`(T-017: `license_record.stale_area_match`) + `0005_prior_ex_surge`(T-018: `record_prior.prior_closures_floor_ex_surge`) + `0006_floor_scale`(T-019b: `floor_summary.max_concurrent`, `record_prior.max_concurrent_at_open`, `base_rate.floor_scale`), §3 = `0002_rules`(T-005). `0007_admin_auth`(T-023)는 §2 `correction_request.revalidated_at`과 §3 `admin_user` 잠금 컬럼·`admin_session`을 더한다. `0009_measure`(T-104)는 §2 `measure_daily_count`를 더한다. 아래 DDL은 기준 명세이며, 구현 시 이름·타입·제약을 그대로 따른다. 변경은 이 문서를 먼저 고친다.

## 1. 공통 규칙

- 시각은 `TIMESTAMPTZ`(UTC 저장, 표시는 Asia/Seoul). 날짜는 `DATE`.
- 금액은 `BIGINT`(원). 비율(0~1, `base_rate.rate` 등)은 `NUMERIC(6,4)`.
  - 예외: 유사도 점수 `evidence.similarity`는 `NUMERIC(4,3)`, 퍼센트 값 `rate_base.annual_pct`는 `NUMERIC(6,3)`.
- 상태값은 `TEXT + CHECK`(PostgreSQL ENUM 사용 안 함 — 마이그레이션 단순화).
- 모든 파생 테이블에 `method_version`(계산 로직 버전) 또는 `parse_version`을 둔다. 값 형식: `YYYY.MM.N` (예: `2026.10.1`).

## 2. 자리 이력 (`location`)

```sql
CREATE EXTENSION IF NOT EXISTS postgis;

-- 수집 단위(파일 또는 API 실행 1회)
CREATE TABLE data_snapshot (
  id                BIGSERIAL PRIMARY KEY,
  source            TEXT NOT NULL CHECK (source IN ('license_file','license_api')),
  license_type      TEXT NOT NULL CHECK (license_type IN ('general_restaurant','rest_restaurant','bakery')),
  fetched_at        TIMESTAMPTZ NOT NULL DEFAULT now(),
  source_updated_max TIMESTAMPTZ,            -- 원천 데이터갱신시점 최댓값
  row_count         INT NOT NULL,
  file_sha256       TEXT,
  validation        JSONB NOT NULL DEFAULT '{}'::jsonb,   -- docs/50 §2 검사 결과
  status            TEXT NOT NULL CHECK (status IN ('loaded','validated','failed'))
);

-- 원본 행 보관 (컬럼명 원문 그대로)
CREATE TABLE license_raw (
  id            BIGSERIAL PRIMARY KEY,
  snapshot_id   BIGINT NOT NULL REFERENCES data_snapshot(id) ON DELETE CASCADE,
  license_type  TEXT NOT NULL,
  mgmt_no       TEXT NOT NULL,
  payload       JSONB NOT NULL,
  UNIQUE (snapshot_id, license_type, mgmt_no)
);

-- 법정동코드 (폐지 코드 포함)
CREATE TABLE legal_dong (
  code        CHAR(10) PRIMARY KEY,
  sido        TEXT NOT NULL,
  sigungu     TEXT,
  eupmyeondong TEXT,
  ri          TEXT,
  full_name   TEXT NOT NULL,            -- '서울특별시 광진구 화양동'
  abolished   BOOLEAN NOT NULL DEFAULT false
);
CREATE INDEX legal_dong_full_name_idx ON legal_dong (full_name);

-- 정규화된 업소 기록 (license_type + mgmt_no 당 1행, 최신 상태)
CREATE TABLE license_record (
  id                BIGSERIAL PRIMARY KEY,
  license_type      TEXT NOT NULL CHECK (license_type IN ('general_restaurant','rest_restaurant','bakery')),
  mgmt_no           TEXT NOT NULL,
  jurisdiction_code TEXT NOT NULL,
  name              TEXT NOT NULL,
  biz_category      TEXT,
  status            TEXT NOT NULL CHECK (status IN ('open','closed','suspended','other')),
  status_raw        TEXT NOT NULL,
  opened_on         DATE,
  closed_on         DATE,
  area_m2           NUMERIC(10,2),
  jibun_addr        TEXT,
  road_addr         TEXT,
  pnu               CHAR(19),            -- 파싱 실패 시 NULL
  sigungu_code      CHAR(5),             -- 법정동코드 앞 5자리
  floor             TEXT,                -- '1','2',…,'B1','B2' / 파싱 실패 NULL
  floor_source      TEXT CHECK (floor_source IN ('jibun_tail','road_detail')),
  ho_list           TEXT[] NOT NULL DEFAULT '{}',
  geom              GEOMETRY(Point, 4326),
  bulk_closure      BOOLEAN NOT NULL DEFAULT false,   -- ADR-020. 그날의 관할 이름·건수는 closure_surge_day
  stale_suspect     BOOLEAN NOT NULL DEFAULT false,   -- ADR-023. 근거: 같은 호 (docs/10 §6). 화면 배지에 쓴다
  stale_area_match  BOOLEAN NOT NULL DEFAULT false,   -- ADR-023. 근거: 같은 면적 ±1%. 통계 민감도 분석에만 쓴다
  no_fixed_place    BOOLEAN NOT NULL DEFAULT false,   -- 고정된 자리가 없는 업태(docs/10 §1.1). 자리 이력·통계에서 제외
  source_updated_at TIMESTAMPTZ,
  last_snapshot_id  BIGINT REFERENCES data_snapshot(id),
  parse_version     TEXT NOT NULL,
  UNIQUE (license_type, mgmt_no),
  CHECK (closed_on IS NULL OR opened_on IS NULL OR closed_on >= opened_on)
);
CREATE INDEX license_record_floor_idx ON license_record (pnu, floor);
CREATE INDEX license_record_geom_idx  ON license_record USING GIST (geom);
CREATE INDEX license_record_closed_idx ON license_record (jurisdiction_code, closed_on) WHERE status = 'closed';

-- 폐업 처리 급증일 (docs/10 §5, ADR-020). 정규화할 때마다 전체를 다시 만든다
CREATE TABLE closure_surge_day (
  jurisdiction_code  TEXT NOT NULL,
  closed_on          DATE NOT NULL,
  jurisdiction_label TEXT,               -- '마포구'. 그 관할 기록의 주소에 가장 많이 나온 시군구 이름, 정할 수 없으면 NULL
  closure_count      INT NOT NULL,       -- c(j, d): 그날 그 관할의 폐업 건수 (식품 3종 합산)
  median_daily       NUMERIC(8,1) NOT NULL,  -- m(j): 관할의 하루 폐업 건수 중앙값
  parse_version      TEXT NOT NULL,
  PRIMARY KEY (jurisdiction_code, closed_on)
);

-- 필지(PNU) 요약 — 자리 페이지 1단계
CREATE TABLE parcel (
  pnu             CHAR(19) PRIMARY KEY,
  legal_dong_code CHAR(10) NOT NULL REFERENCES legal_dong(code),
  jibun_label     TEXT NOT NULL,         -- '서울특별시 광진구 화양동 47-1'
  road_addr       TEXT,                  -- 가장 최근에 개업한 기록의 도로명주소(상세 제외). 없으면 그 앞 기록
  geom            GEOMETRY(Point, 4326), -- 좌표가 있는 기록 중 가장 최근에 개업한 기록의 좌표
  floors          TEXT[] NOT NULL,       -- 이력이 있는 층, 정렬: B2,B1,1,2,…
  record_count    INT NOT NULL,          -- 이력에 보이는 기록 수 (층 정보 없는 기록 포함, docs/10 §7.1의 제외 적용)
  updated_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- 층키 요약
CREATE TABLE floor_summary (
  pnu               CHAR(19) NOT NULL REFERENCES parcel(pnu),
  floor             TEXT NOT NULL,
  record_count      INT NOT NULL,
  records_since_2005 INT NOT NULL,
  open_now_count    INT NOT NULL,
  median_closed_tenure_days INT,          -- 폐업 업소 영업기간 중앙값 (bulk 제외)
  has_concurrent    BOOLEAN NOT NULL,     -- 동시 영업 기록 존재 → "여러 점포" 안내
  max_concurrent    INT NOT NULL CHECK (max_concurrent >= 1),  -- 기준일까지 동시에 영업한 최대 점포 수 → 화면의 층 규모 (docs/10 §7.1·§7.2)
  method_version    TEXT NOT NULL,
  PRIMARY KEY (pnu, floor)
);

-- 기록별 과거 폐업 횟수 (층키 기준, docs/10 §7.2). 급증일 폐업을 포함한 값과 뺀 값을 둘 다 둔다
CREATE TABLE record_prior (
  record_id             BIGINT PRIMARY KEY REFERENCES license_record(id) ON DELETE CASCADE,
  prior_closures_floor  INT NOT NULL,          -- 같은 층키에서 개업일 전에 폐업한 기록 수 (급증일 폐업 포함)
  prior_closures_floor_ex_surge INT NOT NULL,  -- 그중 bulk_closure = true인 폐업을 뺀 수
  max_concurrent_at_open INT NOT NULL CHECK (max_concurrent_at_open >= 1),  -- 개업일까지의 이력으로 센 동시 영업 최대 점포 수 → 통계의 층 규모 (docs/10 §7.2)
  method_version        TEXT NOT NULL,
  computed_at           TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- 기준율 (월 1회 계산, 화면에서 읽기 전용)
CREATE TABLE base_rate (
  id             BIGSERIAL PRIMARY KEY,
  snapshot_label TEXT NOT NULL,            -- '2026-11'
  method_version TEXT NOT NULL,
  scope_code     TEXT NOT NULL,            -- '11'(서울 전체) 또는 시군구 5자리
  license_group  TEXT NOT NULL DEFAULT 'food3',   -- MVP: 식품 3종 통합. 'general_restaurant' 등 개별은 n 충족 시
  floor_scale    TEXT NOT NULL DEFAULT 'all' CHECK (floor_scale IN ('all','single','small','large')),  -- 층 규모 (docs/10 §7.2). 'all' = 규모로 나누지 않은 값. 판정이 깨진 규모의 행은 없다 (docs/10 §7.3)
  prior_bucket   TEXT NOT NULL CHECK (prior_bucket IN ('0','1','2','3','4+')),
  n              INT NOT NULL,
  events         INT NOT NULL,             -- 3년 내 폐업 수
  rate           NUMERIC(6,4) NOT NULL,
  ci_low         NUMERIC(6,4) NOT NULL,    -- Wilson 95%
  ci_high        NUMERIC(6,4) NOT NULL,
  cohort_from    DATE NOT NULL,
  cohort_to      DATE NOT NULL,
  created_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
  UNIQUE (snapshot_label, method_version, scope_code, license_group, floor_scale, prior_bucket)
);

-- 모형 카드 (방법론 페이지 데이터)
CREATE TABLE model_card (
  id             BIGSERIAL PRIMARY KEY,
  snapshot_label TEXT NOT NULL,
  method_version TEXT NOT NULL,
  payload        JSONB NOT NULL,           -- docs/10 §7.3 형식
  created_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
  UNIQUE (snapshot_label, method_version)
);

-- 검색 일치율 측정 결과 (방법론 페이지 데이터, T-034. 마이그레이션 0008_search_match)
-- `jobs.render_search_match --save`가 건별 결과 파일(docs/50 §7)을 집계해 seed마다 1행을 쓴다(API 호출 없음).
-- 화면은 `id`가 가장 큰 행을 쓴다(docs/30 `/stats/model-card`). 건별 결과(기록 키·주소)는 저장하지 않는다
CREATE TABLE search_match_result (
  id          BIGSERIAL PRIMARY KEY,
  seed        INT NOT NULL UNIQUE,      -- 20261013(첫 측정) 또는 20261014(재측정)
  measured_on DATE NOT NULL,
  payload     JSONB NOT NULL,           -- docs/30 `/stats/model-card`의 `search_match` 형식
  created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- 방문 측정·"도움이 됐나요" 일별 합계 (T-104, ADR-027, docs/30 `POST /measure/events`, docs/70 §5. 마이그레이션 0009_measure)
-- 이벤트 한 건씩 저장하지 않고 (날짜, 이벤트)마다 합계만 둔다. 식별자·IP·User-Agent·주소·필지 열이 없고,
-- 마지막 이벤트 시각이 남지 않도록 시각 열(created_at·updated_at)도 두지 않는다
CREATE TABLE measure_daily_count (
  day    DATE NOT NULL,             -- 한국 시간 날짜. `revisit_7d`는 첫 방문 날짜
  event  TEXT NOT NULL CHECK (event IN ('first_visit','revisit_7d','helpful_yes','helpful_no')),
  count  INT NOT NULL CHECK (count >= 0),
  PRIMARY KEY (day, event)
);

-- 정정·삭제 요청 (연락처 필드 없음. 자유 입력 `message`에 연락처가 들어올 수 있어 로그에 남기지 않고,
-- 처리(`resolved_at`) 후 1년이 지나면 `message`를 빈 문자열로 지운다 — 행·처리 결과는 처리 기록으로 남긴다, docs/60 §3·§5)
CREATE TABLE correction_request (
  id          BIGSERIAL PRIMARY KEY,
  pnu         CHAR(19) NOT NULL,
  floor       TEXT,
  record_id   BIGINT REFERENCES license_record(id),
  kind        TEXT NOT NULL CHECK (kind IN ('wrong_info','remove_request','other')),
  message     TEXT NOT NULL CHECK (char_length(message) <= 1000),
  status      TEXT NOT NULL DEFAULT 'open' CHECK (status IN ('open','resolved','rejected')),
  resolution_note TEXT,            -- rejected면 거절 사유(필수, API에서 검사). 1년 뒤에도 남긴다
  created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
  resolved_at TIMESTAMPTZ,
  revalidated_at TIMESTAMPTZ               -- 숨김 처리 뒤 웹 재생성 호출이 성공한 시각 (T-023). NULL이면 재시도 대상
);

-- 숨김 처리 (정정 요청 승인 결과)
CREATE TABLE record_suppression (
  record_id   BIGINT PRIMARY KEY REFERENCES license_record(id),
  reason      TEXT NOT NULL,
  request_id  BIGINT REFERENCES correction_request(id),
  created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);
```

## 3. 규칙 (`rules`, `funding`, `closure`)

> 마이그레이션 `0002_rules`(T-005). `admin_user`도 여기 포함.

```sql
CREATE TABLE source_site (
  id          BIGSERIAL PRIMARY KEY,
  name        TEXT NOT NULL,
  kind        TEXT NOT NULL CHECK (kind IN ('api','page')),
  url         TEXT NOT NULL,
  active      BOOLEAN NOT NULL DEFAULT true
);

CREATE TABLE announcement (
  id            BIGSERIAL PRIMARY KEY,
  source_site_id BIGINT NOT NULL REFERENCES source_site(id),
  external_id   TEXT NOT NULL,
  version       INT NOT NULL DEFAULT 1,
  title         TEXT NOT NULL,
  agency        TEXT,
  url           TEXT NOT NULL,
  published_on  DATE,
  content_hash  TEXT NOT NULL,
  fetched_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
  UNIQUE (source_site_id, external_id, version)
);

CREATE TABLE document (
  id             BIGSERIAL PRIMARY KEY,
  announcement_id BIGINT NOT NULL REFERENCES announcement(id),
  file_name      TEXT NOT NULL,
  format         TEXT NOT NULL CHECK (format IN ('hwp','hwpx','pdf','html')),
  storage_path   TEXT NOT NULL,
  file_sha256    TEXT NOT NULL,
  text           TEXT,                     -- 변환 결과
  line_index     JSONB,                    -- [{line_no, page, section, start_char, end_char}] PDF는 page(1부터), HWP는 section(0부터). 해당 없는 쪽은 null. line_no는 그 쪽·섹션 안에서 1부터
  converter      TEXT,                     -- 'hwpx-xml@1' 등
  converted_at   TIMESTAMPTZ,
  convert_status TEXT NOT NULL DEFAULT 'pending' CHECK (convert_status IN ('pending','ok','failed','manual'))
);

CREATE TABLE program (
  id          TEXT PRIMARY KEY,            -- 'sbiz.general_stability' 처럼 연도 없는 안정 키
  module      TEXT NOT NULL CHECK (module IN ('funding','closure')),
  name        TEXT NOT NULL,
  agency      TEXT NOT NULL,
  level       TEXT NOT NULL CHECK (level IN ('national','local')),
  region_code TEXT,                        -- '11' 서울 / NULL 전국
  tags        TEXT[] NOT NULL DEFAULT '{}',
  official_url TEXT,
  active      BOOLEAN NOT NULL DEFAULT true
);

CREATE TABLE extraction (
  id              BIGSERIAL PRIMARY KEY,
  announcement_id BIGINT NOT NULL REFERENCES announcement(id),
  model           TEXT NOT NULL,
  prompt_version  TEXT NOT NULL,
  dsl_version     TEXT NOT NULL,
  auto_checks     JSONB NOT NULL DEFAULT '{}'::jsonb,
  status          TEXT NOT NULL DEFAULT 'pending' CHECK (status IN ('pending','reviewed')),
  created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE extraction_item (
  id                  BIGSERIAL PRIMARY KEY,
  extraction_id       BIGINT NOT NULL REFERENCES extraction(id) ON DELETE CASCADE,
  program_id          TEXT REFERENCES program(id),   -- 검수 시 연결
  proposed_program_key TEXT NOT NULL,
  output              JSONB NOT NULL,                -- 규칙 DSL 초안
  needs_review_fields TEXT[] NOT NULL DEFAULT '{}',
  status              TEXT NOT NULL DEFAULT 'pending' CHECK (status IN ('pending','approved','rejected')),
  reviewed_at         TIMESTAMPTZ
);

CREATE TABLE rule (
  id                 BIGSERIAL PRIMARY KEY,
  program_id         TEXT NOT NULL REFERENCES program(id),
  version            INT NOT NULL,
  dsl_version        TEXT NOT NULL,
  body               JSONB NOT NULL,                 -- docs/20 §2 스키마, 서버에서 Pydantic 검증 후 저장
  status             TEXT NOT NULL CHECK (status IN ('draft','approved','retired')),
  approved_by        TEXT,
  approved_at        TIMESTAMPTZ,
  valid_from         DATE,
  valid_to           DATE,
  extraction_item_id BIGINT REFERENCES extraction_item(id),
  UNIQUE (program_id, version),
  CHECK (status <> 'approved' OR (approved_by IS NOT NULL AND approved_at IS NOT NULL))
);
-- 한 프로그램에 approved 규칙은 동시에 1개
CREATE UNIQUE INDEX rule_one_approved ON rule (program_id) WHERE status = 'approved';

CREATE TABLE evidence (
  id          BIGSERIAL PRIMARY KEY,
  rule_id     BIGINT NOT NULL REFERENCES rule(id) ON DELETE CASCADE,
  ev_key      TEXT NOT NULL,              -- 'E1'
  document_id BIGINT NOT NULL REFERENCES document(id),
  quote       TEXT NOT NULL CHECK (char_length(quote) <= 500),
  loc         TEXT NOT NULL,              -- PDF 'p3:l12-14', HWP 's0:l120-123' (형식: docs/30 §2 evidence)
  similarity  NUMERIC(4,3) NOT NULL CHECK (similarity BETWEEN 0 AND 1),  -- 원문 대조 점수 0~1 (docs/20 §10.4)
  UNIQUE (rule_id, ev_key)
);

CREATE TABLE change_event (
  id              BIGSERIAL PRIMARY KEY,
  announcement_id BIGINT NOT NULL REFERENCES announcement(id),
  target          TEXT NOT NULL CHECK (target IN ('page','attachment')),
  prev_hash       TEXT,
  new_hash        TEXT NOT NULL,
  diff            TEXT,
  detected_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
  review_status   TEXT NOT NULL DEFAULT 'open' CHECK (review_status IN ('open','done'))
);

CREATE TABLE review_log (
  id                 BIGSERIAL PRIMARY KEY,
  review_kind        TEXT NOT NULL CHECK (review_kind IN ('field_edit','approve','reject','second_review')),
  extraction_item_id BIGINT REFERENCES extraction_item(id),
  rule_id            BIGINT REFERENCES rule(id),
  field_path         TEXT,                -- JSON Pointer (field_edit일 때 필수)
  before             JSONB,
  after              JSONB,
  note               TEXT,                -- second_review: "원문 대조 이상 없음" 또는 발견 사항
  reviewer           TEXT NOT NULL,
  seconds_spent      INT NOT NULL,
  created_at         TIMESTAMPTZ NOT NULL DEFAULT now(),
  CHECK (review_kind <> 'field_edit' OR (extraction_item_id IS NOT NULL AND field_path IS NOT NULL)),
  CHECK (review_kind <> 'second_review' OR rule_id IS NOT NULL)
);

-- 변동금리 기준값 (관리자가 갱신, 엔진 입력 rate_bases)
CREATE TABLE rate_base (
  id          BIGSERIAL PRIMARY KEY,
  name        TEXT NOT NULL,               -- 'policy_base_rate' 등, 규칙 benefit.rate.base 값과 일치
  annual_pct  NUMERIC(6,3) NOT NULL,
  as_of       DATE NOT NULL,
  source_url  TEXT NOT NULL,
  updated_by  TEXT NOT NULL,
  created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
  UNIQUE (name, as_of)
);

CREATE TABLE eval_case (
  id              BIGSERIAL PRIMARY KEY,
  announcement_id BIGINT NOT NULL REFERENCES announcement(id),
  split           TEXT NOT NULL CHECK (split IN ('dev','test')),
  gold            JSONB NOT NULL,         -- 공고 1건 → 규칙 배열 (사람 라벨)
  labeled_by      TEXT NOT NULL,
  labeled_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
  relabel_of      BIGINT REFERENCES eval_case(id)    -- 일관성 측정용 재라벨
);

CREATE TABLE eval_run (
  id             BIGSERIAL PRIMARY KEY,
  prompt_version TEXT NOT NULL,
  model          TEXT NOT NULL,
  split          TEXT NOT NULL CHECK (split IN ('dev','test')),
  metrics        JSONB NOT NULL,          -- docs/50 §5 형식 (점추정 + 95% CI)
  created_at     TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE admin_user (
  id            BIGSERIAL PRIMARY KEY,
  username      TEXT NOT NULL UNIQUE,
  password_hash TEXT NOT NULL,              -- argon2id
  created_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
  -- 로그인 잠금 (T-023, docs/30 §3): 첫 실패부터 10분 안에 5회 실패하면 15분 잠금.
  -- 재시작·여러 워커에서도 유지되도록 DB에 둔다
  failed_login_count      INT NOT NULL DEFAULT 0,
  failed_login_started_at TIMESTAMPTZ,      -- 지금 세는 실패 창의 첫 실패 시각
  locked_until            TIMESTAMPTZ
);

-- 관리자 세션 (T-023). 쿠키에는 무작위 32바이트 토큰, DB에는 그 SHA-256 해시만 저장한다.
-- 로그인 후 8시간(`expires_at`) 또는 마지막 요청 후 30분이 지나면 만료. 로그아웃·비밀번호 변경 시 지운다
CREATE TABLE admin_session (
  token_hash    BYTEA PRIMARY KEY,
  admin_user_id BIGINT NOT NULL REFERENCES admin_user(id) ON DELETE CASCADE,
  created_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
  last_seen_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
  expires_at    TIMESTAMPTZ NOT NULL
);
CREATE INDEX ON admin_session (admin_user_id);
```

충돌·한도 그룹·순서 효과는 규칙 `body` 안에 저장한다(docs/20 §2). 엔진은 승인 규칙 로드 시 이를 모아 그래프를 만든다.

## 4. 사용자 프로필 (서버 비저장 — 클라이언트 스키마)

`BusinessProfile`은 DB 테이블이 없다. 스키마 정본은 `services/api/app/common/profile.py`(Pydantic)이고, 프론트는 OpenAPI에서 생성된 타입 + zod 스키마를 쓴다. 필드 정의는 docs/21 §3, docs/22 §3.

브라우저 저장 키: `gn.profile.v1` (값: `{schema_version: 1, updated_at, profile}`). 스키마 버전이 오르면 `lib/profile-store.ts`의 마이그레이션 함수로 변환한다.
