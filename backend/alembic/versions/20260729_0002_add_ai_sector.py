"""Add AI as an IT and communications sector."""

import sqlalchemy as sa

from alembic import op

revision = "20260729_0002"
down_revision = "20260726_0001"
branch_labels = None
depends_on = None


sectors = sa.table(
    "sectors",
    sa.column("id", sa.Integer),
    sa.column("slug", sa.String),
    sa.column("name", sa.String),
    sa.column("sort_order", sa.Integer),
    sa.column("is_active", sa.Boolean),
    sa.column("industry_id", sa.Integer),
)


def upgrade() -> None:
    bind = op.get_bind()
    bind.execute(
        sectors.update()
        .where(sectors.c.slug == "sector-1-06")
        .values(sort_order=7)
    )
    exists = bind.execute(
        sa.select(sectors.c.id).where(sectors.c.slug == "sector-1-71")
    ).scalar_one_or_none()
    if exists is None:
        bind.execute(
            sectors.insert().values(
                id=71,
                slug="sector-1-71",
                name="AI",
                sort_order=6,
                is_active=True,
                industry_id=1,
            )
        )


def downgrade() -> None:
    bind = op.get_bind()
    bind.execute(sectors.delete().where(sectors.c.slug == "sector-1-71"))
    bind.execute(
        sectors.update()
        .where(sectors.c.slug == "sector-1-06")
        .values(sort_order=6)
    )
