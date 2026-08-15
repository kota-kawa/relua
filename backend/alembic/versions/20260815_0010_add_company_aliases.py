"""Add company_aliases so company-name search and duplicate detection can resolve known aliases."""

import re
import unicodedata

import sqlalchemy as sa

from alembic import op

revision = "20260815_0010"
down_revision = "20260814_0010"
branch_labels = None
depends_on = None


#: A few well-known alternate spellings, seeded only when the target company already exists. New
#: aliases beyond these should be added through the application rather than another migration.
SEED_ALIASES = [
    ("ディーエヌエー", "DeNA"),
    ("野村総合研究所", "NRI"),
    ("三菱ufj銀行", "MUFG"),
]


def _normalize_company_name(value: str) -> str:
    """Mirrors app.services.normalization.normalize_company_name, duplicated so this migration
    keeps producing the same seed values even if that function changes later."""
    value = unicodedata.normalize("NFKC", value).strip()
    value = re.sub(r"\s+", "", value)
    value = re.sub(r"[（(](?:株)[）)]|㈱", "株式会社", value)
    without_legal = value.replace("株式会社", "").replace("有限会社", "")
    without_legal = without_legal.replace("・", "")
    return without_legal.casefold()


def upgrade() -> None:
    existing = set(sa.inspect(op.get_bind()).get_table_names())
    if "company_aliases" not in existing:
        op.create_table(
            "company_aliases",
            sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
            sa.Column("company_id", sa.Integer(), nullable=False),
            sa.Column("alias", sa.String(length=200), nullable=False),
            sa.Column("normalized_alias", sa.String(length=200), nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
            sa.ForeignKeyConstraint(["company_id"], ["companies.id"], ondelete="CASCADE"),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint("company_id", "alias", name="uq_company_alias_company_alias"),
        )
        op.create_index(
            "ix_company_aliases_normalized_alias", "company_aliases", ["normalized_alias"], unique=True
        )

    bind = op.get_bind()
    companies = sa.table(
        "companies", sa.column("id", sa.Integer), sa.column("normalized_name", sa.String)
    )
    aliases = sa.table(
        "company_aliases",
        sa.column("company_id", sa.Integer),
        sa.column("alias", sa.String),
        sa.column("normalized_alias", sa.String),
    )
    for normalized_company_name, alias in SEED_ALIASES:
        company_id = bind.execute(
            sa.select(companies.c.id).where(companies.c.normalized_name == normalized_company_name)
        ).scalar_one_or_none()
        if company_id is None:
            continue
        normalized_alias = _normalize_company_name(alias)
        already_present = bind.execute(
            sa.select(aliases.c.company_id).where(aliases.c.normalized_alias == normalized_alias)
        ).first()
        if already_present is not None:
            continue
        bind.execute(
            aliases.insert().values(
                company_id=company_id, alias=alias, normalized_alias=normalized_alias
            )
        )


def downgrade() -> None:
    op.drop_index("ix_company_aliases_normalized_alias", table_name="company_aliases")
    op.drop_table("company_aliases")
