"""0006_floor_scale: 층 규모 (docs/04-data-model.md §2)

`floor_summary.max_concurrent`, `record_prior.max_concurrent_at_open`, `base_rate.floor_scale`을
더한다 (T-019b, docs/10 §7.1~§7.3).

Revision ID: 0006_floor_scale
Revises: 0005_prior_ex_surge
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0006_floor_scale"
down_revision: str | None = "0005_prior_ex_surge"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_OLD_UNIQUE = "base_rate_snapshot_label_method_version_scope_code_license__key"
_NEW_UNIQUE = "base_rate_snapshot_method_scope_group_scale_bucket_key"


def upgrade() -> None:
    # 문서의 정의는 기본값 없는 NOT NULL. 이미 행이 있어도 적용되도록 1로 채운 뒤 기본값을 뗀다
    for table, column in (
        ("floor_summary", "max_concurrent"),
        ("record_prior", "max_concurrent_at_open"),
    ):
        op.execute(
            f"ALTER TABLE {table} ADD COLUMN {column} INT NOT NULL DEFAULT 1 CHECK ({column} >= 1)"
        )
        op.execute(f"ALTER TABLE {table} ALTER COLUMN {column} DROP DEFAULT")
    op.execute(
        "ALTER TABLE base_rate ADD COLUMN floor_scale TEXT NOT NULL DEFAULT 'all' "
        "CHECK (floor_scale IN ('all','single','small','large'))"
    )
    op.execute(f"ALTER TABLE base_rate DROP CONSTRAINT {_OLD_UNIQUE}")
    op.execute(
        f"ALTER TABLE base_rate ADD CONSTRAINT {_NEW_UNIQUE} UNIQUE "
        "(snapshot_label, method_version, scope_code, license_group, floor_scale, prior_bucket)"
    )


def downgrade() -> None:
    op.execute(f"ALTER TABLE base_rate DROP CONSTRAINT {_NEW_UNIQUE}")
    op.execute("DELETE FROM base_rate WHERE floor_scale <> 'all'")
    op.execute("ALTER TABLE base_rate DROP COLUMN floor_scale")
    op.execute(
        f"ALTER TABLE base_rate ADD CONSTRAINT {_OLD_UNIQUE} UNIQUE "
        "(snapshot_label, method_version, scope_code, license_group, prior_bucket)"
    )
    op.execute("ALTER TABLE record_prior DROP COLUMN max_concurrent_at_open")
    op.execute("ALTER TABLE floor_summary DROP COLUMN max_concurrent")
