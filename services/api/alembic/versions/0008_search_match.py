"""0008_search_match: 검색 일치율 측정 결과 (docs/04-data-model.md §2)

방법론 페이지가 읽는 `search_match_result` 테이블을 더한다 (T-034, docs/30 `/stats/model-card`).

Revision ID: 0008_search_match
Revises: 0007_admin_auth
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0008_search_match"
down_revision: str | None = "0007_admin_auth"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

UPGRADE_STATEMENTS: tuple[str, ...] = (
    """
CREATE TABLE search_match_result (
  id          BIGSERIAL PRIMARY KEY,
  seed        INT NOT NULL UNIQUE,
  measured_on DATE NOT NULL,
  payload     JSONB NOT NULL,
  created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
)
""",
)


def upgrade() -> None:
    for statement in UPGRADE_STATEMENTS:
        op.execute(statement)


def downgrade() -> None:
    op.execute("DROP TABLE search_match_result")
