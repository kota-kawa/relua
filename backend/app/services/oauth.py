"""OAuth 2.1 authorization server backing the remote MCP endpoint.

Remote clients such as ChatGPT and Claude cannot be handed a static token: they discover the endpoint,
register themselves, and send the operator to a browser login. This module implements the smallest server
that satisfies that flow — dynamic registration (RFC 7591), authorization code with mandatory PKCE, resource
indicators (RFC 8707), refresh with rotation, and revocation (RFC 7009).

There is exactly one identity, the operator, proven by MCP_OPERATOR_PASSWORD. Registration is open because
the clients mint their own client_id, so a registered client is not a trusted one; the password login is what
actually grants access.
"""

import base64
import hashlib
import hmac
import re
import secrets
import uuid
from datetime import UTC, datetime, timedelta
from urllib.parse import urlparse

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.models import OAuthAuthorizationCode, OAuthClient, OAuthToken
from app.security import new_secret, token_hash

#: The single scope this server issues. MCP does not define scopes, and the operator has full access anyway.
DEFAULT_SCOPE = "mcp"
SUPPORTED_GRANT_TYPES = ("authorization_code", "refresh_token")
LOOPBACK_HOSTS = {"localhost", "127.0.0.1", "::1"}

#: RFC 7636 §4.1 defines code_verifier as 43-128 characters of ALPHA / DIGIT / "-" / "." / "_" / "~".
CODE_VERIFIER_PATTERN = re.compile(r"\A[A-Za-z0-9\-._~]{43,128}\Z")


class OAuthError(Exception):
    """An error to report using the OAuth error format, either as JSON or as a redirect query."""

    def __init__(self, error: str, description: str, status_code: int = 400) -> None:
        super().__init__(description)
        self.error = error
        self.description = description
        self.status_code = status_code


def _now() -> datetime:
    return datetime.now(UTC)


def _as_utc(value: datetime | None) -> datetime | None:
    """Read a stored timestamp as UTC-aware. SQLite drops the offset, so naive values are known to be UTC."""
    if value is not None and value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value


def _expired(value: datetime | None) -> bool:
    moment = _as_utc(value)
    return moment is not None and moment <= _now()


def normalize_resource(value: str | None) -> str | None:
    return value.rstrip("/") if value else None


def valid_redirect_uri(value: str) -> bool:
    """Accept https callbacks, plus loopback http for locally running clients such as mcp-remote."""
    if len(value) > 2048:
        return False
    parsed = urlparse(value)
    if parsed.fragment or not parsed.hostname:
        return False
    if parsed.scheme == "https":
        return True
    return parsed.scheme == "http" and parsed.hostname.lower() in LOOPBACK_HOSTS


def register_client(
    db: Session,
    *,
    redirect_uris: list[str],
    client_name: str,
    grant_types: list[str] | None,
    token_endpoint_auth_method: str,
) -> tuple[OAuthClient, str | None]:
    if not redirect_uris:
        raise OAuthError("invalid_redirect_uri", "redirect_uris は1つ以上必要です")
    invalid = [uri for uri in redirect_uris if not valid_redirect_uri(uri)]
    if invalid:
        raise OAuthError(
            "invalid_redirect_uri",
            "redirect_uris にはhttps、またはループバックホストのhttpのみ指定できます",
        )
    if token_endpoint_auth_method not in {"none", "client_secret_post", "client_secret_basic"}:
        raise OAuthError("invalid_client_metadata", "token_endpoint_auth_method が未対応です")

    requested = grant_types or list(SUPPORTED_GRANT_TYPES)
    unsupported = [grant for grant in requested if grant not in SUPPORTED_GRANT_TYPES]
    if unsupported:
        raise OAuthError("invalid_client_metadata", "対応していない grant_types が含まれています")

    secret = None if token_endpoint_auth_method == "none" else new_secret("relua_cs")
    client = OAuthClient(
        client_id=secrets.token_urlsafe(24),
        client_secret_hash=token_hash(secret) if secret else None,
        client_name=client_name[:200] or "unknown",
        redirect_uris=redirect_uris,
        grant_types=requested,
        token_endpoint_auth_method=token_endpoint_auth_method,
    )
    db.add(client)
    db.commit()
    return client, secret


def get_client(db: Session, client_id: str | None) -> OAuthClient:
    client = db.get(OAuthClient, client_id) if client_id else None
    if client is None:
        raise OAuthError("invalid_client", "client_id が登録されていません", status_code=401)
    return client


