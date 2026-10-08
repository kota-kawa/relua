from collections.abc import AsyncGenerator, Generator
from contextlib import contextmanager
from typing import Annotated

from fastapi import Depends
from sqlalchemy import create_engine, event
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from app.config import get_settings


class Base(DeclarativeBase):
    pass


settings = get_settings()
connect_args = {"check_same_thread": False} if settings.database_url.startswith("sqlite") else {}
engine = create_engine(settings.database_url, pool_pre_ping=True, connect_args=connect_args)
SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


@event.listens_for(engine, "connect")
def _enable_sqlite_foreign_keys(dbapi_connection, _connection_record) -> None:
    """Turn foreign keys on for every SQLite connection.

    SQLite ships with foreign key enforcement off per connection, which silently disables the
    ``ON DELETE CASCADE`` / ``ON DELETE SET NULL`` rules the schema relies on. ``scripts/close_expired.py``
    deletes opportunities in bulk and expects the database to clean up the association rows and to null
    out ``collection_checks.opportunity_id``; without the pragma a SQLite deployment is left with orphan
    rows and dangling references. PostgreSQL always enforces them, so the listener only has to act here.
    """
    if engine.dialect.name != "sqlite":
        return
    cursor = dbapi_connection.cursor()
    try:
        cursor.execute("PRAGMA foreign_keys=ON")
    finally:
        cursor.close()


async def get_db() -> AsyncGenerator[Session, None]:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


#: The session every REST and OAuth endpoint depends on.
#:
#: With a plain ``Depends(get_db)`` on a sync generator, one burst of traffic took the API down for
#: good: all fifteen pooled connections sat ``idle in transaction``, every later request timed out
#: waiting for one (``QueuePool limit ... reached``), and the backlog did not drain after the burst
#: had ended. The session was only closed after the response had been sent, so a connection stayed
#: checked out for as long as a finished request was still queued behind the ones waiting for it.
#:
#: Two things together remove that state. A load test against PostgreSQL showed that either one
#: alone still hangs:
#:
#: - ``scope="function"`` closes the session once the endpoint's work is done, before the response
#:   is sent. Every endpoint builds its whole response before returning, so nothing reads from the
#:   session afterwards.
#: - ``get_db`` is an async generator, although nothing in it awaits, so that the close runs on the
#:   event loop instead of being handed to a worker thread. The cost is one short ROLLBACK round
#:   trip on the loop per request.
DbSession = Annotated[Session, Depends(get_db, scope="function")]


@contextmanager
def session_scope() -> Generator[Session, None, None]:
    with SessionLocal() as db:
        try:
            yield db
            db.commit()
        except Exception:
            db.rollback()
            raise
