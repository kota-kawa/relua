"""OAuth 2.1 endpoints that let a remote MCP client connect through an operator password login.

The routes live at the site root, not under /api/v1, because clients find them through the well-known
discovery documents named in RFC 8414 and RFC 9728.
"""

import base64
import binascii
import html
from typing import Annotated, Any
from urllib.parse import urlencode, urlparse, urlunparse

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse, Response
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.orm import Session

from app.config import get_settings
from app.db import get_db
from app.security import valid_operator_password
from app.services.oauth import (
    DEFAULT_SCOPE,
    SUPPORTED_GRANT_TYPES,
    OAuthError,
    authenticate_client,
    check_resource,
    exchange_authorization_code,
    get_client,
    issue_authorization_code,
    normalize_resource,
    refresh_access_token,
    register_client,
    revoke_token,
)
from app.services.rate_limit import (
    RateLimitExceeded,
    RateLimitUnavailable,
    clear_login_rate_limit,
    enforce_login_rate_limit,
    enforce_registration_rate_limit,
)

router = APIRouter(tags=["oauth"])

NO_STORE = {"Cache-Control": "no-store", "Pragma": "no-cache"}


class ClientRegistrationRequest(BaseModel):
    model_config = ConfigDict(extra="ignore")

    redirect_uris: list[str] = Field(default_factory=list, max_length=10)
    client_name: str = "unknown"
    grant_types: list[str] | None = None
    token_endpoint_auth_method: str = "none"


def _oauth_json_error(exc: OAuthError) -> JSONResponse:
    headers = dict(NO_STORE)
    if exc.status_code == 401:
        headers["WWW-Authenticate"] = 'Basic realm="relua"'
    return JSONResponse(
        status_code=exc.status_code,
        content={"error": exc.error, "error_description": exc.description},
        headers=headers,
    )


def _client_ip(request: Request) -> str:
    return request.client.host if request.client else "unknown"


def _redirect_with(redirect_uri: str, params: dict[str, str]) -> RedirectResponse:
    parsed = urlparse(redirect_uri)
    query = f"{parsed.query}&{urlencode(params)}" if parsed.query else urlencode(params)
    target = urlunparse(parsed._replace(query=query))
    return RedirectResponse(target, status_code=302, headers=NO_STORE)


def _error_page(message: str, status_code: int = 400) -> HTMLResponse:
    return HTMLResponse(_page(f"<h1>接続できません</h1><p class=error>{html.escape(message)}</p>"), status_code, NO_STORE)


def _page(body: str) -> str:
    return f"""<!doctype html>
<html lang="ja"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="robots" content="noindex, nofollow">
<title>relua MCP 接続認証</title>
<style>
  :root {{ color-scheme: light dark; }}
  body {{ font-family: system-ui, -apple-system, "Hiragino Sans", sans-serif; margin: 0;
         display: grid; place-items: center; min-height: 100vh; padding: 1.5rem; }}
  main {{ width: min(28rem, 100%); }}
  h1 {{ font-size: 1.25rem; margin: 0 0 1rem; }}
  dl {{ display: grid; grid-template-columns: auto 1fr; gap: .35rem 1rem; margin: 0 0 1.25rem;
        padding: .85rem 1rem; border: 1px solid currentColor; border-radius: .5rem; font-size: .875rem; }}
  dt {{ opacity: .7; }} dd {{ margin: 0; overflow-wrap: anywhere; }}
  label {{ display: block; font-size: .875rem; margin-bottom: .35rem; }}
  input[type=password] {{ width: 100%; padding: .6rem; font-size: 1rem; box-sizing: border-box;
                          border: 1px solid currentColor; border-radius: .375rem; background: transparent;
                          color: inherit; }}
  button {{ width: 100%; margin-top: 1rem; padding: .65rem; font-size: 1rem; border: 0; border-radius: .375rem;
            background: #1f6feb; color: #fff; cursor: pointer; }}
  .error {{ color: #d1242f; font-size: .875rem; }}
  .note {{ opacity: .7; font-size: .8125rem; margin-top: 1rem; }}
</style></head>
<body><main>{body}</main></body></html>
"""


