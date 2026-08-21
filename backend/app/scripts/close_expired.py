"""Expire past-deadline postings and permanently remove expired soft deletions.

Run this once a day from cron or the deployment scheduler. Deadlines are evaluated in Tokyo time;
the retention period is measured from ``deleted_at`` in UTC, so manual and automatic soft deletions
follow the same 30-day lifecycle.
"""

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from sqlalchemy import delete, select, update
from sqlalchemy.orm import Session

from app.dates import today_in_tokyo
from app.db import SessionLocal
from app.models import Opportunity, RecruitmentStatus

OPPORTUNITY_SOFT_DELETE_RETENTION_DAYS = 30


@dataclass(frozen=True)
class ExpiryCleanupResult:
    expired: int
    purged: int


def expire_and_purge_opportunities(
    db: Session, *, now: datetime | None = None
) -> ExpiryCleanupResult:
    """Soft-delete past-deadline postings, then hard-delete rows retained for 30 days.

    Database foreign keys keep collection checks as historical evidence by setting their
    ``opportunity_id`` to NULL, while join rows and idempotency records cascade with the deleted
    opportunity. Audit logs intentionally have no FK and remain as the operation history.
    """
    instant = now or datetime.now(timezone.utc)  # noqa: UP017 -- tests also support Python 3.10
    closed_id = db.scalar(select(RecruitmentStatus.id).where(RecruitmentStatus.name == "締切"))
    if closed_id is None:
        raise RuntimeError("募集状況マスタ「締切」がありません")

    expired = db.execute(
        update(Opportunity)
        .where(
            Opportunity.deadline < today_in_tokyo(instant),
            Opportunity.deleted_at.is_(None),
        )
        .values(status_id=closed_id, deleted_at=instant, updated_at=instant)
    )
    cutoff = instant - timedelta(days=OPPORTUNITY_SOFT_DELETE_RETENTION_DAYS)
    purged = db.execute(delete(Opportunity).where(Opportunity.deleted_at <= cutoff))
    db.commit()
    return ExpiryCleanupResult(expired=int(expired.rowcount or 0), purged=int(purged.rowcount or 0))


def run() -> ExpiryCleanupResult:
    with SessionLocal() as db:
        return expire_and_purge_opportunities(db)


if __name__ == "__main__":
    result = run()
    print(f"expired={result.expired} purged={result.purged}")