def authenticate_client(db: Session, client_id: str | None, client_secret: str | None) -> OAuthClient:
    client = get_client(db, client_id)
    if client.client_secret_hash is None:
        return client
    if not client_secret or not hmac.compare_digest(token_hash(client_secret), client.client_secret_hash):
        raise OAuthError("invalid_client", "client_secret が一致しません", status_code=401)
    return client


def validate_scope(scope: str | None) -> str:
    """Allowlist the requested scope and normalise it to the single scope this server issues.

    The value used to be stored raw into a String(200) column, so a long scope was a PostgreSQL DataError
    — an unauthenticated 500 — and an unknown scope was recorded as if it had been granted while nothing
    ever read it back. Refusing anything but DEFAULT_SCOPE here means what is stored is also what is
    enforced, so a future read-only scope cannot be silently upgraded to write access.
    """
    if not scope:
        return DEFAULT_SCOPE
    if any(requested != DEFAULT_SCOPE for requested in scope.split()):
        raise OAuthError("invalid_scope", f"scope は {DEFAULT_SCOPE} のみ対応しています")
    return DEFAULT_SCOPE


def check_resource(resource: str | None) -> str | None:
    """Reject a token request aimed at some other server, so a token minted here cannot be replayed elsewhere."""
    expected = get_settings().resource_identifier
    normalized = normalize_resource(resource)
    if normalized is not None and normalized != normalize_resource(expected):
        raise OAuthError("invalid_target", "resource がこのMCPサーバーと一致しません")
    return expected


def issue_authorization_code(
    db: Session,
    *,
    client: OAuthClient,
    redirect_uri: str,
    code_challenge: str,
    scope: str | None,
    resource: str | None,
) -> str:
    code = new_secret("relua_ac")
    settings = get_settings()
    db.add(
        OAuthAuthorizationCode(
            code_hash=token_hash(code),
            client_id=client.client_id,
            redirect_uri=redirect_uri,
            code_challenge=code_challenge,
            scope=validate_scope(scope),
            resource=resource,
            expires_at=_now() + timedelta(seconds=settings.mcp_authorization_code_ttl_seconds),
        )
    )
    db.commit()
    return code


def _verify_pkce(code_verifier: str | None, code_challenge: str) -> None:
    # The charset is checked, not just the length: `.encode("ascii")` below raised UnicodeEncodeError on
    # any non-ASCII verifier, which surfaced as an unauthenticated 500 instead of an OAuth error body.
    if not code_verifier or not CODE_VERIFIER_PATTERN.match(code_verifier):
        raise OAuthError("invalid_grant", "code_verifier が不正です")
    digest = hashlib.sha256(code_verifier.encode("ascii")).digest()
    computed = base64.urlsafe_b64encode(digest).decode("ascii").rstrip("=")
    if not hmac.compare_digest(computed, code_challenge):
        raise OAuthError("invalid_grant", "code_verifier が code_challenge と一致しません")


def _locked(db: Session, statement):
    """Add a row lock to a SELECT that is about to be read, decided on, and written back.

    Exchanging an authorization code and rotating a refresh token both read a row, check that it has not
    been used, and only later write that it has. Without a lock two concurrent requests carrying the same
    leaked code both see `consumed_at IS NULL`, both mint an independent grant, and the OAuth 2.1 reuse
    detection in the caller never fires — the attacker ends up with a grant the operator never learns
    about. SQLite has no FOR UPDATE (its writes already serialise on a database-wide lock), so the clause
    is added only where it exists.
    """
    if db.get_bind().dialect.name == "postgresql":
        return statement.with_for_update()
    return statement


def revoke_grant(db: Session, grant_id: str) -> None:
    tokens = db.scalars(select(OAuthToken).where(OAuthToken.grant_id == grant_id)).all()
    for token in tokens:
        if token.revoked_at is None:
            token.revoked_at = _now()
    db.commit()


def _issue_token_pair(db: Session, *, client_id: str, grant_id: str, scope: str | None, resource: str | None) -> dict:
    settings = get_settings()
    access = new_secret("relua_at")
    refresh = new_secret("relua_rt")
    expires_in = settings.mcp_access_token_ttl_seconds
    refresh_expires_at = (
        _now() + timedelta(days=settings.mcp_refresh_token_ttl_days) if settings.mcp_refresh_token_ttl_days else None
    )
    db.add_all(
        [
            OAuthToken(
                token_hash=token_hash(access),
                kind="access",
                grant_id=grant_id,
                client_id=client_id,
                scope=scope,
                resource=resource,
                expires_at=_now() + timedelta(seconds=expires_in),
            ),
            OAuthToken(
                token_hash=token_hash(refresh),
                kind="refresh",
                grant_id=grant_id,
                client_id=client_id,
                scope=scope,
                resource=resource,
                expires_at=refresh_expires_at,
            ),
        ]
    )
    db.commit()
    return {
        "access_token": access,
        "token_type": "Bearer",
        "expires_in": expires_in,
        "refresh_token": refresh,
        "scope": scope or DEFAULT_SCOPE,
    }