def _login_page(*, client_name: str, redirect_uri: str, fields: dict[str, str], error: str | None) -> HTMLResponse:
    hidden = "".join(
        f'<input type="hidden" name="{html.escape(name)}" value="{html.escape(value)}">'
        for name, value in fields.items()
        if value
    )
    warning = f'<p class="error">{html.escape(error)}</p>' if error else ""
    host = urlparse(redirect_uri).netloc
    body = f"""<h1>MCPクライアントの接続を許可しますか？</h1>
<dl>
  <dt>クライアント</dt><dd>{html.escape(client_name)}</dd>
  <dt>戻り先</dt><dd>{html.escape(host)}</dd>
  <dt>権限</dt><dd>募集情報の検索・登録・更新</dd>
</dl>
<form method="post" action="/oauth/authorize" autocomplete="off">
  {hidden}
  <label for="password">運営者パスワード</label>
  <input id="password" name="password" type="password" required autofocus autocomplete="current-password">
  {warning}
  <button type="submit">許可して接続</button>
</form>
<p class="note">身に覚えのない接続要求であれば、パスワードを入力せずにこのページを閉じてください。</p>"""
    return HTMLResponse(_page(body), status_code=401 if error else 200, headers=NO_STORE)


@router.get("/.well-known/oauth-protected-resource")
@router.get("/.well-known/oauth-protected-resource/mcp")
def protected_resource_metadata() -> JSONResponse:
    settings = get_settings()
    return JSONResponse(
        {
            "resource": settings.resource_identifier,
            "authorization_servers": [settings.issuer],
            "scopes_supported": [DEFAULT_SCOPE],
            "bearer_methods_supported": ["header"],
        }
    )


@router.get("/.well-known/oauth-authorization-server")
@router.get("/.well-known/oauth-authorization-server/mcp")
def authorization_server_metadata() -> JSONResponse:
    issuer = get_settings().issuer
    return JSONResponse(
        {
            "issuer": issuer,
            "authorization_endpoint": f"{issuer}/oauth/authorize",
            "token_endpoint": f"{issuer}/oauth/token",
            "registration_endpoint": f"{issuer}/oauth/register",
            "revocation_endpoint": f"{issuer}/oauth/revoke",
            "response_types_supported": ["code"],
            "grant_types_supported": list(SUPPORTED_GRANT_TYPES),
            "code_challenge_methods_supported": ["S256"],
            "token_endpoint_auth_methods_supported": ["none", "client_secret_post", "client_secret_basic"],
            "scopes_supported": [DEFAULT_SCOPE],
        }
    )


@router.post("/oauth/register", status_code=201)
def register(
    request: Request,
    payload: ClientRegistrationRequest,
    db: Annotated[Session, Depends(get_db)],
) -> Response:
    try:
        enforce_registration_rate_limit(_client_ip(request))
    except (RateLimitExceeded, RateLimitUnavailable):
        return _oauth_json_error(OAuthError("temporarily_unavailable", "登録要求が多すぎます", status_code=429))

    try:
        client, secret = register_client(
            db,
            redirect_uris=payload.redirect_uris,
            client_name=payload.client_name,
            grant_types=payload.grant_types,
            token_endpoint_auth_method=payload.token_endpoint_auth_method,
        )
    except OAuthError as exc:
        return _oauth_json_error(exc)

    body: dict[str, Any] = {
        "client_id": client.client_id,
        "client_name": client.client_name,
        "redirect_uris": client.redirect_uris,
        "grant_types": client.grant_types,
        "response_types": ["code"],
        "token_endpoint_auth_method": client.token_endpoint_auth_method,
        "client_id_issued_at": int(client.created_at.timestamp()) if client.created_at else None,
    }
    if secret:
        body["client_secret"] = secret
        body["client_secret_expires_at"] = 0
    return JSONResponse(body, status_code=201, headers=NO_STORE)


