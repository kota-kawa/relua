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
INITIALIZE_REQUEST = {
    "jsonrpc": "2.0",
    "id": 1,
    "method": "initialize",
    "params": {
        "protocolVersion": "2025-06-18",
        "capabilities": {},
        "clientInfo": {"name": "endpoint-test", "version": "1.0"},
    },
}


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
    assert response.headers["www-authenticate"] == (
        'Bearer resource_metadata="https://relua.test/.well-known/oauth-protected-resource/mcp", scope="mcp"'
    )


def test_oauth_clients_can_discover_tools_before_login(client):
    initialized = client.post(
        "/mcp",
        json=INITIALIZE_REQUEST,
        headers={"Host": "relua.test", "Accept": "application/json, text/event-stream"},
    )
    assert initialized.status_code == 200, initialized.text

    listed = client.post(
        "/mcp",
        json={"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}},
        headers={"Host": "relua.test", "Accept": "application/json, text/event-stream"},
    )
    assert listed.status_code == 200, listed.text
    tools = {tool["name"]: tool for tool in listed.json()["result"]["tools"]}
    assert tools["search_opportunity"]["securitySchemes"] == [{"type": "noauth"}]
    assert tools["get_master_values"]["securitySchemes"] == [{"type": "noauth"}]
    assert tools["get_opportunity"]["securitySchemes"] == [{"type": "noauth"}]
    assert tools["add_opportunity"]["securitySchemes"] == [{"type": "oauth2", "scopes": ["mcp"]}]
    assert tools["update_opportunity"]["securitySchemes"] == [{"type": "oauth2", "scopes": ["mcp"]}]
    assert tools["validate_opportunity"]["securitySchemes"] == [{"type": "oauth2", "scopes": ["mcp"]}]
    assert tools["get_collection_queue"]["securitySchemes"] == [{"type": "oauth2", "scopes": ["mcp"]}]


def test_oauth_clients_can_send_chatgpt_origin(client):
    response = client.post(
        "/mcp",
        json=INITIALIZE_REQUEST,
        headers={
            "Authorization": "Bearer local-development-mcp-token",
            "Host": "relua.test",
            "Origin": "https://chatgpt.com",
            "Accept": "application/json, text/event-stream",
        },
    )
    assert response.status_code == 200, response.text


def test_public_read_tool_and_protected_write_tool_have_different_access(client):
    read_call = client.post(
        "/mcp",
        json={
            "jsonrpc": "2.0",
            "id": 3,
            "method": "tools/call",
            "params": {"name": "search_opportunity", "arguments": {"query": ""}},
        },
        headers={"Host": "relua.test", "Accept": "application/json, text/event-stream"},
    )
    assert read_call.status_code == 200, read_call.text

    fetch_call = client.post(
        "/mcp",
        json={
            "jsonrpc": "2.0",
            "id": 4,
            "method": "tools/call",
            "params": {"name": "get_opportunity", "arguments": {"reference": "ZZZZZZZZ"}},
        },
        headers={"Host": "relua.test", "Accept": "application/json, text/event-stream"},
    )
    assert fetch_call.status_code == 200, fetch_call.text

    write_call = client.post(
        "/mcp",
        json={
            "jsonrpc": "2.0",
            "id": 5,
            "method": "tools/call",
            "params": {"name": "add_opportunity", "arguments": {}},
        },
        headers={"Host": "relua.test", "Accept": "application/json, text/event-stream"},
    )
    assert write_call.status_code == 401

    # A dry run reads nothing back, but it walks the write path, so it stays behind the login.
    dry_run_call = client.post(
        "/mcp",
        json={
            "jsonrpc": "2.0",
            "id": 6,
            "method": "tools/call",
            "params": {"name": "validate_opportunity", "arguments": {}},
        },
        headers={"Host": "relua.test", "Accept": "application/json, text/event-stream"},
    )
    assert dry_run_call.status_code == 401

    collection_queue_call = client.post(
        "/mcp",
        json={
            "jsonrpc": "2.0",
            "id": 7,
            "method": "tools/call",
            "params": {"name": "get_collection_queue", "arguments": {}},
        },
        headers={"Host": "relua.test", "Accept": "application/json, text/event-stream"},
    )
    assert collection_queue_call.status_code == 401


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
        "/mcp",
        json=INITIALIZE_REQUEST,
        headers={
            "Authorization": f"Bearer {access_token}",
            "Host": "relua.test",
            "Accept": "application/json, text/event-stream",
        },
        follow_redirects=False,
    )
    assert accepted.status_code == 200, accepted.text
    assert accepted.json()["result"]["serverInfo"]["name"] == "All Job"


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
        json=INITIALIZE_REQUEST,
        headers={
            "Authorization": "Bearer local-development-mcp-token",
            "Host": "relua.test",
            "Accept": "application/json, text/event-stream",
        },
        follow_redirects=False,
    )
    assert response.status_code == 200, response.text


def test_mcp_rejects_an_unconfigured_host(client):
    response = client.post(
        "/mcp",
        json=INITIALIZE_REQUEST,
        headers={"Authorization": "Bearer local-development-mcp-token", "Host": "attacker.example"},
    )
    assert response.status_code == 421
