"""0003_normalize: 정규화에 필요한 컬럼·테이블 (docs/04-data-model.md §2)

`license_record.no_fixed_place`와 `closure_surge_day`를 더한다 (T-016, docs/10 §1.1·§5).

Revision ID: 0003_normalize
Revises: 0002_rules
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0003_normalize"
down_revision: str | None = "0002_rules"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# docs/04 §2의 DDL에서 0001 이후 바뀐 부분. 바꾸려면 문서를 먼저 고치고 새 마이그레이션을 만든다.
UPGRADE_STATEMENTS: tuple[str, ...] = (
    """\
ALTER TABLE license_record
  ADD COLUMN no_fixed_place BOOLEAN NOT NULL DEFAULT false
""",
    """\
-- 폐업 처리 급증일 (docs/10 §5, ADR-020). 정규화할 때마다 전체를 다시 만든다
CREATE TABLE closure_surge_day (
  jurisdiction_code  TEXT NOT NULL,
  closed_on          DATE NOT NULL,
  jurisdiction_label TEXT,               -- '마포구'. 그 관할 기록의 주소에 가장 많이 나온 시군구 이름, 정할 수 없으면 NULL
  closure_count      INT NOT NULL,       -- c(j, d): 그날 그 관할의 폐업 건수 (식품 3종 합산)
  median_daily       NUMERIC(8,1) NOT NULL,  -- m(j): 관할의 하루 폐업 건수 중앙값
  parse_version      TEXT NOT NULL,
  PRIMARY KEY (jurisdiction_code, closed_on)
)
""",
)

DOWNGRADE_STATEMENTS: tuple[str, ...] = (
    "DROP TABLE closure_surge_day",
    "ALTER TABLE license_record DROP COLUMN no_fixed_place",
)


def upgrade() -> None:
    for statement in UPGRADE_STATEMENTS:
        op.execute(statement)


def downgrade() -> None:
    for statement in DOWNGRADE_STATEMENTS:
        op.execute(statement)
