"""Move industry classification off collection_targets onto company_industries.

collection_targets was keyed on (company_id, industry_id), so a company operating in two industries
occupied two rows: checked twice on schedule, counted twice in any "how many companies" figure, and
reported as uncovered under whichever industry its postings were not filed under. Classification
moves to company_industries (many per company), the duplicate targets are merged into one row per
company, and collection_targets keeps only the monitoring schedule.
"""

import sqlalchemy as sa

from alembic import op

revision = "20260820_0012"
down_revision = "20260815_0011"
branch_labels = None
depends_on = None


def _collection_target_columns() -> set[str]:
    return {column["name"] for column in sa.inspect(op.get_bind()).get_columns("collection_targets")}


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    if "company_industries" not in set(inspector.get_table_names()):
        op.create_table(
            "company_industries",
            sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
            sa.Column("company_id", sa.Integer(), nullable=False),
            sa.Column("industry_id", sa.Integer(), nullable=False),
            sa.Column("sector_id", sa.Integer(), nullable=True),
            sa.Column("is_primary", sa.Boolean(), nullable=False, server_default=sa.false()),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
            sa.ForeignKeyConstraint(["company_id"], ["companies.id"], ondelete="CASCADE"),
            sa.ForeignKeyConstraint(["industry_id"], ["industries.id"], ondelete="RESTRICT"),
            sa.ForeignKeyConstraint(["sector_id"], ["sectors.id"], ondelete="RESTRICT"),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint("company_id", "industry_id", name="uq_company_industry"),
        )
        op.create_index("ix_company_industries_industry", "company_industries", ["industry_id"])
        op.create_index("ix_company_industries_sector", "company_industries", ["sector_id"])
        op.create_index(
            "uq_company_industry_primary",
            "company_industries",
            ["company_id"],
            unique=True,
            postgresql_where=sa.text("is_primary"),
            sqlite_where=sa.text("is_primary"),
        )

    # Revision 0001 builds fresh databases straight from the live metadata, where collection_targets
    # never had these columns. Only an upgraded database has data to move.
    if "industry_id" not in _collection_target_columns():
        return

    # Every classification the old schema knew about: one per collection target, plus one per
    # posting. Postings carry a non-null sector, so they also fill in sectors the targets left null.
    op.execute(
        """
        INSERT INTO company_industries (company_id, industry_id, sector_id, is_primary)
        SELECT company_id, industry_id, MIN(sector_id), FALSE
        FROM (
            SELECT company_id, industry_id, sector_id FROM collection_targets
            UNION ALL
            SELECT company_id, industry_id, sector_id FROM opportunities
        ) AS classifications
        GROUP BY company_id, industry_id
        """
    )
    # The lowest-numbered target was the company's first and, by the old ordering, its most
    # important; its industry becomes the one shown wherever a single industry has to be picked.
    op.execute(
        """
        UPDATE company_industries SET is_primary = TRUE
        WHERE id IN (
            SELECT MIN(ci.id)
            FROM company_industries ci
            JOIN (
                SELECT company_id, MIN(priority_tier * 1000000 + id) AS ranked
                FROM collection_targets GROUP BY company_id
            ) best ON best.company_id = ci.company_id
            JOIN collection_targets ct
              ON ct.company_id = ci.company_id
             AND ct.industry_id = ci.industry_id
             AND ct.priority_tier * 1000000 + ct.id = best.ranked
            GROUP BY ci.company_id
        )
        """
    )
    # Companies known only from postings never had a target, so the loop above skipped them.
    op.execute(
        """
        UPDATE company_industries SET is_primary = TRUE
        WHERE id IN (
            SELECT MIN(id) FROM company_industries
            WHERE company_id NOT IN (SELECT company_id FROM company_industries WHERE is_primary)
            GROUP BY company_id
        )
        """
    )

    # Merge duplicates into the surviving target: lowest priority_tier wins, then lowest id. The
    # survivor inherits every source and check, and keeps the earliest/most recent timestamps so no
    # verification history is lost by the merge.
    op.execute(
        """
        CREATE TEMPORARY TABLE target_merge AS
        SELECT ct.id AS loser_id, keep.keep_id AS keeper_id
        FROM collection_targets ct
        JOIN (
            SELECT c.company_id,
                   (SELECT t.id FROM collection_targets t
                     WHERE t.company_id = c.company_id
                     ORDER BY t.priority_tier, t.id LIMIT 1) AS keep_id
            FROM (SELECT DISTINCT company_id FROM collection_targets) c
        ) keep ON keep.company_id = ct.company_id
        WHERE ct.id <> keep.keep_id
        """
    )
    op.execute(
        """
        UPDATE collection_targets SET
            priority_tier = (
                SELECT MIN(t.priority_tier) FROM collection_targets t
                WHERE t.company_id = collection_targets.company_id
            ),
            check_interval_days = (
                SELECT MIN(t.check_interval_days) FROM collection_targets t
                WHERE t.company_id = collection_targets.company_id
            ),
            last_checked_at = (
                SELECT MAX(t.last_checked_at) FROM collection_targets t
                WHERE t.company_id = collection_targets.company_id
            ),
            last_found_at = (
                SELECT MAX(t.last_found_at) FROM collection_targets t
                WHERE t.company_id = collection_targets.company_id
            ),
            next_check_at = (
                SELECT MIN(t.next_check_at) FROM collection_targets t
                WHERE t.company_id = collection_targets.company_id
            ),
            is_active = (
                SELECT MAX(CASE WHEN t.is_active THEN 1 ELSE 0 END) = 1 FROM collection_targets t
                WHERE t.company_id = collection_targets.company_id
            )
        WHERE id IN (SELECT keeper_id FROM target_merge)
        """
    )
    # A URL registered under both duplicates would violate uq_collection_source_target_url once
    # both point at the survivor, so drop the copy before re-pointing the rest.
    op.execute(
        """
        DELETE FROM collection_sources
        WHERE id IN (
            SELECT s.id FROM collection_sources s
            JOIN target_merge m ON m.loser_id = s.collection_target_id
            JOIN collection_sources kept ON kept.collection_target_id = m.keeper_id AND kept.url = s.url
        )
        """
    )
    op.execute(
        """
        UPDATE collection_sources SET collection_target_id = (
            SELECT keeper_id FROM target_merge WHERE loser_id = collection_sources.collection_target_id
        )
        WHERE collection_target_id IN (SELECT loser_id FROM target_merge)
        """
    )
    op.execute(
        """
        UPDATE collection_checks SET collection_target_id = (
            SELECT keeper_id FROM target_merge WHERE loser_id = collection_checks.collection_target_id
        )
        WHERE collection_target_id IN (SELECT loser_id FROM target_merge)
        """
    )
    op.execute("DELETE FROM collection_targets WHERE id IN (SELECT loser_id FROM target_merge)")
    op.execute("DROP TABLE target_merge")

    with op.batch_alter_table("collection_targets") as batch:
        batch.drop_constraint("uq_collection_target_company_industry", type_="unique")
        batch.drop_column("industry_id")
        batch.drop_column("sector_id")
        batch.create_unique_constraint("uq_collection_target_company", ["company_id"])


