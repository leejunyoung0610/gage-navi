"""0007_admin_auth: 관리자 세션·로그인 잠금, 재생성 호출 시각 (docs/04-data-model.md §2·§3)

`admin_user`에 로그인 잠금 컬럼, `admin_session` 테이블, `correction_request.revalidated_at`을
더한다 (T-023, docs/30 §3).

Revision ID: 0007_admin_auth
Revises: 0006_floor_scale
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0007_admin_auth"
down_revision: str | None = "0006_floor_scale"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

UPGRADE_STATEMENTS: tuple[str, ...] = (
    "ALTER TABLE admin_user ADD COLUMN failed_login_count INT NOT NULL DEFAULT 0",
    "ALTER TABLE admin_user ADD COLUMN failed_login_started_at TIMESTAMPTZ",
    "ALTER TABLE admin_user ADD COLUMN locked_until TIMESTAMPTZ",
    """
CREATE TABLE admin_session (
  token_hash    BYTEA PRIMARY KEY,
  admin_user_id BIGINT NOT NULL REFERENCES admin_user(id) ON DELETE CASCADE,
  created_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
  last_seen_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
  expires_at    TIMESTAMPTZ NOT NULL
)
""",
    "CREATE INDEX ON admin_session (admin_user_id)",
    "ALTER TABLE correction_request ADD COLUMN revalidated_at TIMESTAMPTZ",
)


def upgrade() -> None:
    for statement in UPGRADE_STATEMENTS:
        op.execute(statement)


def downgrade() -> None:
    op.execute("ALTER TABLE correction_request DROP COLUMN revalidated_at")
    op.execute("DROP TABLE admin_session")
    for column in ("locked_until", "failed_login_started_at", "failed_login_count"):
        op.execute(f"ALTER TABLE admin_user DROP COLUMN {column}")
