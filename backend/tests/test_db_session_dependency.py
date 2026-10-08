import inspect

from fastapi import FastAPI
from fastapi.dependencies.models import Dependant
from fastapi.routing import APIRoute
from fastapi.testclient import TestClient

from app import db as db_module
from app.api.companies import router as companies_router
from app.api.health import router as health_router
from app.api.masters import router as masters_router
from app.api.oauth import router as oauth_router
from app.api.opportunities import router as opportunities_router
from app.db import DbSession, get_db

ROUTERS = (companies_router, health_router, masters_router, oauth_router, opportunities_router)


def _get_db_dependants(dependant: Dependant) -> list[Dependant]:
    found = [dependant] if dependant.call is get_db else []
    for child in dependant.dependencies:
        found.extend(_get_db_dependants(child))
    return found


def test_every_endpoint_takes_its_session_through_the_function_scoped_dependency():
    assert inspect.isasyncgenfunction(get_db)

    for router in ROUTERS:
        routes_using_a_session = 0
        for route in router.routes:
            assert isinstance(route, APIRoute)
            dependants = _get_db_dependants(route.dependant)
            routes_using_a_session += bool(dependants)
            assert all(dependant.scope == "function" for dependant in dependants), route.path
        # Each router has an endpoint that reads the database, so finding none means this walk
        # stopped recognising the dependency rather than that the router is clean.
        assert routes_using_a_session > 0, router.prefix


def test_session_is_closed_before_the_response_is_sent(monkeypatch):
    events: list[str] = []

    class RecordingSession:
        def close(self) -> None:
            events.append("closed")

    monkeypatch.setattr(db_module, "SessionLocal", RecordingSession)
    app = FastAPI()

    @app.middleware("http")
    async def record_send(request, call_next):
        response = await call_next(request)
        events.append("sent")
        return response

    @app.get("/probe")
    def probe(db: DbSession) -> dict[str, str]:
        events.append("endpoint")
        return {"status": "ok"}

    with TestClient(app) as client:
        assert client.get("/probe").status_code == 200

    assert events == ["endpoint", "closed", "sent"]
