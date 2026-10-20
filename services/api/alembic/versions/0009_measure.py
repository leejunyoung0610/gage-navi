"""0009_measure: 방문 측정·"도움이 됐나요" 일별 합계 (docs/04-data-model.md §2)

`measure_daily_count` 테이블을 더한다 (T-104, docs/30 `POST /measure/events`). 이벤트 한 건씩이
아니라 (날짜, 이벤트)마다 합계만 둔다. 식별자·IP·User-Agent·시각 열이 없다.

Revision ID: 0009_measure
Revises: 0008_search_match
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0009_measure"
down_revision: str | None = "0008_search_match"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

UPGRADE_STATEMENTS: tuple[str, ...] = (
    """
CREATE TABLE measure_daily_count (
  day    DATE NOT NULL,
  event  TEXT NOT NULL CHECK (event IN ('first_visit','revisit_7d','helpful_yes','helpful_no')),
  count  INT NOT NULL CHECK (count >= 0),
  PRIMARY KEY (day, event)
)
""",
)


def upgrade() -> None:
    for statement in UPGRADE_STATEMENTS:
        op.execute(statement)


def downgrade() -> None:
    op.execute("DROP TABLE measure_daily_count")
