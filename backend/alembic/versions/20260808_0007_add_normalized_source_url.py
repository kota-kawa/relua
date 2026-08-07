"""Add a normalized opportunity source URL for duplicate detection."""

import re
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

import sqlalchemy as sa

from alembic import op

revision = "20260808_0007"
down_revision = "20260807_0006"
branch_labels = None
depends_on = None

TRACKING_QUERY_KEYS = {
    "fbclid", "gclid", "mc_cid", "mc_eid", "ref_src", "utm_campaign", "utm_content",
    "utm_creative_format", "utm_id", "utm_marketing_tactic", "utm_medium", "utm_source",
    "utm_source_platform", "utm_term",
}


def _normalize(value: str) -> str:
    parsed = urlsplit(value.strip())
    scheme = parsed.scheme.lower()
    host = (parsed.hostname or "").lower()
    port = parsed.port
    netloc = host if port is None or (scheme == "https" and port == 443) else f"{host}:{port}"
    path = re.sub(r"/{2,}", "/", parsed.path or "/")
    if path != "/":
        path = path.rstrip("/")
    query = urlencode(
        sorted(
            (key, item)
            for key, item in parse_qsl(parsed.query, keep_blank_values=True)
            if key.casefold() not in TRACKING_QUERY_KEYS
        ),
        doseq=True,
    )
    return urlunsplit((scheme, netloc, path, query, ""))


def _has_column() -> bool:
    return "normalized_source_url" in {
        column["name"] for column in sa.inspect(op.get_bind()).get_columns("opportunities")
    }


def upgrade() -> None:
    # Revision 0001 creates fresh databases from live metadata, so only upgraded databases need
    # the column and index added here.
    if _has_column():
        return
    op.add_column("opportunities", sa.Column("normalized_source_url", sa.String(length=2048), nullable=True))
    opportunities = sa.table(
        "opportunities",
        sa.column("id", sa.String),
        sa.column("source_url", sa.String),
        sa.column("normalized_source_url", sa.String),
    )
    bind = op.get_bind()
    rows = bind.execute(sa.select(opportunities.c.id, opportunities.c.source_url)).all()
    for opportunity_id, source_url in rows:
        if source_url:
            bind.execute(
                opportunities.update()
                .where(opportunities.c.id == opportunity_id)
                .values(normalized_source_url=_normalize(source_url))
            )
    op.create_index(
        "ix_opportunities_normalized_source_url",
        "opportunities",
        ["normalized_source_url"],
    )


def downgrade() -> None:
    if _has_column():
        op.drop_index("ix_opportunities_normalized_source_url", table_name="opportunities")
        op.drop_column("opportunities", "normalized_source_url")
