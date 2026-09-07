import json
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from app.api.companies import router as companies_router
from app.api.health import router as health_router
from app.api.masters import router as masters_router
from app.api.oauth import router as oauth_router
from app.api.opportunities import router as opportunities_router
from app.config import get_settings
from app.db import SessionLocal
from app.mcp_server import ANONYMOUS_TOOLS, mcp, mcp_http_app
from app.security import bearer_token, valid_internal_token, valid_mcp_authorization
from app.services.oauth import DEFAULT_SCOPE, authenticate_access_token

#: Discovery documents and the login flow itself must answer before any credential exists.
PUBLIC_PATH_PREFIXES = ("/.well-known/", "/oauth/")


@asynccontextmanager
async def lifespan(_: FastAPI):
    async with mcp.session_manager.run():
        yield


settings = get_settings()
app = FastAPI(
    title=settings.app_name,
    version="0.1.0",
    description="Next.jsと運営者MCPからのみ利用する非公開の就活情報API",
    lifespan=lifespan,
    docs_url=None,
    redoc_url=None,
    openapi_url=None,
)


def _is_mcp_path(path: str) -> bool:
    return path == "/mcp" or path.startswith("/mcp/")


def _mcp_authorized(authorization: str | None) -> bool:
    """Accept the static operator token, and any live OAuth access token once OAuth is enabled.

    Keeping the static token means an existing loopback or SSH-forwarded setup does not have to change.
    """
    if valid_mcp_authorization(authorization, settings.mcp_api_token):
        return True
    if not settings.mcp_oauth_enabled:
        return False
    presented = bearer_token(authorization)
    if presented is None:
        return False
    with SessionLocal() as db:
        return authenticate_access_token(db, presented) is not None


def _mcp_unauthorized() -> JSONResponse:
    challenge = "Bearer"
    if settings.mcp_oauth_enabled:
        # RFC 9728: this header is how a client learns where to register and log in.
        # An auth scheme and its first auth-param are separated by a space, not a
        # comma. Strict clients (including ChatGPT's connector setup) reject
        # ``Bearer, resource_metadata=...`` before OAuth discovery can start.
        challenge += (
            f' resource_metadata="{settings.issuer}/.well-known/oauth-protected-resource/mcp",'
            f' scope="{DEFAULT_SCOPE}"'
        )
    return JSONResponse(
        status_code=401,
        content={"detail": "認証が必要です"},
        headers={"WWW-Authenticate": challenge},
    )


async def _anonymous_mcp_request(request: Request) -> bool:
    """Return whether an unauthenticated MCP request is safe to expose.

    ChatGPT must be able to initialize a connection and inspect tool metadata
    before it can decide which tool needs OAuth.  Read-only tools are public in
    relua; write tools remain protected and receive the OAuth challenge below.
    """
    if request.method == "GET":
        return True
    if request.method != "POST":
        return False
    try:
        payload = json.loads((await request.body()).decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return False
    method = payload.get("method") if isinstance(payload, dict) else None
    if method in {
        "initialize",
        "notifications/initialized",
        "notifications/cancelled",
        "ping",
        "tools/list",
        "resources/list",
        "resources/templates/list",
        "prompts/list",
        "completion/complete",
        "logging/setLevel",
    }:
        return True
    if method != "tools/call":
        return False
    params = payload.get("params")
    return isinstance(params, dict) and params.get("name") in ANONYMOUS_TOOLS


@app.middleware("http")
async def authenticate_private_service(request: Request, call_next):
    path = request.url.path
    if settings.mcp_oauth_enabled and path.startswith(PUBLIC_PATH_PREFIXES):
        return await call_next(request)
    if _is_mcp_path(path):
        if not _mcp_authorized(request.headers.get("authorization")):
            if not settings.mcp_oauth_enabled or not await _anonymous_mcp_request(request):
                return _mcp_unauthorized()
    elif not valid_internal_token(request.headers.get("x-internal-api-token"), settings.api_internal_token):
        return JSONResponse(status_code=401, content={"detail": "認証が必要です"})
    return await call_next(request)


@app.exception_handler(Exception)
async def unhandled_exception(_: Request, exc: Exception) -> JSONResponse:
    return JSONResponse(status_code=500, content={"detail": "サーバー内部でエラーが発生しました"})


app.include_router(health_router, prefix="/api/v1")
app.include_router(masters_router, prefix="/api/v1")
app.include_router(opportunities_router, prefix="/api/v1")
app.include_router(companies_router, prefix="/api/v1")
if settings.mcp_oauth_enabled:
    app.include_router(oauth_router)

# Register the Streamable HTTP route directly. Mounting the MCP app at
# ``/mcp`` makes Starlette redirect the exact endpoint to ``/mcp/``. Some
# remote MCP clients do not replay authenticated POST requests across that
# redirect, so the stable public endpoint must handle ``POST /mcp`` itself.
app.router.routes.extend(mcp_http_app().routes)


@app.get("/")
def root() -> dict[str, str]:
    return {"name": settings.app_name, "visibility": "private"}
