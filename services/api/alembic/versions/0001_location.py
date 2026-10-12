"""0001_location: 자리 이력 테이블 (docs/04-data-model.md §2 DDL 그대로)

Revision ID: 0001_location
Revises:
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0001_location"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# docs/04 §2의 DDL을 문장 단위로 옮긴 것. 바꾸려면 문서를 먼저 고치고 새 마이그레이션을 만든다.
# (asyncpg는 한 번에 한 문장만 실행하므로 나눠 둔다.)
UPGRADE_STATEMENTS: tuple[str, ...] = (
    """\
CREATE EXTENSION IF NOT EXISTS postgis
""",
    """\
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
)
""",
    """\
-- 원본 행 보관 (컬럼명 원문 그대로)
CREATE TABLE license_raw (
  id            BIGSERIAL PRIMARY KEY,
  snapshot_id   BIGINT NOT NULL REFERENCES data_snapshot(id) ON DELETE CASCADE,
  license_type  TEXT NOT NULL,
  mgmt_no       TEXT NOT NULL,
  payload       JSONB NOT NULL,
  UNIQUE (snapshot_id, license_type, mgmt_no)
)
""",
    """\
-- 법정동코드 (폐지 코드 포함)
CREATE TABLE legal_dong (
  code        CHAR(10) PRIMARY KEY,
  sido        TEXT NOT NULL,
  sigungu     TEXT,
  eupmyeondong TEXT,
  ri          TEXT,
  full_name   TEXT NOT NULL,            -- '서울특별시 광진구 화양동'
  abolished   BOOLEAN NOT NULL DEFAULT false
)
""",
    """\
CREATE INDEX legal_dong_full_name_idx ON legal_dong (full_name)
""",
    """\
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
  bulk_closure      BOOLEAN NOT NULL DEFAULT false,   -- ADR-020
  stale_suspect     BOOLEAN NOT NULL DEFAULT false,   -- ADR-023
  source_updated_at TIMESTAMPTZ,
  last_snapshot_id  BIGINT REFERENCES data_snapshot(id),
  parse_version     TEXT NOT NULL,
  UNIQUE (license_type, mgmt_no),
  CHECK (closed_on IS NULL OR opened_on IS NULL OR closed_on >= opened_on)
)
""",
    """\
CREATE INDEX license_record_floor_idx ON license_record (pnu, floor)
""",
    """\
CREATE INDEX license_record_geom_idx  ON license_record USING GIST (geom)
""",
    """\
CREATE INDEX license_record_closed_idx ON license_record (jurisdiction_code, closed_on) WHERE status = 'closed'
""",
    """\
-- 필지(PNU) 요약 — 자리 페이지 1단계
CREATE TABLE parcel (
  pnu             CHAR(19) PRIMARY KEY,
  legal_dong_code CHAR(10) NOT NULL REFERENCES legal_dong(code),
  jibun_label     TEXT NOT NULL,         -- '서울특별시 광진구 화양동 47-1'
  road_addr       TEXT,                  -- 가장 최근 기록의 도로명주소(상세 제외)
  geom            GEOMETRY(Point, 4326),
  floors          TEXT[] NOT NULL,       -- 이력이 있는 층, 정렬: B2,B1,1,2,…
  record_count    INT NOT NULL,
  updated_at      TIMESTAMPTZ NOT NULL DEFAULT now()
)
""",
    """\
-- 층키 요약
CREATE TABLE floor_summary (
  pnu               CHAR(19) NOT NULL REFERENCES parcel(pnu),
  floor             TEXT NOT NULL,
  record_count      INT NOT NULL,
  records_since_2005 INT NOT NULL,
  open_now_count    INT NOT NULL,
  median_closed_tenure_days INT,          -- 폐업 업소 영업기간 중앙값 (bulk 제외)
  has_concurrent    BOOLEAN NOT NULL,     -- 동시 영업 기록 존재 → "여러 점포" 안내
  method_version    TEXT NOT NULL,
  PRIMARY KEY (pnu, floor)
)
""",
    """\
-- 기록별 과거 폐업 횟수 (층키 기준, docs/10 §6)
CREATE TABLE record_prior (
  record_id             BIGINT PRIMARY KEY REFERENCES license_record(id) ON DELETE CASCADE,
  prior_closures_floor  INT NOT NULL,
  method_version        TEXT NOT NULL,
  computed_at           TIMESTAMPTZ NOT NULL DEFAULT now()
)
""",
    """\
-- 기준율 (월 1회 계산, 화면에서 읽기 전용)
CREATE TABLE base_rate (
  id             BIGSERIAL PRIMARY KEY,
  snapshot_label TEXT NOT NULL,            -- '2026-11'
  method_version TEXT NOT NULL,
  scope_code     TEXT NOT NULL,            -- '11'(서울 전체) 또는 시군구 5자리
  license_group  TEXT NOT NULL DEFAULT 'food3',   -- MVP: 식품 3종 통합. 'general_restaurant' 등 개별은 n 충족 시
  prior_bucket   TEXT NOT NULL CHECK (prior_bucket IN ('0','1','2','3','4+')),
  n              INT NOT NULL,
  events         INT NOT NULL,             -- 3년 내 폐업 수
  rate           NUMERIC(6,4) NOT NULL,
  ci_low         NUMERIC(6,4) NOT NULL,    -- Wilson 95%
  ci_high        NUMERIC(6,4) NOT NULL,
  cohort_from    DATE NOT NULL,
  cohort_to      DATE NOT NULL,
  created_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
  UNIQUE (snapshot_label, method_version, scope_code, license_group, prior_bucket)
)
""",
    """\
-- 모형 카드 (방법론 페이지 데이터)
CREATE TABLE model_card (
  id             BIGSERIAL PRIMARY KEY,
  snapshot_label TEXT NOT NULL,
  method_version TEXT NOT NULL,
  payload        JSONB NOT NULL,           -- docs/10 §7.3 형식
  created_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
  UNIQUE (snapshot_label, method_version)
)
""",
    """\
-- 정정·삭제 요청 (연락처 수집 안 함)
CREATE TABLE correction_request (
  id          BIGSERIAL PRIMARY KEY,
  pnu         CHAR(19) NOT NULL,
  floor       TEXT,
  record_id   BIGINT REFERENCES license_record(id),
  kind        TEXT NOT NULL CHECK (kind IN ('wrong_info','remove_request','other')),
  message     TEXT NOT NULL CHECK (char_length(message) <= 1000),
  status      TEXT NOT NULL DEFAULT 'open' CHECK (status IN ('open','resolved','rejected')),
  resolution_note TEXT,
  created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
  resolved_at TIMESTAMPTZ
)
""",
    """\
-- 숨김 처리 (정정 요청 승인 결과)
CREATE TABLE record_suppression (
  record_id   BIGINT PRIMARY KEY REFERENCES license_record(id),
  reason      TEXT NOT NULL,
  request_id  BIGINT REFERENCES correction_request(id),
  created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
)
""",
)

# 생성의 역순. postgis 확장은 다른 스키마 객체가 쓸 수 있어 지우지 않는다.
DOWNGRADE_TABLES: tuple[str, ...] = (
    "record_suppression",
    "correction_request",
    "model_card",
    "base_rate",
    "record_prior",
    "floor_summary",
    "parcel",
    "license_record",
    "legal_dong",
    "license_raw",
    "data_snapshot",
)


def upgrade() -> None:
    for statement in UPGRADE_STATEMENTS:
        op.execute(statement)


def downgrade() -> None:
    for table in DOWNGRADE_TABLES:
        op.execute(f"DROP TABLE {table}")
