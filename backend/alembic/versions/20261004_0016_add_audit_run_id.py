"""Add optional MCP execution correlation without changing existing audit records."""

import sqlalchemy as sa

from alembic import op

revision = "20261004_0016"
down_revision = "20260919_0015"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    if "run_id" not in {column["name"] for column in sa.inspect(bind).get_columns("audit_logs")}:
        op.add_column("audit_logs", sa.Column("run_id", sa.String(100), nullable=True))
    if "ix_audit_logs_run_id" not in {index["name"] for index in sa.inspect(bind).get_indexes("audit_logs")}:
        op.create_index("ix_audit_logs_run_id", "audit_logs", ["run_id"])


def downgrade() -> None:
    op.drop_index("ix_audit_logs_run_id", table_name="audit_logs")
    op.drop_column("audit_logs", "run_id")