def downgrade() -> None:
    if "industry_id" not in _collection_target_columns():
        with op.batch_alter_table("collection_targets") as batch:
            batch.add_column(sa.Column("industry_id", sa.Integer(), nullable=True))
            batch.add_column(sa.Column("sector_id", sa.Integer(), nullable=True))
        # Only the primary classification survives a downgrade: the old schema has nowhere to put
        # the others, and re-splitting one target into several would invent ids nothing references.
        op.execute(
            """
            UPDATE collection_targets SET
                industry_id = (
                    SELECT ci.industry_id FROM company_industries ci
                    WHERE ci.company_id = collection_targets.company_id
                    ORDER BY ci.is_primary DESC, ci.id LIMIT 1
                ),
                sector_id = (
                    SELECT ci.sector_id FROM company_industries ci
                    WHERE ci.company_id = collection_targets.company_id
                    ORDER BY ci.is_primary DESC, ci.id LIMIT 1
                )
            """
        )
        op.execute("DELETE FROM collection_targets WHERE industry_id IS NULL")
        with op.batch_alter_table("collection_targets") as batch:
            batch.alter_column("industry_id", nullable=False)
            batch.drop_constraint("uq_collection_target_company", type_="unique")
            batch.create_unique_constraint(
                "uq_collection_target_company_industry", ["company_id", "industry_id"]
            )
            batch.create_foreign_key(
                "fk_collection_targets_industry_id", "industries", ["industry_id"], ["id"], ondelete="RESTRICT"
            )
            batch.create_foreign_key(
                "fk_collection_targets_sector_id", "sectors", ["sector_id"], ["id"], ondelete="RESTRICT"
            )
    op.drop_table("company_industries")
