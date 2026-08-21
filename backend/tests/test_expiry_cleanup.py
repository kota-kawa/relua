from datetime import UTC, datetime, timedelta, timezone

from sqlalchemy import select

from app.dates import today_in_tokyo
from app.models import CollectionCheck, CollectionTarget, IdempotencyRecord, Opportunity, RecruitmentStatus
from app.schemas import OpportunityInput
from app.scripts.close_expired import OPPORTUNITY_SOFT_DELETE_RETENTION_DAYS, expire_and_purge_opportunities
from app.services.opportunities import write_opportunity
from tests.test_validation import valid_payload


def test_expiry_job_soft_deletes_past_deadlines_then_purges_after_30_days(db):
    now = datetime.now(timezone.utc)  # noqa: UP017 -- tests also support Python 3.10
    expired, _ = write_opportunity(
        db,
        data=OpportunityInput.model_validate(
            valid_payload()
            | {
                "company_name": "株式会社期限切れ",
                "source_url": "https://example.com/expired-posting",
                "deadline": (today_in_tokyo(now) - timedelta(days=1)).isoformat(),
            }
        ),
        request_id="expiry-cleanup-expire-0001",
        client_name="pytest",
    )
    purged, _ = write_opportunity(
        db,
        data=OpportunityInput.model_validate(
            valid_payload()
            | {
                "company_name": "株式会社完全削除",
                "event_name": "完全削除対象",
                "source_url": "https://example.com/purge-posting",
            }
        ),
        request_id="expiry-cleanup-purge-0001",
        client_name="pytest",
    )
    target = CollectionTarget(company_id=purged.company_id)
    db.add(target)
    db.flush()
    check = CollectionCheck(
        collection_target_id=target.id,
        result="no_opening",
        opportunity_id=purged.id,
        request_id="expiry-cleanup-check-0001",
        client_name="pytest",
    )
    db.add(check)
    purged.deleted_at = now - timedelta(days=OPPORTUNITY_SOFT_DELETE_RETENTION_DAYS)
    db.commit()

    result = expire_and_purge_opportunities(db, now=now)
    db.expire_all()

    assert result.expired == 1
    assert result.purged == 1
    expired_after = db.get(Opportunity, expired.id)
    assert expired_after is not None
    assert expired_after.deleted_at.replace(tzinfo=UTC) == now
    assert expired_after.status_id == db.scalar(select(RecruitmentStatus.id).where(RecruitmentStatus.name == "締切"))
    assert db.get(Opportunity, purged.id) is None
    assert db.get(CollectionCheck, check.id).opportunity_id is None
    assert db.scalar(select(IdempotencyRecord).where(IdempotencyRecord.opportunity_id == purged.id)) is None
