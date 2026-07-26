from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.api.health import router as health_router
from app.api.masters import router as masters_router
from app.api.opportunities import router as opportunities_router
from app.config import get_settings
from app.mcp_server import mcp, mcp_http_app


@asynccontextmanager
async def lifespan(_: FastAPI):
    async with mcp.session_manager.run():
        yield


settings = get_settings()
app = FastAPI(
    title=settings.app_name,
    version="0.1.0",
    description="未ログインで閲覧でき、MCPからのみ更新できる就活情報API",
    lifespan=lifespan,
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin_list,
    allow_credentials=False,
    allow_methods=["GET"],
    allow_headers=["*"],
)


@app.exception_handler(Exception)
async def unhandled_exception(_: Request, exc: Exception) -> JSONResponse:
    return JSONResponse(status_code=500, content={"detail": "サーバー内部でエラーが発生しました"})


app.include_router(health_router, prefix="/api/v1")
app.include_router(masters_router, prefix="/api/v1")
app.include_router(opportunities_router, prefix="/api/v1")
app.mount("/mcp", mcp_http_app())


@app.get("/")
def root() -> dict[str, str]:
    return {"name": settings.app_name, "docs": "/docs", "mcp": "/mcp/"}
