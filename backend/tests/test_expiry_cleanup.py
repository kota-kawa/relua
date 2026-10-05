import gzip
import json
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest
from sqlalchemy import select

from app.config import HISTORY_RETENTION_DAYS
from app.dates import today_in_tokyo
from app.models import CollectionCheck, CollectionTarget, IdempotencyRecord, Opportunity
from app.schemas import OpportunityInput
from app.scripts.close_expired import OPPORTUNITY_SOFT_DELETE_RETENTION_DAYS, expire_and_purge_opportunities
from app.services import history_archive
from app.services.history_archive import archive_expired_history
from app.services.opportunities import DomainValidationError, write_opportunity
from tests.test_validation import valid_payload


def test_expiry_job_waits_for_idempotency_archive_before_purging(db, monkeypatch, tmp_path):
    now = datetime.now(timezone.utc)  # noqa: UP017 -- tests also support Python 3.10
    expired_payload = OpportunityInput.model_validate(
        valid_payload()
        | {
            "company_name": "株式会社期限切れ",
            "source_url": "https://example.com/expired-posting",
            "deadline": (today_in_tokyo(now) - timedelta(days=1)).isoformat(),
        }
    )
    expired, _ = write_opportunity(
        db,
        data=expired_payload,
        request_id="expiry-cleanup-expire-0001",
        client_name="pytest",
    )
    purged_payload = OpportunityInput.model_validate(
        valid_payload()
        | {
            "company_name": "株式会社完全削除",
            "event_name": "完全削除対象",
            "source_url": "https://example.com/purge-posting",
        }
    )
    purged, _ = write_opportunity(
        db,
        data=purged_payload,
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
    idempotency = db.scalar(
        select(IdempotencyRecord).where(IdempotencyRecord.request_id == "expiry-cleanup-purge-0001")
    )
    assert idempotency is not None
    db.commit()

    with pytest.raises(DomainValidationError) as replay_error:
        write_opportunity(
            db,
            data=purged_payload,
            request_id="expiry-cleanup-purge-0001",
            client_name="pytest",
        )
    assert replay_error.value.errors[0]["reason"] == "前回の操作対象は現在削除されています"

    result = expire_and_purge_opportunities(db, now=now)
    db.expire_all()

    assert result.purged == 0
    expired_after = db.get(Opportunity, expired.id)
    assert expired_after is not None
    assert expired_after.deleted_at is None
    assert expired_after.status.name == "募集中"
    assert db.get(Opportunity, purged.id) is not None
    assert db.get(CollectionCheck, check.id).opportunity_id == purged.id
    retained_record = db.scalar(
        select(IdempotencyRecord).where(IdempotencyRecord.opportunity_id == purged.id)
    )
    assert retained_record is not None
    retained_at = retained_record.created_at
    if retained_at.tzinfo is None:
        retained_at = retained_at.replace(tzinfo=timezone.utc)  # noqa: UP017 -- tests also support Python 3.10
    assert retained_at >= now - timedelta(days=HISTORY_RETENTION_DAYS)

    monkeypatch.setattr(
        history_archive,
        "get_settings",
        lambda: SimpleNamespace(history_archive_dir=tmp_path),
    )
    retained_record.created_at = now - timedelta(days=HISTORY_RETENTION_DAYS + 1)
    db.commit()
    write_archive = history_archive._write_archive

    def fail_archive(_path, _payload):
        raise OSError("archive storage unavailable")

    monkeypatch.setattr(history_archive, "_write_archive", fail_archive)
    with pytest.raises(OSError, match="archive storage unavailable"):
        archive_expired_history(db, now=now)
    db.expire_all()
    assert db.scalar(select(IdempotencyRecord).where(IdempotencyRecord.opportunity_id == purged.id)) is not None

    failed_archive_purge = expire_and_purge_opportunities(db, now=now)
    db.expire_all()
    assert failed_archive_purge.purged == 0
    assert db.get(Opportunity, purged.id) is not None

    monkeypatch.setattr(history_archive, "_write_archive", write_archive)
    archived = archive_expired_history(db, now=now)
    assert archived.archived_idempotency == 1
    assert db.scalar(select(IdempotencyRecord).where(IdempotencyRecord.opportunity_id == purged.id)) is None
    archive_files = list((tmp_path / "idempotency_records").glob("*.jsonl.gz"))
    assert len(archive_files) == 1
    archived_rows = [
        json.loads(line)
        for line in gzip.decompress(archive_files[0].read_bytes()).decode("utf-8").splitlines()
    ]
    assert len(archived_rows) == 1
    assert archived_rows[0]["request_id"] == "expiry-cleanup-purge-0001"
    assert archived_rows[0]["opportunity_id"] == purged.id

    result_after_archive = expire_and_purge_opportunities(db, now=now)
    db.expire_all()
    assert result_after_archive.purged == 1
    assert db.get(Opportunity, purged.id) is None
    assert db.get(CollectionCheck, check.id).opportunity_id is None
