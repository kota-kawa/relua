"""Add opportunities.source_checked_at, tracking when the official source was last confirmed."""

import sqlalchemy as sa

from alembic import op

revision = "20260815_0011"
down_revision = "20260815_0010"
branch_labels = None
depends_on = None


def _has_column() -> bool:
    return "source_checked_at" in {
        column["name"] for column in sa.inspect(op.get_bind()).get_columns("opportunities")
    }


def upgrade() -> None:
    # Revision 0001 creates fresh databases from live metadata, so only upgraded databases need the
    # column and its backfill here.
    if _has_column():
        return
    op.add_column("opportunities", sa.Column("source_checked_at", sa.DateTime(timezone=True), nullable=True))
    # updated_at was already documented as "when the source was last read into this record" before
    # this column existed, so it is the best available estimate for every pre-existing row.
    op.execute("UPDATE opportunities SET source_checked_at = updated_at")
    op.create_index("ix_opportunities_source_checked_at", "opportunities", ["source_checked_at"])


def downgrade() -> None:
    if _has_column():
        op.drop_index("ix_opportunities_source_checked_at", table_name="opportunities")
        op.drop_column("opportunities", "source_checked_at")
