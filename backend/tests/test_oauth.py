import base64
import hashlib

import pytest
from sqlalchemy import select

from app.models import OAuthAuthorizationCode, OAuthToken
from app.services.oauth import (
    DEFAULT_SCOPE,
    OAuthError,
    _locked,
    authenticate_access_token,
    authenticate_client,
    exchange_authorization_code,
    issue_authorization_code,
    refresh_access_token,
    register_client,
    revoke_token,
    valid_redirect_uri,
    validate_scope,
)

RESOURCE = "https://relua.test/mcp"
VERIFIER = "verifier-that-is-long-enough-for-pkce-0123456789"
CHALLENGE = base64.urlsafe_b64encode(hashlib.sha256(VERIFIER.encode("ascii")).digest()).decode("ascii").rstrip("=")


def make_client(db, *, auth_method: str = "none", redirect_uris: list[str] | None = None):
    return register_client(
        db,
        redirect_uris=redirect_uris or ["https://claude.ai/api/mcp/auth_callback"],
        client_name="テストクライアント",
        grant_types=None,
        token_endpoint_auth_method=auth_method,
    )


def connect(db, client, *, resource: str | None = RESOURCE) -> dict:
    code = issue_authorization_code(
        db,
        client=client,
        redirect_uri=client.redirect_uris[0],
        code_challenge=CHALLENGE,
        scope=None,
        resource=resource,
    )
    return exchange_authorization_code(
        db,
        code=code,
        client=client,
        redirect_uri=client.redirect_uris[0],
        code_verifier=VERIFIER,
        resource=resource,
    )


def test_redirect_uris_allow_https_and_loopback_only():
    assert valid_redirect_uri("https://claude.ai/api/mcp/auth_callback")
    assert valid_redirect_uri("http://localhost:33418/oauth/callback")
    assert not valid_redirect_uri("http://example.com/callback")
    assert not valid_redirect_uri("https://example.com/callback#fragment")
    assert not valid_redirect_uri("javascript:alert(1)")


def test_registration_rejects_a_plain_http_callback(db):
    with pytest.raises(OAuthError) as error:
        make_client(db, redirect_uris=["http://example.com/callback"])
    assert error.value.error == "invalid_redirect_uri"


def test_authorization_code_flow_issues_a_usable_access_token(db):
    client, secret = make_client(db)
    assert secret is None

    tokens = connect(db, client)
    assert tokens["token_type"] == "Bearer"
    assert authenticate_access_token(db, tokens["access_token"]) is not None
    assert authenticate_access_token(db, "relua_at_not-a-real-token") is None


def test_refresh_token_has_no_expiry_so_a_connection_survives(db):
    client, _ = make_client(db)
    tokens = connect(db, client)

    refresh = db.scalar(select(OAuthToken).where(OAuthToken.kind == "refresh"))
    assert refresh.expires_at is None
    assert tokens["refresh_token"].startswith("relua_rt_")


def test_wrong_code_verifier_is_rejected(db):
    client, _ = make_client(db)
    code = issue_authorization_code(
        db,
        client=client,
        redirect_uri=client.redirect_uris[0],
        code_challenge=CHALLENGE,
        scope=None,
        resource=RESOURCE,
    )
    with pytest.raises(OAuthError) as error:
        exchange_authorization_code(
            db,
            code=code,
            client=client,
            redirect_uri=client.redirect_uris[0],
            code_verifier="a-different-verifier-that-is-long-enough-01234567",
            resource=RESOURCE,
        )
    assert error.value.error == "invalid_grant"


def test_replaying_an_authorization_code_revokes_the_whole_grant(db):
    client, _ = make_client(db)
    code = issue_authorization_code(
        db,
        client=client,
        redirect_uri=client.redirect_uris[0],
        code_challenge=CHALLENGE,
        scope=None,
        resource=RESOURCE,
    )
    tokens = exchange_authorization_code(
        db,
        code=code,
        client=client,
        redirect_uri=client.redirect_uris[0],
        code_verifier=VERIFIER,
        resource=RESOURCE,
    )
    with pytest.raises(OAuthError):
        exchange_authorization_code(
            db,
            code=code,
            client=client,
            redirect_uri=client.redirect_uris[0],
            code_verifier=VERIFIER,
            resource=RESOURCE,
        )
    assert authenticate_access_token(db, tokens["access_token"]) is None


