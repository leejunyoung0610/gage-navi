"""0004_stale_area: 미갱신 의심의 면적 근거 컬럼 (docs/04-data-model.md §2)

`license_record.stale_area_match`를 더한다 (T-017, docs/10 §6).

Revision ID: 0004_stale_area
Revises: 0003_normalize
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0004_stale_area"
down_revision: str | None = "0003_normalize"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        "ALTER TABLE license_record ADD COLUMN stale_area_match BOOLEAN NOT NULL DEFAULT false"
    )


def downgrade() -> None:
    op.execute("ALTER TABLE license_record DROP COLUMN stale_area_match")
