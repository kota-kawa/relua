"""Enable pg_trgm and add indexes for relevance search."""

from alembic import op

revision = "20260814_0009"
down_revision = "20260809_0008"
branch_labels = None
depends_on = None


TRIGRAM_INDEXES = {
    "ix_companies_name_trgm": ("companies", "name"),
    "ix_opportunities_event_name_trgm": ("opportunities", "event_name"),
    "ix_opportunities_description_trgm": ("opportunities", "description"),
    "ix_opportunities_requirements_trgm": ("opportunities", "requirements"),
}


def upgrade() -> None:
    if op.get_bind().dialect.name != "postgresql":
        return
    op.execute("CREATE EXTENSION IF NOT EXISTS pg_trgm")
    for index_name, (table_name, column_name) in TRIGRAM_INDEXES.items():
        op.execute(
            f"CREATE INDEX IF NOT EXISTS {index_name} "
            f"ON {table_name} USING gin ({column_name} gin_trgm_ops)"
        )


def downgrade() -> None:
    if op.get_bind().dialect.name != "postgresql":
        return
    for index_name in reversed(TRIGRAM_INDEXES):
        op.execute(f"DROP INDEX IF EXISTS {index_name}")
    # pg_trgm may be shared by other application objects, so leave the extension installed.
