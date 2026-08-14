import os

os.environ.setdefault("DATABASE_URL", "sqlite://")
os.environ["REDIS_URL"] = "redis://localhost:6379/15"
os.environ["MCP_OAUTH_ENABLED"] = "true"
os.environ["MCP_PUBLIC_URL"] = "https://relua.test"
os.environ["MCP_OPERATOR_PASSWORD"] = "test-operator-password-0001"

import pytest
from sqlalchemy import create_engine, event, text
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app import models  # noqa: F401
from app.db import Base
from app.master_data import seed_masters


@pytest.fixture
def db() -> Session:
    database_url = os.environ["DATABASE_URL"]
    sqlite = database_url.startswith("sqlite")
    engine_options = (
        {"connect_args": {"check_same_thread": False}, "poolclass": StaticPool}
        if sqlite
        else {}
    )
    engine = create_engine(database_url, **engine_options)

    if sqlite:
        @event.listens_for(engine, "connect")
        def enable_foreign_keys(connection, _):
            connection.execute("PRAGMA foreign_keys=ON")
    else:
        with engine.begin() as connection:
            connection.execute(text("CREATE EXTENSION IF NOT EXISTS pg_trgm"))

    Base.metadata.create_all(engine)
    with engine.begin() as connection:
        seed_masters(connection)
    with Session(engine, expire_on_commit=False) as session:
        yield session
    Base.metadata.drop_all(engine)
