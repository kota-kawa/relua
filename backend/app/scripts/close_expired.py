"""Permanently remove soft-deleted postings after their retention period.

The historical module name is retained so existing cron invocations remain valid.  A past deadline
is no longer enough to change a posting's status or delete it: extensions and additional rounds
must be checked by an operator through the MCP review queue first.
"""

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from sqlalchemy import delete
from sqlalchemy.orm import Session

from app.db import SessionLocal
from app.models import Opportunity

OPPORTUNITY_SOFT_DELETE_RETENTION_DAYS = 30


@dataclass(frozen=True)
class ExpiryCleanupResult:
    purged: int


def expire_and_purge_opportunities(
    db: Session, *, now: datetime | None = None
) -> ExpiryCleanupResult:
    """Purge rows that were already soft-deleted at least 30 days ago.

    Database foreign keys keep collection checks as historical evidence by setting their
    ``opportunity_id`` to NULL, while join rows and idempotency records cascade with the deleted
    opportunity. Audit logs intentionally have no FK and remain as the operation history.
    """
    instant = now or datetime.now(timezone.utc)  # noqa: UP017 -- tests also support Python 3.10
    cutoff = instant - timedelta(days=OPPORTUNITY_SOFT_DELETE_RETENTION_DAYS)
    purged = db.execute(delete(Opportunity).where(Opportunity.deleted_at <= cutoff))
    db.commit()
    return ExpiryCleanupResult(purged=int(purged.rowcount or 0))


def run() -> ExpiryCleanupResult:
    with SessionLocal() as db:
        return expire_and_purge_opportunities(db)


if __name__ == "__main__":
    result = run()
    print(f"purged={result.purged}")
