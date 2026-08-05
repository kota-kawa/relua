"""Add OAuth tables for remote MCP client authorization."""

import sqlalchemy as sa

from alembic import op

revision = "20260805_0004"
down_revision = "20260730_0003"
branch_labels = None
depends_on = None


# Revision 0001 builds a fresh database from the live models, so these tables already exist there.
# Only a database created before this revision needs them, hence the guard, as in revision 0002.
def _missing_tables() -> set[str]:
    existing = set(sa.inspect(op.get_bind()).get_table_names())
    return {"oauth_clients", "oauth_authorization_codes", "oauth_tokens"} - existing


def upgrade() -> None:
    missing = _missing_tables()
    if "oauth_clients" in missing:
        op.create_table(
            "oauth_clients",
            sa.Column("client_id", sa.String(64), primary_key=True),
            sa.Column("client_secret_hash", sa.String(64), nullable=True),
            sa.Column("client_name", sa.String(200), nullable=False, server_default="unknown"),
            sa.Column("redirect_uris", sa.JSON(), nullable=False),
            sa.Column("grant_types", sa.JSON(), nullable=False),
            sa.Column("token_endpoint_auth_method", sa.String(32), nullable=False, server_default="none"),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        )
    if "oauth_authorization_codes" in missing:
        op.create_table(
            "oauth_authorization_codes",
            sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
            sa.Column("code_hash", sa.String(64), nullable=False, unique=True),
            sa.Column(
                "client_id",
                sa.String(64),
                sa.ForeignKey("oauth_clients.client_id", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column("redirect_uri", sa.String(2048), nullable=False),
            sa.Column("code_challenge", sa.String(128), nullable=False),
            sa.Column("scope", sa.String(200), nullable=True),
            sa.Column("resource", sa.String(2048), nullable=True),
            sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("consumed_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("grant_id", sa.String(36), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        )
    if "oauth_tokens" in missing:
        op.create_table(
            "oauth_tokens",
            sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
            sa.Column("token_hash", sa.String(64), nullable=False, unique=True),
            sa.Column("kind", sa.String(16), nullable=False),
            sa.Column("grant_id", sa.String(36), nullable=False),
            sa.Column(
                "client_id",
                sa.String(64),
                sa.ForeignKey("oauth_clients.client_id", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column("scope", sa.String(200), nullable=True),
            sa.Column("resource", sa.String(2048), nullable=True),
            sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        )
        op.create_index("ix_oauth_tokens_grant", "oauth_tokens", ["grant_id", "kind"])


def downgrade() -> None:
    op.drop_index("ix_oauth_tokens_grant", table_name="oauth_tokens")
    op.drop_table("oauth_tokens")
    op.drop_table("oauth_authorization_codes")
    op.drop_table("oauth_clients")
