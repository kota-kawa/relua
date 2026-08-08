"""Add the soft-delete timestamp used by MCP delete and restore tools."""

import sqlalchemy as sa

from alembic import op

revision = "20260809_0008"
down_revision = "20260808_0007"
branch_labels = None
depends_on = None


def _has_column() -> bool:
    return "deleted_at" in {
        column["name"] for column in sa.inspect(op.get_bind()).get_columns("opportunities")
    }


def upgrade() -> None:
    # Revision 0001 creates fresh databases from live metadata, so only upgraded databases need
    # the column and index added here.
    if _has_column():
        return
    op.add_column("opportunities", sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True))
    op.create_index("ix_opportunities_deleted_at", "opportunities", ["deleted_at"])


def downgrade() -> None:
    if _has_column():
        op.drop_index("ix_opportunities_deleted_at", table_name="opportunities")
        op.drop_column("opportunities", "deleted_at")
