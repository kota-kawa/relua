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
    op.add_column("opportunities", sa.Column("public_code", sa.String(PUBLIC_CODE_LENGTH), nullable=True))

    bind = op.get_bind()
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
    op.create_index("uq_opportunities_public_code", "opportunities", ["public_code"], unique=True)


def downgrade() -> None:
    op.drop_index("uq_opportunities_public_code", table_name="opportunities")
    op.drop_column("opportunities", "public_code")
