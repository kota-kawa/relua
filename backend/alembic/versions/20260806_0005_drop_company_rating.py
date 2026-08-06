"""Drop the unused company_rating column from opportunities.

The column shipped in the initial schema but was never exposed through the API, the MCP tools
or the UI. Scoring named companies with an unverifiable value was dropped from the product,
so the column goes with it rather than sitting dead in the table.
"""

import sqlalchemy as sa

from alembic import op

revision = "20260806_0005"
down_revision = "20260805_0004"
branch_labels = None
depends_on = None


def _has_company_rating() -> bool:
    return "company_rating" in {col["name"] for col in sa.inspect(op.get_bind()).get_columns("opportunities")}


def upgrade() -> None:
    # Revision 0001 builds a fresh database from the live models, which no longer declare this
    # column, so only a database created before this revision has anything to drop.
    if _has_company_rating():
        # Postgres drops ck_company_rating along with its only column; naming it here would fail
        # on a database where 0001 built the table without the constraint.
        op.drop_column("opportunities", "company_rating")


def downgrade() -> None:
    if not _has_company_rating():
        op.add_column("opportunities", sa.Column("company_rating", sa.Integer(), nullable=True))
        op.create_check_constraint(
            "ck_company_rating",
            "opportunities",
            "company_rating IS NULL OR company_rating BETWEEN 1 AND 5",
        )
