"""Add company identity request records and trigram indexes for alias search."""

import sqlalchemy as sa

from alembic import op

revision = "20260820_0013"
down_revision = "20260820_0012"
branch_labels = None
depends_on = None


TRIGRAM_INDEXES = {
    "ix_companies_normalized_name_trgm": ("companies", "normalized_name"),
    "ix_company_aliases_alias_trgm": ("company_aliases", "alias"),
    "ix_company_aliases_normalized_alias_trgm": ("company_aliases", "normalized_alias"),
}


def upgrade() -> None:
    # Revision 0001 builds a fresh database from live ORM metadata, so the table can already exist
    # even though an upgraded older database still needs this revision to create it.
    if "company_request_records" not in set(sa.inspect(op.get_bind()).get_table_names()):
        op.create_table(
            "company_request_records",
            sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
            sa.Column("request_id", sa.String(length=100), nullable=False),
            sa.Column("operation", sa.String(length=32), nullable=False),
            sa.Column("request_hash", sa.String(length=64), nullable=False),
            sa.Column("company_id", sa.Integer(), nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
            sa.ForeignKeyConstraint(["company_id"], ["companies.id"], ondelete="CASCADE"),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint("request_id"),
        )
    if op.get_bind().dialect.name != "postgresql":
        return
    op.execute("CREATE EXTENSION IF NOT EXISTS pg_trgm")
    for index_name, (table_name, column_name) in TRIGRAM_INDEXES.items():
        op.execute(f"CREATE INDEX IF NOT EXISTS {index_name} ON {table_name} USING gin ({column_name} gin_trgm_ops)")


def downgrade() -> None:
    if op.get_bind().dialect.name == "postgresql":
        for index_name in reversed(TRIGRAM_INDEXES):
            op.execute(f"DROP INDEX IF EXISTS {index_name}")
    op.drop_table("company_request_records")
