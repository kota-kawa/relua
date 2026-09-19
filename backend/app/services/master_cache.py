import json
import weakref
from typing import Any

from redis.exceptions import RedisError
from sqlalchemy import text
from sqlalchemy.exc import DatabaseError, SQLAlchemyError
from sqlalchemy.orm import Session

from app.services.masters import get_masters
from app.services.rate_limit import redis_client
from app.services.serialization import master_dict

MASTER_CACHE_PREFIX = "masters:public:v3"
MASTER_CACHE_TTL_SECONDS = 3600
#: Used while the schema revision cannot be read (a database built straight from the metadata, as in
#: the tests). The payload is still cached, just under one fixed generation.
UNKNOWN_GENERATION = "unmigrated"
#: Binds already known to have no alembic_version table, so the probe is not repeated per request.
#: Weak so a per-test engine does not outlive its test.
_UNVERSIONED_BINDS: weakref.WeakSet[Any] = weakref.WeakSet()


def master_generation(db: Session) -> str:
    """The generation marker that the cached payload is keyed by.

    The cache used to be a single fixed key with a one-hour TTL, invalidated by nothing: the running
    application never writes master rows, so ``invalidate_master_cache()`` had no caller anywhere and
    could not have had one. Master values only ever change through an Alembic migration (``seed_masters``
    and the later migrations that add rows or flip ``is_active``), so for up to an hour after such a
    migration ``get_master_values`` kept advertising the previous list while ``validate_write`` /
    ``resolve_one`` already read the new rows straight from the database - a value the MCP surface
    offered was rejected on write, and a newly seeded value stayed invisible.

    Keying the payload on the applied schema revision closes exactly that window. The revision changes
    in the same deployment step that changes the master rows, so the key rotates the moment the data
    can differ and the next read repopulates from the database. Unrelated migrations rotate it too,
    which costs one extra repopulation per deploy and is far cheaper than serving stale fixed values.
    Reading it is a single row from a two-column table, next to the eight table scans it avoids.
    """
    bind = db.get_bind()
    # A database created straight from the metadata (the test fixtures) has no alembic_version table.
    # Asking for it fails, and on PostgreSQL a failed statement poisons the surrounding transaction, so
    # the answer is remembered per bind and the probe is not repeated on every later request.
    if bind in _UNVERSIONED_BINDS:
        return UNKNOWN_GENERATION
    try:
        revision = db.scalar(text("SELECT version_num FROM alembic_version LIMIT 1"))
    except SQLAlchemyError as exc:
        db.rollback()
        # Only a genuinely absent table is remembered. Catching every SQLAlchemyError here meant one
        # dropped connection or statement timeout retired the probe for the life of the process: the
        # generation would stay pinned to UNKNOWN_GENERATION even after the database recovered, which
        # is exactly the stale-master bug this key was introduced to close, now silent and permanent.
        if _is_missing_table(exc):
            _UNVERSIONED_BINDS.add(bind)
            return UNKNOWN_GENERATION
        raise
    return revision or UNKNOWN_GENERATION


def _is_missing_table(exc: SQLAlchemyError) -> bool:
    """Whether the probe failed because alembic_version does not exist, rather than transiently.

    SQLAlchemy reports this as a dialect-specific DBAPI error, so the driver's own signal is what
    distinguishes it: psycopg raises UndefinedTable (SQLSTATE 42P01) and sqlite3 an OperationalError
    whose message names the missing table. Anything else — a closed connection, a timeout — is a
    condition that can clear on its own and must not be cached as a permanent answer.
    """
    if not isinstance(exc, DatabaseError):
        return False
    sqlstate = getattr(exc.orig, "sqlstate", None) or getattr(getattr(exc.orig, "diag", None), "sqlstate", None)
    if sqlstate is not None:
        return sqlstate == "42P01"
    return "alembic_version" in str(exc.orig) and "no such table" in str(exc.orig).lower()


def master_cache_key(db: Session) -> str:
    return f"{MASTER_CACHE_PREFIX}:{master_generation(db)}"


def master_payload(db: Session) -> dict[str, list[dict[str, Any]]]:
    key = master_cache_key(db)
    try:
        cached = redis_client().get(key)
        if cached:
            return json.loads(cached)
    except RedisError:
        pass

    values = get_masters(db)
    payload = {
        key_name: [
            master_dict(item) | ({"industry_id": item.industry_id} if hasattr(item, "industry_id") else {})
            for item in items
        ]
        for key_name, items in values.items()
    }
    try:
        # Superseded generations are left to expire on their own TTL rather than being deleted: after a
        # migration the old key is simply never read again.
        redis_client().setex(key, MASTER_CACHE_TTL_SECONDS, json.dumps(payload, ensure_ascii=False))
    except RedisError:
        pass
    return payload