def test_refresh_rotates_and_reusing_the_old_token_disconnects(db):
    client, _ = make_client(db)
    first = connect(db, client)

    second = refresh_access_token(db, refresh_token=first["refresh_token"], client=client, resource=RESOURCE)
    assert second["refresh_token"] != first["refresh_token"]
    assert authenticate_access_token(db, second["access_token"]) is not None

    with pytest.raises(OAuthError) as error:
        refresh_access_token(db, refresh_token=first["refresh_token"], client=client, resource=RESOURCE)
    assert error.value.error == "invalid_grant"
    assert authenticate_access_token(db, second["access_token"]) is None


def test_a_token_request_for_another_resource_is_refused(db):
    client, _ = make_client(db)
    with pytest.raises(OAuthError) as error:
        connect(db, client, resource="https://attacker.example/mcp")
    assert error.value.error == "invalid_target"


def test_trailing_slash_on_the_resource_still_matches(db):
    client, _ = make_client(db)
    assert connect(db, client, resource="https://relua.test/mcp/")["access_token"]


def test_confidential_client_must_present_its_secret(db):
    client, secret = make_client(db, auth_method="client_secret_post")
    assert secret is not None
    assert authenticate_client(db, client.client_id, secret).client_id == client.client_id

    with pytest.raises(OAuthError) as error:
        authenticate_client(db, client.client_id, "wrong-secret")
    assert error.value.status_code == 401


def test_a_code_issued_to_one_client_cannot_be_used_by_another(db):
    first, _ = make_client(db)
    second, _ = make_client(db)
    code = issue_authorization_code(
        db,
        client=first,
        redirect_uri=first.redirect_uris[0],
        code_challenge=CHALLENGE,
        scope=None,
        resource=RESOURCE,
    )
    with pytest.raises(OAuthError):
        exchange_authorization_code(
            db,
            code=code,
            client=second,
            redirect_uri=second.redirect_uris[0],
            code_verifier=VERIFIER,
            resource=RESOURCE,
        )


def test_revoking_the_refresh_token_kills_the_access_token(db):
    client, _ = make_client(db)
    tokens = connect(db, client)

    revoke_token(db, token=tokens["refresh_token"], client=client)
    assert authenticate_access_token(db, tokens["access_token"]) is None
    with pytest.raises(OAuthError):
        refresh_access_token(db, refresh_token=tokens["refresh_token"], client=client, resource=RESOURCE)


def test_a_non_ascii_code_verifier_is_an_oauth_error_not_a_crash(db):
    """`code_verifier.encode("ascii")` used to raise UnicodeEncodeError, surfacing as an unauthenticated 500."""
    client, _ = make_client(db)
    code = issue_authorization_code(
        db,
        client=client,
        redirect_uri=client.redirect_uris[0],
        code_challenge=CHALLENGE,
        scope=None,
        resource=RESOURCE,
    )
    with pytest.raises(OAuthError) as error:
        exchange_authorization_code(
            db,
            code=code,
            client=client,
            redirect_uri=client.redirect_uris[0],
            code_verifier="コードベリファイア" * 6,
            resource=RESOURCE,
        )
    assert error.value.error == "invalid_grant"
    assert error.value.status_code == 400


