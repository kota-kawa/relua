"""Add a public code and the company profile columns to companies.

The public code gives a company page a stable URL that never exposes an internal row id, the same
policy opportunities already follow. The profile columns are nullable because a company exists as
soon as a posting names it, long before anyone writes its profile.
"""

import secrets

import sqlalchemy as sa

from alembic import op

revision = "20260907_0014"
down_revision = "20260820_0013"
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
    # Revision 0001 builds fresh databases from live ORM metadata, so every column here can already
    # exist. Read the column set once: the inspector caches per table anyway, and each branch below
    # has to make the same decision.
    columns = {column["name"] for column in inspector.get_columns("companies")}

    if "public_code" not in columns:
        op.add_column("companies", sa.Column("public_code", sa.String(PUBLIC_CODE_LENGTH), nullable=True))
        ids = [row[0] for row in bind.execute(sa.text("SELECT id FROM companies"))]
        used: set[str] = set()
        for company_id in ids:
            code = _code()
            while code in used:
                code = _code()
            used.add(code)
            bind.execute(
                sa.text("UPDATE companies SET public_code = :code WHERE id = :id"),
                {"code": code, "id": company_id},
            )
        # batch_alter_table keeps the NOT NULL promotion working on SQLite, which cannot ALTER a
        # column in place. On PostgreSQL it emits the plain ALTER.
        with op.batch_alter_table("companies") as batch:
            batch.alter_column("public_code", existing_type=sa.String(PUBLIC_CODE_LENGTH), nullable=False)

    if "business_summary" not in columns:
        op.add_column("companies", sa.Column("business_summary", sa.String(length=200), nullable=True))
    if "description" not in columns:
        op.add_column("companies", sa.Column("description", sa.Text(), nullable=True))
    if "business_areas" not in columns:
        op.add_column("companies", sa.Column("business_areas", sa.JSON(), nullable=True))
    if "website_url" not in columns:
        op.add_column("companies", sa.Column("website_url", sa.String(length=2048), nullable=True))

    if "updated_at" not in columns:
        op.add_column(
            "companies",
            sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=True),
        )
        # Nothing has edited these rows yet, so creation time is the only honest last-change time.
        op.execute("UPDATE companies SET updated_at = created_at")
        with op.batch_alter_table("companies") as batch:
            batch.alter_column("updated_at", existing_type=sa.DateTime(timezone=True), nullable=False)

    # create_all() emits an unnamed UNIQUE constraint while this revision creates a named index, so
    # accept either as proof the uniqueness already exists.
    has_unique_public_code = any(
        index["column_names"] == ["public_code"] and index.get("unique")
        for index in inspector.get_indexes("companies")
    ) or any(constraint["column_names"] == ["public_code"] for constraint in inspector.get_unique_constraints("companies"))
    if not has_unique_public_code:
        op.create_index("uq_companies_public_code", "companies", ["public_code"], unique=True)


def downgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    columns = {column["name"] for column in inspector.get_columns("companies")}
    if any(index["name"] == "uq_companies_public_code" for index in inspector.get_indexes("companies")):
        op.drop_index("uq_companies_public_code", table_name="companies")
    for column_name in (
        "updated_at",
        "website_url",
        "business_areas",
        "description",
        "business_summary",
        "public_code",
    ):
        if column_name in columns:
            op.drop_column("companies", column_name)