#: Only these travel from the query string into the login form, so a crafted URL cannot inject a form field.
AUTHORIZE_PARAMS = (
    "response_type",
    "client_id",
    "redirect_uri",
    "code_challenge",
    "code_challenge_method",
    "state",
    "scope",
    "resource",
)


def _present(values: dict[str, str | None]) -> dict[str, str]:
    return {key: value for key, value in values.items() if value}


def _authorize_params(values: dict[str, str | None]) -> dict[str, str]:
    return {key: value for key, value in _present(values).items() if key in AUTHORIZE_PARAMS}


def _validate_authorize_request(db: Session, params: dict[str, str]) -> tuple[Any, str]:
    """Check the parts that decide whether redirecting back is safe at all."""
    client = get_client(db, params.get("client_id"))
    redirect_uri = params.get("redirect_uri") or ""
    if not redirect_uri:
        if len(client.redirect_uris) != 1:
            raise OAuthError("invalid_request", "redirect_uri を指定してください")
        redirect_uri = client.redirect_uris[0]
    if redirect_uri not in client.redirect_uris:
        raise OAuthError("invalid_request", "redirect_uri が登録内容と一致しません")
    return client, redirect_uri


def _check_authorize_grant(params: dict[str, str]) -> None:
    """Check the parts that can be reported back to the client as a redirect error."""
    if params.get("response_type") != "code":
        raise OAuthError("unsupported_response_type", "response_type は code のみ対応しています")
    if params.get("code_challenge_method", "S256") != "S256":
        raise OAuthError("invalid_request", "code_challenge_method は S256 のみ対応しています")
    challenge = params.get("code_challenge") or ""
    if not 43 <= len(challenge) <= 128:
        raise OAuthError("invalid_request", "PKCE の code_challenge が必要です")
    check_resource(params.get("resource"))


@router.get("/oauth/authorize")
def authorize_form(
    request: Request,
    db: Annotated[Session, Depends(get_db)],
) -> Response:
    params = _authorize_params(dict(request.query_params))
    try:
        client, redirect_uri = _validate_authorize_request(db, params)
    except OAuthError as exc:
        return _error_page(exc.description, exc.status_code if exc.status_code != 401 else 400)

    params["redirect_uri"] = redirect_uri
    try:
        _check_authorize_grant(params)
    except OAuthError as exc:
        return _redirect_with(
            redirect_uri,
            _present({"error": exc.error, "error_description": exc.description, "state": params.get("state")}),
        )
    return _login_page(client_name=client.client_name, redirect_uri=redirect_uri, fields=params, error=None)


@router.post("/oauth/authorize")
def authorize_submit(
    request: Request,
    db: Annotated[Session, Depends(get_db)],
    password: Annotated[str, Form()],
    client_id: Annotated[str, Form()],
    code_challenge: Annotated[str, Form()],
    response_type: Annotated[str, Form()] = "code",
    redirect_uri: Annotated[str | None, Form()] = None,
    code_challenge_method: Annotated[str, Form()] = "S256",
    state: Annotated[str | None, Form()] = None,
    scope: Annotated[str | None, Form()] = None,
    resource: Annotated[str | None, Form()] = None,
) -> Response:
    params = _authorize_params(
        {
            "response_type": response_type,
            "client_id": client_id,
            "redirect_uri": redirect_uri,
            "code_challenge": code_challenge,
            "code_challenge_method": code_challenge_method,
            "state": state,
            "scope": scope,
            "resource": resource,
        }
    )
    try:
        client, verified_redirect_uri = _validate_authorize_request(db, params)
    except OAuthError as exc:
        return _error_page(exc.description, exc.status_code if exc.status_code != 401 else 400)

    params["redirect_uri"] = verified_redirect_uri
    try:
        _check_authorize_grant(params)
    except OAuthError as exc:
        return _redirect_with(
            verified_redirect_uri,
            _present({"error": exc.error, "error_description": exc.description, "state": state}),
        )

    identifier = _client_ip(request)
    try:
        enforce_login_rate_limit(identifier)
    except RateLimitExceeded:
        return _error_page("パスワードの試行回数が上限に達しました。しばらく待って再試行してください。", 429)
    except RateLimitUnavailable:
        return _error_page("認証基盤に接続できないため、安全のため接続を停止しています。", 503)

    if not valid_operator_password(password, get_settings().mcp_operator_password):
        return _login_page(
            client_name=client.client_name,
            redirect_uri=verified_redirect_uri,
            fields=params,
            error="パスワードが正しくありません。",
        )
    clear_login_rate_limit(identifier)

    code = issue_authorization_code(
        db,
        client=client,
        redirect_uri=verified_redirect_uri,
        code_challenge=code_challenge,
        scope=scope,
        resource=normalize_resource(resource) or get_settings().resource_identifier,
    )
    return _redirect_with(verified_redirect_uri, _present({"code": code, "state": state}))


