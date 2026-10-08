"""OAuth 2.1 endpoints that let a remote MCP client connect through an operator password login.

The routes live at the site root, not under /api/v1, because clients find them through the well-known
discovery documents named in RFC 8414 and RFC 9728.
"""

import base64
import binascii
import html
from typing import Annotated, Any
from urllib.parse import urlencode, urlparse, urlunparse

from fastapi import APIRouter, Form, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse, Response
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.orm import Session

from app.config import get_settings
from app.db import DbSession
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
    validate_scope,
)
from app.services.rate_limit import (
    UNRESOLVED_CLIENT_IP,
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
    """The peer address uvicorn resolved, after --proxy-headers has been applied.

    This is only a real client address when --forwarded-allow-ips names the proxy in front of us; see
    the rate limiter, which deliberately does not rely on this value alone.
    """
    return request.client.host if request.client else UNRESOLVED_CLIENT_IP


def _redirect_with(redirect_uri: str, params: dict[str, str]) -> RedirectResponse:
    parsed = urlparse(redirect_uri)
    query = f"{parsed.query}&{urlencode(params)}" if parsed.query else urlencode(params)
    target = urlunparse(parsed._replace(query=query))
    return RedirectResponse(target, status_code=302, headers=NO_STORE)


def _error_page(message: str, status_code: int = 400) -> HTMLResponse:
    note = "お使いのMCPクライアントに戻り、もう一度接続を実行してください。繰り返し失敗する場合は、クライアント側の登録内容を確認してください。"
    body = f"""<p class="auth-alert" role="alert">{_ALERT_ICON}<span>{html.escape(message)}</span></p>
<p class="auth-note">{note}</p>"""
    return HTMLResponse(
        _page(eyebrow="CONNECTION FAILED", heading="接続できません", body=body),
        status_code,
        NO_STORE,
    )


#: The honeycomb from the relua mark, reused from the site's about page so the
#: login inherits the same navy-and-lattice header the rest of relua uses.
_HEX_FIELD = (
    "url(\"data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='56' height='100'%3E"
    "%3Cpath d='M28 66 0 50V16L28 0l28 16v34L28 66v34' fill='none' stroke='%23ffffff' stroke-opacity='.13'"
    " stroke-width='1.4'/%3E%3Cpath d='M28 0v34L0 50v34l28 16 28-16V50L28 34' fill='none' stroke='%23ffffff'"
    " stroke-opacity='.13' stroke-width='1.4'/%3E%3C/svg%3E\")"
)

_BRAND_MARK = (
    '<svg width="26" height="30" viewBox="0 0 26 30" aria-hidden="true">'
    '<path d="M13 1.2 24 7.6v12.8L13 26.8 2 20.4V7.6z" fill="none" stroke="#f59120" stroke-width="1.9"/>'
    '<circle cx="13" cy="14" r="3.9" fill="#f59120"/></svg>'
)

_ALERT_ICON = (
    '<svg width="17" height="17" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"'
    ' stroke-linecap="round" aria-hidden="true"><circle cx="12" cy="12" r="9"/>'
    '<path d="M12 7.5v5.5"/><path d="M12 16.4h.01"/></svg>'
)

_LOCK_ICON = (
    '<svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"'
    ' stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">'
    '<rect x="4" y="10.5" width="16" height="10.5" rx="2"/><path d="M8 10.5V7a4 4 0 0 1 8 0v3.5"/></svg>'
)


def _page(*, eyebrow: str, heading: str, body: str) -> str:
    """The shared shell. Colours and type follow the site's brand tokens in globals.css."""
    return f"""<!doctype html>
<html lang="ja"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="robots" content="noindex, nofollow">
<meta name="theme-color" content="#21385a">
<title>relua MCP 接続認証</title>
<style>
  :root {{
    color-scheme: light;
    --ink: #21385a; --ink-deep: #16273d; --paper: #f7f5ee; --paper-deep: #efede4;
    --white: #fffefa; --orange: #f59120; --orange-soft: #fdefda; --line: #ddd9d4; --muted: #6b7686;
  }}
  * {{ box-sizing: border-box; }}
  body {{
    margin: 0; display: grid; place-items: center; min-height: 100vh; padding: 28px 20px;
    color: var(--ink-deep); background: var(--paper);
    font-family: "Hiragino Kaku Gothic ProN", "Yu Gothic", "Noto Sans JP", system-ui, sans-serif;
    -webkit-font-smoothing: antialiased; -webkit-tap-highlight-color: transparent;
  }}
  button, input {{ font: inherit; }}
  .auth-card {{
    overflow: hidden; width: min(30rem, 100%); border: 1px solid var(--line); border-radius: 12px;
    background: var(--white); box-shadow: 0 20px 50px rgba(22,39,61,.09);
  }}
  .auth-head {{ position: relative; overflow: hidden; padding: 30px 32px 28px; color: var(--paper); background: var(--ink); }}
  .auth-head::before {{
    content: ""; position: absolute; inset: 0; opacity: .5; pointer-events: none;
    background-image: {_HEX_FIELD};
    mask-image: radial-gradient(120% 90% at 82% 8%, black, transparent 72%);
  }}
  .auth-head > * {{ position: relative; z-index: 1; }}
  .brand {{ display: flex; align-items: center; gap: 10px; margin-bottom: 26px; }}
  .brand strong {{ color: white; font-family: Georgia, serif; font-size: 21px; font-style: italic; font-weight: 500; letter-spacing: .02em; }}
  .brand small {{ padding-left: 11px; border-left: 1px solid rgba(255,255,255,.22); color: #aeb5be; font-size: 11px; letter-spacing: .1em; }}
  .eyebrow {{ display: block; margin: 0 0 12px; color: var(--orange); font-size: 11px; font-weight: 800; letter-spacing: .18em; }}
  /* auto-phrase keeps the Japanese heading from breaking mid-phrase ("許可します / か？")
     where it wraps; browsers without it fall back to the usual per-character break. */
  h1 {{ margin: 0; font-family: Georgia, "Yu Mincho", serif; font-size: 23px; font-weight: 600; line-height: 1.5; word-break: auto-phrase; }}
  .auth-body {{ padding: 26px 32px 30px; }}
  .auth-facts {{ display: grid; gap: 1px; overflow: hidden; margin: 0 0 24px; border: 1px solid var(--line); border-radius: 8px; background: var(--line); }}
  .auth-facts > div {{ display: grid; grid-template-columns: 84px minmax(0,1fr); gap: 14px; padding: 12px 15px; background: var(--paper); }}
  .auth-facts dt {{ color: var(--muted); font-size: 11px; font-weight: 800; letter-spacing: .06em; }}
  .auth-facts dd {{ margin: 0; color: #353e4b; font-size: 13px; line-height: 1.55; overflow-wrap: anywhere; }}
  label {{ display: flex; align-items: center; gap: 7px; margin-bottom: 9px; font-size: 13px; font-weight: 800; letter-spacing: .02em; }}
  label svg {{ color: var(--orange); }}
  input[type=password] {{
    width: 100%; min-height: 50px; padding: 0 15px; border: 1px solid var(--line); border-radius: 7px;
    color: var(--ink-deep); background: white; font-size: 15px; letter-spacing: .08em;
    outline: none; transition: border-color .2s, box-shadow .2s;
  }}
  input[type=password]:focus {{ border-color: var(--orange); box-shadow: 0 0 0 3px rgba(245,145,32,.16); }}
  .auth-alert {{
    display: flex; align-items: flex-start; gap: 8px; margin: 14px 0 0; padding: 11px 14px;
    border-left: 3px solid #c0563c; border-radius: 0 5px 5px 0; color: #98402c; background: #fbeae5;
    font-size: 12px; font-weight: 700; line-height: 1.65;
  }}
  .auth-alert svg {{ flex: none; margin-top: 1px; }}
  button {{
    display: flex; align-items: center; justify-content: center; gap: 8px; width: 100%; min-height: 52px;
    margin-top: 22px; border: 0; border-radius: 7px; color: white; background: var(--ink);
    font-size: 14px; font-weight: 800; cursor: pointer; transition: background .2s, transform .15s;
  }}
  button:active {{ transform: scale(.98); transition-duration: .08s; }}
  .auth-note {{
    display: flex; align-items: flex-start; gap: 8px; margin: 22px 0 0; padding: 13px 15px;
    border-left: 3px solid var(--orange); color: #66543e; background: var(--orange-soft);
    font-size: 12px; line-height: 1.75;
  }}
  :focus-visible {{ outline: 3px solid rgba(245,145,32,.45); outline-offset: 2px; }}
  @media (hover: hover) {{ button:hover {{ background: var(--orange); }} }}
  @media (max-width: 480px) {{
    body {{ padding: 0; place-items: stretch; }}
    .auth-card {{ width: 100%; border: 0; border-radius: 0; box-shadow: none; }}
    .auth-head {{ padding: 26px 22px 24px; }}
    .auth-body {{ padding: 24px 22px 34px; }}
    h1 {{ font-size: 20px; }}
    .auth-facts > div {{ grid-template-columns: 1fr; gap: 4px; }}
  }}
</style></head>
<body>
<main class="auth-card">
  <div class="auth-head">
    <p class="brand">{_BRAND_MARK}<strong>relua</strong><small>Relay, then reveal.</small></p>
    <span class="eyebrow">{eyebrow}</span>
    <h1>{heading}</h1>
  </div>
  <div class="auth-body">{body}</div>
</main>
</body></html>
"""


def _login_page(*, client_name: str, redirect_uri: str, fields: dict[str, str], error: str | None) -> HTMLResponse:
    hidden = "".join(
        f'<input type="hidden" name="{html.escape(name)}" value="{html.escape(value)}">'
        for name, value in fields.items()
        if value
    )
    warning = (
        f'<p class="auth-alert" role="alert">{_ALERT_ICON}<span>{html.escape(error)}</span></p>' if error else ""
    )
    host = urlparse(redirect_uri).netloc
    body = f"""<dl class="auth-facts">
  <div><dt>クライアント</dt><dd>{html.escape(client_name)}</dd></div>
  <div><dt>戻り先</dt><dd>{html.escape(host)}</dd></div>
  <div><dt>権限</dt><dd>募集情報の検索・登録・更新</dd></div>
</dl>
<form method="post" action="/oauth/authorize" autocomplete="off">
  {hidden}
  <label for="password">{_LOCK_ICON}運営者パスワード</label>
  <input id="password" name="password" type="password" required autofocus autocomplete="current-password">
  {warning}
  <button type="submit">許可して接続</button>
</form>
<p class="auth-note">身に覚えのない接続要求であれば、パスワードを入力せずにこのページを閉じてください。</p>"""
    return HTMLResponse(
        _page(eyebrow="MCP CONNECTION", heading="MCPクライアントの接続を許可しますか？", body=body),
        status_code=401 if error else 200,
        headers=NO_STORE,
    )


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
    db: DbSession,
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
    # Checked here, before the password form is shown, so an unsupported scope comes back to the client
    # as a redirect error rather than being stored and then silently ignored at the resource.
    validate_scope(params.get("scope"))
    check_resource(params.get("resource"))


@router.get("/oauth/authorize")
def authorize_form(
    request: Request,
    db: DbSession,
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
    db: DbSession,
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
        enforce_login_rate_limit(identifier, client.client_id)
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
    clear_login_rate_limit(identifier, client.client_id)

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
    db: DbSession,
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
    db: DbSession,
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
