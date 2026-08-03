"""Add a short public code to opportunities."""

import secrets

import sqlalchemy as sa

from alembic import op

revision = "20260730_0003"
down_revision = "20260729_0002"
branch_labels = None
depends_on = None


# Kept in sync with app.models on purpose: a migration must not depend on today's application code.
PUBLIC_CODE_ALPHABET = "0123456789ABCDEFGHJKMNPQRSTVWXYZ"
PUBLIC_CODE_LENGTH = 8


def _code() -> str:
    return "".join(secrets.choice(PUBLIC_CODE_ALPHABET) for _ in range(PUBLIC_CODE_LENGTH))


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    # On a fresh install, migration 0001's create_all() already builds today's
    # schema (see app.models), so public_code may already exist here. Guard the
    # same way 0002 guards its AI sector insert.
    columns = {col["name"] for col in inspector.get_columns("opportunities")}
    if "public_code" not in columns:
        op.add_column("opportunities", sa.Column("public_code", sa.String(PUBLIC_CODE_LENGTH), nullable=True))

        ids = [row[0] for row in bind.execute(sa.text("SELECT id FROM opportunities"))]
        used: set[str] = set()
        for opportunity_id in ids:
            code = _code()
            while code in used:
                code = _code()
            used.add(code)
            bind.execute(
                sa.text("UPDATE opportunities SET public_code = :code WHERE id = :id"),
                {"code": code, "id": opportunity_id},
            )

        op.alter_column("opportunities", "public_code", existing_type=sa.String(PUBLIC_CODE_LENGTH), nullable=False)

    has_unique_public_code = any(
        idx["column_names"] == ["public_code"] and idx.get("unique") for idx in inspector.get_indexes("opportunities")
    ) or any(uc["column_names"] == ["public_code"] for uc in inspector.get_unique_constraints("opportunities"))
    if not has_unique_public_code:
        op.create_index("uq_opportunities_public_code", "opportunities", ["public_code"], unique=True)


def downgrade() -> None:
    op.drop_index("uq_opportunities_public_code", table_name="opportunities")
    op.drop_column("opportunities", "public_code")
