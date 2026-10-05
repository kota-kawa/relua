from datetime import datetime, timedelta

from sqlalchemy import or_

from app.models import CollectionTarget

FAILED_CHECK_RESULTS = ("unreachable", "needs_review")
MAX_FAILED_CHECKS = 8
MAX_RETRY_INTERVAL_DAYS = 90


def collection_due_clause(now: datetime):
    return or_(
        CollectionTarget.last_checked_at.is_(None),
        CollectionTarget.next_check_at.is_(None),
        CollectionTarget.next_check_at <= now,
    )


def collection_check_interval(target: CollectionTarget) -> int:
    multiplier = 2 ** max(0, target.consecutive_failed_checks - 1)
    return min(target.check_interval_days * multiplier, max(target.check_interval_days, MAX_RETRY_INTERVAL_DAYS))


def record_collection_result(target: CollectionTarget, *, result: str, checked_at: datetime) -> None:
    if result in FAILED_CHECK_RESULTS:
        target.consecutive_failed_checks = min(target.consecutive_failed_checks + 1, MAX_FAILED_CHECKS)
    else:
        target.consecutive_failed_checks = 0
    target.last_checked_at = checked_at
    target.last_check_result = result
    target.next_check_at = checked_at + timedelta(days=collection_check_interval(target))
    if result == "found":
        target.last_found_at = checked_at