def exchange_authorization_code(
    db: Session,
    *,
    code: str,
    client: OAuthClient,
    redirect_uri: str | None,
    code_verifier: str | None,
    resource: str | None,
) -> dict:
    record = db.scalar(
        _locked(db, select(OAuthAuthorizationCode).where(OAuthAuthorizationCode.code_hash == token_hash(code)))
    )
    if record is None or record.client_id != client.client_id:
        raise OAuthError("invalid_grant", "認可コードが無効です")
    if record.consumed_at is not None:
        # A replayed code means the code leaked, so everything issued from it is withdrawn.
        if record.grant_id:
            revoke_grant(db, record.grant_id)
        raise OAuthError("invalid_grant", "認可コードは既に使用されています")
    if _expired(record.expires_at):
        raise OAuthError("invalid_grant", "認可コードの有効期限が切れています")
    # Compared unconditionally: the column is NOT NULL, so a client that simply omits the parameter used
    # to skip the check entirely, which is exactly what a stolen code replayed from elsewhere would do.
    if redirect_uri != record.redirect_uri:
        raise OAuthError("invalid_grant", "redirect_uri が認可時と一致しません")
    _verify_pkce(code_verifier, record.code_challenge)
    check_resource(resource)

    grant_id = str(uuid.uuid4())
    record.consumed_at = _now()
    record.grant_id = grant_id
    db.commit()
    return _issue_token_pair(
        db,
        client_id=client.client_id,
        grant_id=grant_id,
        scope=record.scope,
        resource=record.resource or get_settings().resource_identifier,
    )


def refresh_access_token(db: Session, *, refresh_token: str, client: OAuthClient, resource: str | None) -> dict:
    record = db.scalar(_locked(db, select(OAuthToken).where(OAuthToken.token_hash == token_hash(refresh_token))))
    if record is None or record.kind != "refresh" or record.client_id != client.client_id:
        raise OAuthError("invalid_grant", "リフレッシュトークンが無効です")
    if record.revoked_at is not None:
        # Rotation means a used refresh token is revoked; seeing it again implies a copy is in the wild.
        revoke_grant(db, record.grant_id)
        raise OAuthError("invalid_grant", "リフレッシュトークンは既に使用されています")
    if _expired(record.expires_at):
        raise OAuthError("invalid_grant", "リフレッシュトークンの有効期限が切れています")
    check_resource(resource)

    record.revoked_at = _now()
    db.commit()
    return _issue_token_pair(
        db,
        client_id=client.client_id,
        grant_id=record.grant_id,
        scope=record.scope,
        resource=record.resource,
    )


def revoke_token(db: Session, *, token: str, client: OAuthClient) -> None:
    """Revoke a token and, when it is a refresh token, the whole grant it belongs to."""
    record = db.scalar(select(OAuthToken).where(OAuthToken.token_hash == token_hash(token)))
    if record is None or record.client_id != client.client_id:
        return
    if record.kind == "refresh":
        revoke_grant(db, record.grant_id)
        return
    if record.revoked_at is None:
        record.revoked_at = _now()
        db.commit()


def authenticate_access_token(db: Session, token: str, *, required_scope: str = DEFAULT_SCOPE) -> OAuthToken | None:
    """Resolve a bearer token, or None when it is unknown, revoked, expired, or too narrow.

    The scope is checked, not just recorded: the MCP write tools advertise `scopes: ["mcp"]`, so a token
    that was never granted that scope must not open them. Today only DEFAULT_SCOPE is ever issued, which
    makes this a no-op — but it is the check that stops a narrower scope, added later, from carrying full
    write access simply because nothing looked at the column.
    """
    record = db.scalar(select(OAuthToken).where(OAuthToken.token_hash == token_hash(token)))
    if record is None or record.kind != "access" or record.revoked_at is not None or _expired(record.expires_at):
        return None
    if required_scope not in (record.scope or "").split():
        return None
    return record


def purge_expired(db: Session) -> int:
    """Drop authorization codes that can no longer be exchanged. Tokens are kept for their audit value."""
    stale = db.scalars(select(OAuthAuthorizationCode).where(OAuthAuthorizationCode.expires_at < _now())).all()
    for record in stale:
        db.delete(record)
    db.commit()
    return len(stale)
