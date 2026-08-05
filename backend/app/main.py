from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from app.api.health import router as health_router
from app.api.masters import router as masters_router
from app.api.oauth import router as oauth_router
from app.api.opportunities import router as opportunities_router
from app.config import get_settings
from app.db import SessionLocal
from app.mcp_server import mcp, mcp_http_app
from app.security import bearer_token, valid_internal_token, valid_mcp_authorization
from app.services.oauth import authenticate_access_token

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
        challenge += f', resource_metadata="{settings.issuer}/.well-known/oauth-protected-resource/mcp"'
    return JSONResponse(
        status_code=401,
        content={"detail": "認証が必要です"},
        headers={"WWW-Authenticate": challenge},
    )


@app.middleware("http")
async def authenticate_private_service(request: Request, call_next):
    path = request.url.path
    if settings.mcp_oauth_enabled and path.startswith(PUBLIC_PATH_PREFIXES):
        return await call_next(request)
    if _is_mcp_path(path):
        if not _mcp_authorized(request.headers.get("authorization")):
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
if settings.mcp_oauth_enabled:
    app.include_router(oauth_router)
app.mount("/mcp", mcp_http_app())


@app.get("/")
def root() -> dict[str, str]:
    return {"name": settings.app_name, "visibility": "private"}
