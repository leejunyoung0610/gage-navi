"""0002_rules: 규칙·관리자 테이블 (docs/04-data-model.md §3 DDL 그대로)

Revision ID: 0002_rules
Revises: 0001_location
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0002_rules"
down_revision: str | None = "0001_location"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# docs/04 §3의 DDL을 문장 단위로 옮긴 것. 바꾸려면 문서를 먼저 고치고 새 마이그레이션을 만든다.
# (asyncpg는 한 번에 한 문장만 실행하므로 나눠 둔다.)
UPGRADE_STATEMENTS: tuple[str, ...] = (
    """\
CREATE TABLE source_site (
  id          BIGSERIAL PRIMARY KEY,
  name        TEXT NOT NULL,
  kind        TEXT NOT NULL CHECK (kind IN ('api','page')),
  url         TEXT NOT NULL,
  active      BOOLEAN NOT NULL DEFAULT true
)
""",
    """\
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
)
""",
    """\
CREATE TABLE document (
  id             BIGSERIAL PRIMARY KEY,
  announcement_id BIGINT NOT NULL REFERENCES announcement(id),
  file_name      TEXT NOT NULL,
  format         TEXT NOT NULL CHECK (format IN ('hwp','hwpx','pdf','html')),
  storage_path   TEXT NOT NULL,
  file_sha256    TEXT NOT NULL,
  text           TEXT,                     -- 변환 결과
  line_index     JSONB,                    -- [{line_no, page, start_char, end_char}]
  converter      TEXT,                     -- 'hwpx-xml@1' 등
  converted_at   TIMESTAMPTZ,
  convert_status TEXT NOT NULL DEFAULT 'pending' CHECK (convert_status IN ('pending','ok','failed','manual'))
)
""",
    """\
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
)
""",
    """\
CREATE TABLE extraction (
  id              BIGSERIAL PRIMARY KEY,
  announcement_id BIGINT NOT NULL REFERENCES announcement(id),
  model           TEXT NOT NULL,
  prompt_version  TEXT NOT NULL,
  dsl_version     TEXT NOT NULL,
  auto_checks     JSONB NOT NULL DEFAULT '{}'::jsonb,
  status          TEXT NOT NULL DEFAULT 'pending' CHECK (status IN ('pending','reviewed')),
  created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
)
""",
    """\
CREATE TABLE extraction_item (
  id                  BIGSERIAL PRIMARY KEY,
  extraction_id       BIGINT NOT NULL REFERENCES extraction(id) ON DELETE CASCADE,
  program_id          TEXT REFERENCES program(id),   -- 검수 시 연결
  proposed_program_key TEXT NOT NULL,
  output              JSONB NOT NULL,                -- 규칙 DSL 초안
  needs_review_fields TEXT[] NOT NULL DEFAULT '{}',
  status              TEXT NOT NULL DEFAULT 'pending' CHECK (status IN ('pending','approved','rejected')),
  reviewed_at         TIMESTAMPTZ
)
""",
    """\
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
)
""",
    """\
-- 한 프로그램에 approved 규칙은 동시에 1개
CREATE UNIQUE INDEX rule_one_approved ON rule (program_id) WHERE status = 'approved'
""",
    """\
CREATE TABLE evidence (
  id          BIGSERIAL PRIMARY KEY,
  rule_id     BIGINT NOT NULL REFERENCES rule(id) ON DELETE CASCADE,
  ev_key      TEXT NOT NULL,              -- 'E1'
  document_id BIGINT NOT NULL REFERENCES document(id),
  quote       TEXT NOT NULL CHECK (char_length(quote) <= 500),
  loc         TEXT NOT NULL,              -- 'p3:l12-14'
  similarity  NUMERIC(4,3) NOT NULL CHECK (similarity BETWEEN 0 AND 1),  -- 원문 대조 점수 0~1 (docs/20 §10.4)
  UNIQUE (rule_id, ev_key)
)
""",
    """\
CREATE TABLE change_event (
  id              BIGSERIAL PRIMARY KEY,
  announcement_id BIGINT NOT NULL REFERENCES announcement(id),
  target          TEXT NOT NULL CHECK (target IN ('page','attachment')),
  prev_hash       TEXT,
  new_hash        TEXT NOT NULL,
  diff            TEXT,
  detected_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
  review_status   TEXT NOT NULL DEFAULT 'open' CHECK (review_status IN ('open','done'))
)
""",
    """\
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
)
""",
    """\
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
)
""",
    """\
CREATE TABLE eval_case (
  id              BIGSERIAL PRIMARY KEY,
  announcement_id BIGINT NOT NULL REFERENCES announcement(id),
  split           TEXT NOT NULL CHECK (split IN ('dev','test')),
  gold            JSONB NOT NULL,         -- 공고 1건 → 규칙 배열 (사람 라벨)
  labeled_by      TEXT NOT NULL,
  labeled_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
  relabel_of      BIGINT REFERENCES eval_case(id)    -- 일관성 측정용 재라벨
)
""",
    """\
CREATE TABLE eval_run (
  id             BIGSERIAL PRIMARY KEY,
  prompt_version TEXT NOT NULL,
  model          TEXT NOT NULL,
  split          TEXT NOT NULL CHECK (split IN ('dev','test')),
  metrics        JSONB NOT NULL,          -- docs/50 §5 형식 (점추정 + 95% CI)
  created_at     TIMESTAMPTZ NOT NULL DEFAULT now()
)
""",
    """\
CREATE TABLE admin_user (
  id            BIGSERIAL PRIMARY KEY,
  username      TEXT NOT NULL UNIQUE,
  password_hash TEXT NOT NULL,
  created_at    TIMESTAMPTZ NOT NULL DEFAULT now()
)
""",
)

# 생성의 역순. rule_one_approved 인덱스는 rule 테이블과 함께 지워진다.
DOWNGRADE_TABLES: tuple[str, ...] = (
    "admin_user",
    "eval_run",
    "eval_case",
    "rate_base",
    "review_log",
    "change_event",
    "evidence",
    "rule",
    "extraction_item",
    "extraction",
    "program",
    "document",
    "announcement",
    "source_site",
)


def upgrade() -> None:
    for statement in UPGRADE_STATEMENTS:
        op.execute(statement)


def downgrade() -> None:
    for table in DOWNGRADE_TABLES:
        op.execute(f"DROP TABLE {table}")
