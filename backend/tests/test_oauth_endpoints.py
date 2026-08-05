import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app import main
from app.api import oauth as oauth_api
from app.db import Base, get_db
from tests.test_oauth import CHALLENGE, VERIFIER

PASSWORD = "test-operator-password-0001"
REDIRECT_URI = "https://claude.ai/api/mcp/auth_callback"


@pytest.fixture(scope="module")
def client():
    """One client for the whole module: the MCP session manager refuses to run a second time in a process."""
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    session_factory = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)

    def override_db():
        with session_factory() as session:
            yield session

    with pytest.MonkeyPatch.context() as patch:
        # The bearer check runs in middleware, where dependency overrides do not reach.
        patch.setattr(main, "SessionLocal", session_factory)
        patch.setattr(oauth_api, "enforce_login_rate_limit", lambda identifier: None)
        patch.setattr(oauth_api, "clear_login_rate_limit", lambda identifier: None)
        patch.setattr(oauth_api, "enforce_registration_rate_limit", lambda identifier: None)
        main.app.dependency_overrides[get_db] = override_db
        with TestClient(main.app) as test_client:
            yield test_client
        main.app.dependency_overrides.clear()
    Base.metadata.drop_all(engine)


def register(client, **overrides) -> dict:
    payload = {"redirect_uris": [REDIRECT_URI], "client_name": "Claude", "token_endpoint_auth_method": "none"}
    response = client.post("/oauth/register", json=payload | overrides)
    assert response.status_code == 201, response.text
    return response.json()


def authorize(client, client_id: str, **overrides) -> object:
    form = {
        "password": PASSWORD,
        "client_id": client_id,
        "redirect_uri": REDIRECT_URI,
        "response_type": "code",
        "code_challenge": CHALLENGE,
        "code_challenge_method": "S256",
        "state": "state-value",
        "resource": "https://relua.test/mcp",
    }
    return client.post("/oauth/authorize", data=form | overrides, follow_redirects=False)


def code_from(response) -> str:
    location = response.headers["location"]
    assert location.startswith(f"{REDIRECT_URI}?")
    query = dict(pair.split("=", 1) for pair in location.split("?", 1)[1].split("&"))
    assert query["state"] == "state-value"
    return query["code"]


def test_discovery_documents_point_at_the_public_url(client):
    resource = client.get("/.well-known/oauth-protected-resource/mcp").json()
    assert resource["resource"] == "https://relua.test/mcp"
    assert resource["authorization_servers"] == ["https://relua.test"]

    server = client.get("/.well-known/oauth-authorization-server").json()
    assert server["issuer"] == "https://relua.test"
    assert server["registration_endpoint"] == "https://relua.test/oauth/register"
    assert server["code_challenge_methods_supported"] == ["S256"]


def test_unauthenticated_mcp_request_advertises_the_metadata_url(client):
    response = client.post("/mcp", json={}, follow_redirects=False)
    assert response.status_code == 401
    assert "resource_metadata=" in response.headers["www-authenticate"]
    assert "/.well-known/oauth-protected-resource/mcp" in response.headers["www-authenticate"]


def test_registration_refuses_a_non_https_callback(client):
    response = client.post("/oauth/register", json={"redirect_uris": ["http://example.com/cb"]})
    assert response.status_code == 400
    assert response.json()["error"] == "invalid_redirect_uri"


def test_browser_login_yields_a_token_that_opens_the_mcp_endpoint(client):
    registration = register(client)

    page = client.get(
        "/oauth/authorize",
        params={
            "response_type": "code",
            "client_id": registration["client_id"],
            "redirect_uri": REDIRECT_URI,
            "code_challenge": CHALLENGE,
            "code_challenge_method": "S256",
            "state": "state-value",
        },
    )
    assert page.status_code == 200
    assert "運営者パスワード" in page.text

    rejected = authorize(client, registration["client_id"], password="wrong-password")
    assert rejected.status_code == 401
    assert "パスワードが正しくありません" in rejected.text

    granted = authorize(client, registration["client_id"])
    assert granted.status_code == 302

    tokens = client.post(
        "/oauth/token",
        data={
            "grant_type": "authorization_code",
            "code": code_from(granted),
            "redirect_uri": REDIRECT_URI,
            "code_verifier": VERIFIER,
            "client_id": registration["client_id"],
            "resource": "https://relua.test/mcp",
        },
    )
    assert tokens.status_code == 200, tokens.text
    access_token = tokens.json()["access_token"]

    accepted = client.post(
        "/mcp", json={}, headers={"Authorization": f"Bearer {access_token}"}, follow_redirects=False
    )
    assert accepted.status_code != 307
    assert accepted.status_code != 401


def test_a_revoked_token_stops_opening_the_mcp_endpoint(client):
    registration = register(client)
    granted = authorize(client, registration["client_id"])
    tokens = client.post(
        "/oauth/token",
        data={
            "grant_type": "authorization_code",
            "code": code_from(granted),
            "redirect_uri": REDIRECT_URI,
            "code_verifier": VERIFIER,
            "client_id": registration["client_id"],
        },
    ).json()

    revoked = client.post(
        "/oauth/revoke",
        data={"token": tokens["refresh_token"], "client_id": registration["client_id"]},
    )
    assert revoked.status_code == 200

    response = client.post("/mcp", json={}, headers={"Authorization": f"Bearer {tokens['access_token']}"})
    assert response.status_code == 401


def test_authorize_rejects_a_callback_the_client_never_registered(client):
    registration = register(client)
    response = authorize(client, registration["client_id"], redirect_uri="https://attacker.example/cb")
    assert response.status_code == 400
    assert "redirect_uri" in response.text


def test_authorize_without_pkce_redirects_an_error_instead_of_asking_for_the_password(client):
    registration = register(client)
    response = client.get(
        "/oauth/authorize",
        params={
            "response_type": "code",
            "client_id": registration["client_id"],
            "redirect_uri": REDIRECT_URI,
            "state": "state-value",
        },
        follow_redirects=False,
    )
    assert response.status_code == 302
    assert "error=invalid_request" in response.headers["location"]


def test_extra_query_parameters_never_become_form_fields(client):
    registration = register(client)
    response = client.get(
        "/oauth/authorize",
        params={
            "response_type": "code",
            "client_id": registration["client_id"],
            "redirect_uri": REDIRECT_URI,
            "code_challenge": CHALLENGE,
            "password": "injected",
            "unexpected": "value",
        },
    )
    assert response.status_code == 200
    assert "injected" not in response.text
    assert "unexpected" not in response.text


def test_an_unknown_client_never_reaches_the_password_form(client):
    response = client.get(
        "/oauth/authorize",
        params={"response_type": "code", "client_id": "unknown", "redirect_uri": REDIRECT_URI},
    )
    assert response.status_code == 400
    assert "運営者パスワード" not in response.text


def test_static_operator_token_still_works(client):
    response = client.post(
        "/mcp",
        json={},
        headers={"Authorization": "Bearer local-development-mcp-token"},
        follow_redirects=False,
    )
    assert response.status_code != 307
    assert response.status_code != 401
