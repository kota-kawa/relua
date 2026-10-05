"""Permanently remove soft-deleted postings once their replay records are archived.

The historical module name is retained so existing cron invocations remain valid.  A past deadline
is no longer enough to change a posting's status or delete it: extensions and additional rounds
must be checked by an operator through the MCP review queue first. A posting with an idempotency
record remains until the history archive job has safely moved that record out of the database.
"""

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from sqlalchemy import delete, exists, select
from sqlalchemy.orm import Session

from app.db import SessionLocal
from app.models import IdempotencyRecord, Opportunity

OPPORTUNITY_SOFT_DELETE_RETENTION_DAYS = 30


@dataclass(frozen=True)
class ExpiryCleanupResult:
    purged: int


def expire_and_purge_opportunities(
    db: Session, *, now: datetime | None = None
) -> ExpiryCleanupResult:
    """Purge rows soft-deleted for at least 30 days after their retries are archived.

    A remaining idempotency record protects its opportunity from physical deletion. The history
    archive job removes expired records only after durable storage, so this job safely defers a
    purge when run alone or when archiving has failed. Collection checks keep their historical
    evidence by setting ``opportunity_id`` to NULL; audit logs have no FK and remain in the database
    until their own archive succeeds.
    """
    instant = now or datetime.now(timezone.utc)  # noqa: UP017 -- tests also support Python 3.10
    cutoff = instant - timedelta(days=OPPORTUNITY_SOFT_DELETE_RETENTION_DAYS)
    has_idempotency_record = exists(
        select(IdempotencyRecord.id).where(IdempotencyRecord.opportunity_id == Opportunity.id)
    )
    purged = db.execute(
        delete(Opportunity).where(Opportunity.deleted_at <= cutoff, ~has_idempotency_record)
    )
    db.commit()
    return ExpiryCleanupResult(purged=int(purged.rowcount or 0))


def run() -> ExpiryCleanupResult:
    with SessionLocal() as db:
        return expire_and_purge_opportunities(db)


if __name__ == "__main__":
    result = run()
    print(f"purged={result.purged}")
