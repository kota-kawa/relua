"""Add the internal company collection queue and its check history."""

import sqlalchemy as sa

from alembic import op

revision = "20260807_0006"
down_revision = "20260806_0005"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Revision 0001 builds a fresh database from the live metadata. On a fresh install these
    # tables therefore already exist by the time Alembic reaches this revision; an upgraded
    # deployment needs them created here.
    existing = set(sa.inspect(op.get_bind()).get_table_names())
    if "collection_targets" not in existing:
        op.create_table(
            "collection_targets",
            sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
            sa.Column("company_id", sa.Integer(), nullable=False),
            sa.Column("industry_id", sa.Integer(), nullable=False),
            sa.Column("sector_id", sa.Integer(), nullable=True),
            sa.Column("priority_tier", sa.Integer(), nullable=False, server_default="2"),
            sa.Column("check_interval_days", sa.Integer(), nullable=False, server_default="30"),
            sa.Column("last_checked_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("next_check_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("last_check_result", sa.String(length=32), nullable=True),
            sa.Column("last_found_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
            sa.Column("selection_reason", sa.String(length=500), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
            sa.CheckConstraint("check_interval_days BETWEEN 1 AND 365", name="ck_collection_target_interval"),
            sa.CheckConstraint("priority_tier BETWEEN 1 AND 3", name="ck_collection_target_priority"),
            sa.CheckConstraint(
                "last_check_result IS NULL OR last_check_result IN ('found', 'no_opening', 'unreachable', 'needs_review')",
                name="ck_collection_target_result",
            ),
            sa.ForeignKeyConstraint(["company_id"], ["companies.id"], ondelete="RESTRICT"),
            sa.ForeignKeyConstraint(["industry_id"], ["industries.id"], ondelete="RESTRICT"),
            sa.ForeignKeyConstraint(["sector_id"], ["sectors.id"], ondelete="RESTRICT"),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint("company_id", "industry_id", name="uq_collection_target_company_industry"),
        )
        op.create_index("ix_collection_targets_next_check_at", "collection_targets", ["next_check_at"])
        op.create_index(
            "ix_collection_targets_queue",
            "collection_targets",
            ["is_active", "priority_tier", "next_check_at"],
        )
    if "collection_sources" not in existing:
        op.create_table(
            "collection_sources",
            sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
            sa.Column("collection_target_id", sa.Integer(), nullable=False),
            sa.Column("source_type", sa.String(length=32), nullable=False),
            sa.Column("url", sa.String(length=2048), nullable=False),
            sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
            sa.Column("last_checked_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
            sa.ForeignKeyConstraint(["collection_target_id"], ["collection_targets.id"], ondelete="CASCADE"),
            sa.PrimaryKeyConstraint("id"),
            sa.CheckConstraint(
                "source_type IN ('recruit', 'internship', 'event', 'news', 'other')",
                name="ck_collection_source_type",
            ),
            sa.UniqueConstraint("collection_target_id", "url", name="uq_collection_source_target_url"),
        )
    if "collection_checks" not in existing:
        op.create_table(
            "collection_checks",
            sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
            sa.Column("collection_target_id", sa.Integer(), nullable=False),
            sa.Column("result", sa.String(length=32), nullable=False),
            sa.Column("checked_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
            sa.Column("source_url", sa.String(length=2048), nullable=True),
            sa.Column("opportunity_id", sa.String(length=36), nullable=True),
            sa.Column("request_id", sa.String(length=100), nullable=False),
            sa.Column("client_name", sa.String(length=100), nullable=False, server_default="mcp-client"),
            sa.Column("note", sa.String(length=500), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
            sa.ForeignKeyConstraint(["collection_target_id"], ["collection_targets.id"], ondelete="CASCADE"),
            sa.ForeignKeyConstraint(["opportunity_id"], ["opportunities.id"], ondelete="SET NULL"),
            sa.PrimaryKeyConstraint("id"),
            sa.CheckConstraint(
                "result IN ('found', 'no_opening', 'unreachable', 'needs_review')",
                name="ck_collection_check_result",
            ),
            sa.UniqueConstraint("request_id"),
        )
    if "collection_request_records" not in existing:
        op.create_table(
            "collection_request_records",
            sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
            sa.Column("request_id", sa.String(length=100), nullable=False),
            sa.Column("operation", sa.String(length=32), nullable=False),
            sa.Column("request_hash", sa.String(length=64), nullable=False),
            sa.Column("entity_type", sa.String(length=32), nullable=False),
            sa.Column("entity_id", sa.String(length=64), nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint("request_id"),
        )


def downgrade() -> None:
    op.drop_table("collection_request_records")
    op.drop_table("collection_checks")
    op.drop_table("collection_sources")
    op.drop_index("ix_collection_targets_queue", table_name="collection_targets")
    op.drop_index("ix_collection_targets_next_check_at", table_name="collection_targets")
    op.drop_table("collection_targets")
