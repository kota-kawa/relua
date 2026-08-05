"""Inspect and disconnect MCP clients that hold OAuth grants.

Refresh tokens do not expire by default, so this is the way to cut a connection off: revoking a grant
invalidates every token that came from one browser login.
"""

import argparse
from datetime import datetime

from sqlalchemy import select

from app.db import SessionLocal
from app.models import OAuthClient, OAuthToken
from app.services.oauth import purge_expired, revoke_grant


def _format(moment: datetime | None) -> str:
    return moment.isoformat(timespec="seconds") if moment else "-"


def list_grants() -> list[tuple[str, str, str, bool]]:
    with SessionLocal() as db:
        rows = db.execute(
            select(OAuthToken, OAuthClient)
            .join(OAuthClient, OAuthClient.client_id == OAuthToken.client_id)
            .where(OAuthToken.kind == "refresh")
            .order_by(OAuthToken.created_at)
        ).all()
        return [
            (token.grant_id, client.client_name, _format(token.created_at), token.revoked_at is None)
            for token, client in rows
        ]


def run() -> None:
    parser = argparse.ArgumentParser(description="MCPのOAuth接続を確認・失効します")
    subcommands = parser.add_subparsers(dest="command")
    subcommands.add_parser("list", help="接続中のクライアントを一覧表示します")
    revoke = subcommands.add_parser("revoke", help="指定した接続を失効させます")
    revoke.add_argument("grant_id")
    subcommands.add_parser("purge", help="期限切れの認可コードを削除します")
    args = parser.parse_args()

    if args.command == "revoke":
        with SessionLocal() as db:
            revoke_grant(db, args.grant_id)
        print(f"revoked={args.grant_id}")
        return
    if args.command == "purge":
        with SessionLocal() as db:
            print(f"purged={purge_expired(db)}")
        return

    for grant_id, client_name, created_at, active in list_grants():
        print(f"{'active ' if active else 'revoked'}  {grant_id}  {created_at}  {client_name}")


if __name__ == "__main__":
    run()