def _basic_credentials(authorization: str | None) -> tuple[str, str] | None:
    if not authorization:
        return None
    scheme, separator, encoded = authorization.partition(" ")
    if separator != " " or scheme.lower() != "basic":
        return None
    try:
        decoded = base64.b64decode(encoded, validate=True).decode("utf-8")
    except (binascii.Error, UnicodeDecodeError):
        return None
    client_id, separator, client_secret = decoded.partition(":")
    return (client_id, client_secret) if separator == ":" else None


def _resolve_client(
    db: Session, request: Request, client_id: str | None, client_secret: str | None
) -> Any:
    credentials = _basic_credentials(request.headers.get("authorization"))
    if credentials:
        return authenticate_client(db, credentials[0], credentials[1])
    return authenticate_client(db, client_id, client_secret)


@router.post("/oauth/token")
def token(
    request: Request,
    db: Annotated[Session, Depends(get_db)],
    grant_type: Annotated[str, Form()],
    code: Annotated[str | None, Form()] = None,
    redirect_uri: Annotated[str | None, Form()] = None,
    code_verifier: Annotated[str | None, Form()] = None,
    refresh_token: Annotated[str | None, Form()] = None,
    client_id: Annotated[str | None, Form()] = None,
    client_secret: Annotated[str | None, Form()] = None,
    resource: Annotated[str | None, Form()] = None,
) -> Response:
    try:
        client = _resolve_client(db, request, client_id, client_secret)
        if grant_type == "authorization_code":
            if not code:
                raise OAuthError("invalid_request", "code が必要です")
            payload = exchange_authorization_code(
                db, code=code, client=client, redirect_uri=redirect_uri, code_verifier=code_verifier, resource=resource
            )
        elif grant_type == "refresh_token":
            if not refresh_token:
                raise OAuthError("invalid_request", "refresh_token が必要です")
            payload = refresh_access_token(db, refresh_token=refresh_token, client=client, resource=resource)
        else:
            raise OAuthError("unsupported_grant_type", "対応していない grant_type です")
    except OAuthError as exc:
        return _oauth_json_error(exc)
    return JSONResponse(payload, headers=NO_STORE)


@router.post("/oauth/revoke")
def revoke(
    request: Request,
    db: Annotated[Session, Depends(get_db)],
    token: Annotated[str, Form()],
    client_id: Annotated[str | None, Form()] = None,
    client_secret: Annotated[str | None, Form()] = None,
) -> Response:
    try:
        client = _resolve_client(db, request, client_id, client_secret)
    except OAuthError as exc:
        return _oauth_json_error(exc)
    revoke_token(db, token=token, client=client)
    # RFC 7009 asks for 200 even when the token was already gone, so a client cannot probe for valid tokens.
    return Response(status_code=200, headers=NO_STORE)
