"""Track reviewed date conflicts and consecutive unsuccessful collection checks."""

import sqlalchemy as sa

from alembic import op

revision = "20261005_0017"
down_revision = "20261004_0016"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    if "date_status_reviewed_at" not in {column["name"] for column in sa.inspect(bind).get_columns("opportunities")}:
        op.add_column("opportunities", sa.Column("date_status_reviewed_at", sa.DateTime(timezone=True), nullable=True))
    if "consecutive_failed_checks" not in {column["name"] for column in sa.inspect(bind).get_columns("collection_targets")}:
        op.add_column("collection_targets", sa.Column("consecutive_failed_checks", sa.Integer(), server_default="0", nullable=False))


def downgrade() -> None:
    op.drop_column("collection_targets", "consecutive_failed_checks")
    op.drop_column("opportunities", "date_status_reviewed_at")
