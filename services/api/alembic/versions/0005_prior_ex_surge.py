"""0005_prior_ex_surge: 급증일 폐업을 뺀 과거 폐업 횟수 (docs/04-data-model.md §2)

`record_prior.prior_closures_floor_ex_surge`를 더한다 (T-018, docs/10 §7.2).

Revision ID: 0005_prior_ex_surge
Revises: 0004_stale_area
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0005_prior_ex_surge"
down_revision: str | None = "0004_stale_area"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # 문서의 정의는 기본값 없는 NOT NULL. 이미 행이 있어도 적용되도록 0으로 채운 뒤 기본값을 뗀다
    op.execute(
        "ALTER TABLE record_prior ADD COLUMN prior_closures_floor_ex_surge INT NOT NULL DEFAULT 0"
    )
    op.execute("ALTER TABLE record_prior ALTER COLUMN prior_closures_floor_ex_surge DROP DEFAULT")


def downgrade() -> None:
    op.execute("ALTER TABLE record_prior DROP COLUMN prior_closures_floor_ex_surge")
