from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from app.api.health import router as health_router
from app.api.masters import router as masters_router
from app.api.opportunities import router as opportunities_router
from app.config import get_settings
from app.mcp_server import mcp, mcp_http_app
from app.security import valid_internal_token, valid_mcp_authorization


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


@app.middleware("http")
async def authenticate_private_service(request: Request, call_next):
    if request.url.path == "/mcp" or request.url.path.startswith("/mcp/"):
        authorized = valid_mcp_authorization(request.headers.get("authorization"), settings.mcp_api_token)
        if not authorized:
            return JSONResponse(
                status_code=401,
                content={"detail": "認証が必要です"},
                headers={"WWW-Authenticate": "Bearer"},
            )
    elif not valid_internal_token(request.headers.get("x-internal-api-token"), settings.api_internal_token):
        return JSONResponse(status_code=401, content={"detail": "認証が必要です"})
    return await call_next(request)


@app.exception_handler(Exception)
async def unhandled_exception(_: Request, exc: Exception) -> JSONResponse:
    return JSONResponse(status_code=500, content={"detail": "サーバー内部でエラーが発生しました"})


app.include_router(health_router, prefix="/api/v1")
app.include_router(masters_router, prefix="/api/v1")
app.include_router(opportunities_router, prefix="/api/v1")
app.mount("/mcp", mcp_http_app())


@app.get("/")
def root() -> dict[str, str]:
    return {"name": settings.app_name, "visibility": "private"}