def test_a_code_verifier_outside_the_rfc_charset_is_rejected(db):
    """RFC 7636 §4.1 limits the verifier to ALPHA / DIGIT / "-" / "." / "_" / "~"."""
    client, _ = make_client(db)
    for verifier in ("+" * 43, "/" * 43, "a b" + "c" * 40, "a" * 42, "a" * 129):
        code = issue_authorization_code(
            db,
            client=client,
            redirect_uri=client.redirect_uris[0],
            code_challenge=CHALLENGE,
            scope=None,
            resource=RESOURCE,
        )
        with pytest.raises(OAuthError) as error:
            exchange_authorization_code(
                db,
                code=code,
                client=client,
                redirect_uri=client.redirect_uris[0],
                code_verifier=verifier,
                resource=RESOURCE,
            )
        assert error.value.error == "invalid_grant"


def test_a_token_request_that_omits_the_redirect_uri_is_refused(db):
    """The column is NOT NULL, so skipping the comparison when the client omits it checked nothing at all."""
    client, _ = make_client(db)
    code = issue_authorization_code(
        db,
        client=client,
        redirect_uri=client.redirect_uris[0],
        code_challenge=CHALLENGE,
        scope=None,
        resource=RESOURCE,
    )
    with pytest.raises(OAuthError) as error:
        exchange_authorization_code(
            db, code=code, client=client, redirect_uri=None, code_verifier=VERIFIER, resource=RESOURCE
        )
    assert error.value.error == "invalid_grant"


def test_a_token_request_with_another_redirect_uri_is_refused(db):
    client, _ = make_client(db)
    code = issue_authorization_code(
        db,
        client=client,
        redirect_uri=client.redirect_uris[0],
        code_challenge=CHALLENGE,
        scope=None,
        resource=RESOURCE,
    )
    with pytest.raises(OAuthError) as error:
        exchange_authorization_code(
            db,
            code=code,
            client=client,
            redirect_uri="https://attacker.example/cb",
            code_verifier=VERIFIER,
            resource=RESOURCE,
        )
    assert error.value.error == "invalid_grant"


def test_only_the_single_supported_scope_can_be_requested():
    assert validate_scope(None) == DEFAULT_SCOPE
    assert validate_scope("") == DEFAULT_SCOPE
    assert validate_scope(DEFAULT_SCOPE) == DEFAULT_SCOPE

    for requested in ("openid", f"{DEFAULT_SCOPE} admin", "x" * 300):
        with pytest.raises(OAuthError) as error:
            validate_scope(requested)
        assert error.value.error == "invalid_scope"


def test_an_unknown_scope_never_reaches_the_column(db):
    """String(200) would make an over-long scope a PostgreSQL DataError, i.e. an unauthenticated 500."""
    client, _ = make_client(db)
    with pytest.raises(OAuthError) as error:
        issue_authorization_code(
            db,
            client=client,
            redirect_uri=client.redirect_uris[0],
            code_challenge=CHALLENGE,
            scope="x" * 300,
            resource=RESOURCE,
        )
    assert error.value.error == "invalid_scope"


def test_an_access_token_without_the_required_scope_does_not_authenticate(db):
    """The MCP write tools advertise scopes ["mcp"]; the stored scope has to be checked, not just recorded."""
    client, _ = make_client(db)
    tokens = connect(db, client)
    record = authenticate_access_token(db, tokens["access_token"])
    assert record is not None and record.scope == DEFAULT_SCOPE

    assert authenticate_access_token(db, tokens["access_token"], required_scope="admin") is None

    # A grant that predates the allowlist, or one narrowed later, must not open a tool it never covered.
    record.scope = "read"
    db.commit()
    assert authenticate_access_token(db, tokens["access_token"]) is None


def test_the_authorization_code_is_read_under_a_row_lock_where_one_exists(db):
    """Two concurrent exchanges of one leaked code must not both pass the `consumed_at IS NULL` check."""
    statement = select(OAuthAuthorizationCode).where(OAuthAuthorizationCode.code_hash == "x")
    compiled = str(_locked(db, statement).compile(db.get_bind()))
    if db.get_bind().dialect.name == "postgresql":
        assert "FOR UPDATE" in compiled
    else:
        # SQLite has no FOR UPDATE and serialises writes on a database-wide lock instead.
        assert "FOR UPDATE" not in compiled
