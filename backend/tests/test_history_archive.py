import gzip
import json
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest
from sqlalchemy import select

from app.config import HISTORY_RETENTION_DAYS
from app.models import (
    AuditLog,
    CollectionCheck,
    CollectionRequestRecord,
    CollectionTarget,
    CompanyRequestRecord,
    IdempotencyRecord,
    OAuthClient,
    OAuthToken,
)
from app.schemas import OpportunityInput
from app.services import history_archive
from app.services.companies import get_or_create_company, merge_company
from app.services.history_archive import archive_expired_history
from app.services.opportunities import write_opportunity
from tests.test_validation import valid_payload


def _use_archive_dir(monkeypatch, tmp_path):
    monkeypatch.setattr(history_archive, "get_settings", lambda: SimpleNamespace(history_archive_dir=tmp_path))


def _create_opportunity_and_target(db, request_id: str = "archive-history-write-0001"):
    company = get_or_create_company(db, "株式会社履歴アーカイブ")
    target = CollectionTarget(company_id=company.id)
    db.add(target)
    db.flush()
    opportunity, _ = write_opportunity(
        db,
        data=OpportunityInput.model_validate(valid_payload() | {"company_name": company.name}),
        request_id=request_id,
        client_name="pytest",
    )
    db.expire_all()
    return company, target, opportunity


def _cutoff(now: datetime) -> datetime:
    return now - timedelta(days=HISTORY_RETENTION_DAYS)


def test_archives_expired_rows_and_keeps_cutoff_recent_and_retry_linked_rows(db, monkeypatch, tmp_path):
    _use_archive_dir(monkeypatch, tmp_path)
    now = datetime.now(UTC)
    cutoff = _cutoff(now)
    old = cutoff - timedelta(microseconds=1)
    recent = cutoff + timedelta(days=1)
    company, target, opportunity = _create_opportunity_and_target(db)

    source_audit = list(db.scalars(select(AuditLog).where(AuditLog.request_id == "archive-history-write-0001")))
    assert source_audit
    for row in source_audit:
        row.created_at = old
    boundary_audit = AuditLog(
        action="boundary",
        entity_type="test",
        success=True,
        created_at=cutoff,
        client_name="pytest",
    )
    recent_audit = AuditLog(
        action="recent",
        entity_type="test",
        success=False,
        created_at=recent,
        client_name="pytest",
    )
    db.add_all([boundary_audit, recent_audit])

    idempotency = db.scalar(
        select(IdempotencyRecord).where(IdempotencyRecord.request_id == "archive-history-write-0001")
    )
    assert idempotency is not None
    idempotency.created_at = old
    boundary_idempotency = IdempotencyRecord(
        request_id="archive-history-boundary-idempotency",
        operation="create",
        request_hash="1" * 64,
        opportunity_id=opportunity.id,
        response_data={"kind": "boundary"},
        created_at=cutoff,
    )
    recent_idempotency = IdempotencyRecord(
        request_id="archive-history-recent-idempotency",
        operation="create",
        request_hash="2" * 64,
        opportunity_id=opportunity.id,
        response_data={"kind": "recent"},
        created_at=recent,
    )
    db.add_all([boundary_idempotency, recent_idempotency])

    linked_check = db.scalar(
        select(CollectionCheck).where(CollectionCheck.request_id == "archive-history-write-0001")
    )
    assert linked_check is not None
    linked_check.created_at = old
    unlinked_old_check = CollectionCheck(
        collection_target_id=target.id,
        result="no_opening",
        checked_at=old,
        request_id="archive-history-unlinked-check",
        client_name="pytest",
        note="過去の確認",
        created_at=old,
    )
    boundary_check = CollectionCheck(
        collection_target_id=target.id,
        result="needs_review",
        checked_at=cutoff,
        request_id="archive-history-boundary-check",
        client_name="pytest",
        created_at=cutoff,
    )
    recent_check = CollectionCheck(
        collection_target_id=target.id,
        result="unreachable",
        checked_at=recent,
        request_id="archive-history-recent-check",
        client_name="pytest",
        created_at=recent,
    )
    db.add_all([unlinked_old_check, boundary_check, recent_check])
    db.add(
        CollectionRequestRecord(
            request_id="archive-history-write-0001",
            operation="create",
            request_hash="3" * 64,
            entity_type="opportunity",
            entity_id=opportunity.id,
            created_at=recent,
        )
    )

    db.add_all(
        [
            CompanyRequestRecord(
                request_id="archive-history-old-company-request",
                operation="company_alias_add",
                request_hash="4" * 64,
                company_id=company.id,
                created_at=old,
            ),
            CompanyRequestRecord(
                request_id="archive-history-boundary-company-request",
                operation="company_alias_add",
                request_hash="5" * 64,
                company_id=company.id,
                created_at=cutoff,
            ),
            CollectionRequestRecord(
                request_id="archive-history-old-collection-request",
                operation="collection_target_update",
                request_hash="6" * 64,
                entity_type="collection_target",
                entity_id=str(target.id),
                created_at=old,
            ),
            CollectionRequestRecord(
                request_id="archive-history-boundary-collection-request",
                operation="collection_target_update",
                request_hash="7" * 64,
                entity_type="collection_target",
                entity_id=str(target.id),
                created_at=cutoff,
            ),
        ]
    )
    db.commit()

    result = archive_expired_history(db, now=now, batch_size=2)
    db.expire_all()

    assert result.archived_audit == len(source_audit)
    assert result.archived_checks == 1
    assert result.archived_idempotency == 1
    assert result.archived_company_requests == 1
    assert result.archived_collection_requests == 1
    assert db.get(AuditLog, boundary_audit.id) is not None
    assert db.get(AuditLog, recent_audit.id) is not None
    assert db.get(IdempotencyRecord, boundary_idempotency.id) is not None
    assert db.get(IdempotencyRecord, recent_idempotency.id) is not None
    assert db.get(CollectionCheck, linked_check.id) is not None
    assert db.get(CollectionCheck, unlinked_old_check.id) is None
    assert db.get(CollectionCheck, boundary_check.id) is not None
    assert db.get(CollectionCheck, recent_check.id) is not None


def test_company_merge_audit_stays_until_its_request_record_expires(db, monkeypatch, tmp_path):
    _use_archive_dir(monkeypatch, tmp_path)
    now = datetime.now(UTC)
    cutoff = _cutoff(now)
    source = get_or_create_company(db, "株式会社統合元アーカイブ")
    target = get_or_create_company(db, "株式会社統合先アーカイブ")
    source_id = source.id
    target_id = target.id
    request_id = "archive-history-company-merge"
    _, expected_summary, replayed = merge_company(
        db,
        source_company_id=source_id,
        target_company_id=target_id,
        request_id=request_id,
        client_name="pytest",
    )
    assert replayed is False

    audit = db.scalar(select(AuditLog).where(AuditLog.action == "company_merge", AuditLog.request_id == request_id))
    request = db.scalar(select(CompanyRequestRecord).where(CompanyRequestRecord.request_id == request_id))
    assert audit is not None
    assert request is not None
    audit.created_at = cutoff - timedelta(seconds=1)
    request.created_at = cutoff + timedelta(seconds=1)
    db.commit()

    first_result = archive_expired_history(db, now=now)
    db.expire_all()

    assert first_result.archived_audit == 0
    assert first_result.archived_company_requests == 0
    assert db.get(AuditLog, audit.id) is not None
    assert db.get(CompanyRequestRecord, request.id) is not None
    replay_company, replay_summary, replayed = merge_company(
        db,
        source_company_id=source_id,
        target_company_id=target_id,
        request_id=request_id,
        client_name="pytest",
    )
    assert replayed is True
    assert replay_company.id == target_id
    assert replay_summary == expected_summary

    second_result = archive_expired_history(db, now=now + timedelta(seconds=2))
    db.expire_all()

    assert second_result.archived_audit == 1
    assert second_result.archived_company_requests == 1
    assert db.get(AuditLog, audit.id) is None
    assert db.get(CompanyRequestRecord, request.id) is None


def test_oauth_archiving_preserves_active_grants_and_moves_expired_access_and_terminal_grants(
    db, monkeypatch, tmp_path
):
    _use_archive_dir(monkeypatch, tmp_path)
    now = datetime.now(UTC)
    cutoff = _cutoff(now)
    old = cutoff - timedelta(days=1)
    client = OAuthClient(
        client_id="archive-history-oauth-client",
        client_name="pytest",
        redirect_uris=["https://client.example/callback"],
        grant_types=["authorization_code", "refresh_token"],
        token_endpoint_auth_method="none",
        created_at=old,
    )
    db.add(client)
    db.flush()

    active_refresh = OAuthToken(
        token_hash="1" * 64,
        kind="refresh",
        grant_id="active-grant",
        client_id=client.client_id,
        created_at=old,
    )
    revoked_refresh = OAuthToken(
        token_hash="2" * 64,
        kind="refresh",
        grant_id="active-grant",
        client_id=client.client_id,
        expires_at=None,
        revoked_at=old,
        created_at=old,
    )
    expired_access = OAuthToken(
        token_hash="3" * 64,
        kind="access",
        grant_id="active-grant",
        client_id=client.client_id,
        expires_at=cutoff - timedelta(seconds=1),
        created_at=old,
    )
    terminal_refresh = OAuthToken(
        token_hash="4" * 64,
        kind="refresh",
        grant_id="terminal-grant",
        client_id=client.client_id,
        expires_at=None,
        revoked_at=old,
        created_at=old,
    )
    db.add_all([active_refresh, revoked_refresh, expired_access, terminal_refresh])
    db.commit()

    result = archive_expired_history(db, now=now)
    db.expire_all()

    assert result.archived_oauth_tokens == 2
    assert db.get(OAuthToken, active_refresh.id) is not None
    assert db.get(OAuthToken, revoked_refresh.id) is not None
    assert db.get(OAuthToken, expired_access.id) is None
    assert db.get(OAuthToken, terminal_refresh.id) is None


def test_archive_is_gzip_jsonl_with_all_columns_and_iso8601_datetime(db, monkeypatch, tmp_path):
    _use_archive_dir(monkeypatch, tmp_path)
    now = datetime.now(UTC)
    old = _cutoff(now) - timedelta(days=1)
    row = AuditLog(
        action="archive_test",
        entity_type="opportunity",
        entity_id="opp-1",
        request_id="archive-history-fields",
        run_id="run-1",
        client_name="pytest",
        source_url="https://example.com/official",
        success=False,
        changes={"before": {"name": "前", "enabled": True}, "after": None},
        errors=[{"field": "name", "reason": "無効", "count": 2}],
        created_at=old,
    )
    db.add(row)
    db.commit()
    row_id = row.id

    result = archive_expired_history(db, now=now)
    db.expire_all()

    assert result.archived_audit == 1
    assert db.get(AuditLog, row_id) is None
    archives = list((tmp_path / "audit_logs").glob("*.jsonl.gz"))
    assert len(archives) == 1
    lines = gzip.decompress(archives[0].read_bytes()).decode("utf-8").splitlines()
    assert len(lines) == 1
    archived = json.loads(lines[0])
    assert set(archived) == {column.name for column in AuditLog.__table__.columns}
    assert archived == {
        "action": "archive_test",
        "changes": {"after": None, "before": {"enabled": True, "name": "前"}},
        "client_name": "pytest",
        "created_at": old.isoformat(),
        "entity_id": "opp-1",
        "entity_type": "opportunity",
        "errors": [{"count": 2, "field": "name", "reason": "無効"}],
        "id": row_id,
        "request_id": "archive-history-fields",
        "run_id": "run-1",
        "source_url": "https://example.com/official",
        "success": False,
    }
    assert isinstance(archived["success"], bool)
    assert isinstance(archived["changes"], dict)
    assert isinstance(archived["errors"], list)
    assert datetime.fromisoformat(archived["created_at"]).tzinfo == UTC


def test_archive_failure_keeps_database_rows_and_existing_archive_allows_retry(
    db, monkeypatch, tmp_path
):
    _use_archive_dir(monkeypatch, tmp_path)
    now = datetime.now(UTC)
    old = _cutoff(now) - timedelta(days=1)
    row = AuditLog(
        action="archive_retry",
        entity_type="test",
        success=True,
        created_at=old,
    )
    db.add(row)
    db.commit()
    row_id = row.id

    def fail_write(_path, _payload):
        raise OSError("archive storage unavailable")

    monkeypatch.setattr(history_archive, "_write_archive", fail_write)
    with pytest.raises(OSError, match="archive storage unavailable"):
        archive_expired_history(db, now=now)
    db.expire_all()
    assert db.get(AuditLog, row_id) is not None

    monkeypatch.undo()
    monkeypatch.setattr(history_archive, "get_settings", lambda: SimpleNamespace(history_archive_dir=tmp_path))
    row = db.get(AuditLog, row_id)
    assert row is not None
    payload = history_archive._serialize_batch(AuditLog, [row])
    archive_path = history_archive._archive_path(tmp_path, AuditLog, [row], payload)
    history_archive._write_archive(archive_path, payload)

    result = archive_expired_history(db, now=now)
    db.expire_all()
    assert result.archived_audit == 1
    assert db.get(AuditLog, row_id) is None
    assert len(list((tmp_path / "audit_logs").glob("*.jsonl.gz"))) == 1

    second_result = archive_expired_history(db, now=now)
    assert second_result.archived_audit == 0
    assert len(list((tmp_path / "audit_logs").glob("*.jsonl.gz"))) == 1


def test_database_commit_failure_keeps_rows_and_retry_reuses_one_archive_file(db, monkeypatch, tmp_path):
    _use_archive_dir(monkeypatch, tmp_path)
    now = datetime.now(UTC)
    row = AuditLog(
        action="archive_commit_retry",
        entity_type="test",
        success=True,
        created_at=_cutoff(now) - timedelta(days=1),
    )
    db.add(row)
    db.commit()
    row_id = row.id
    commit = db.commit
    commit_failed = False

    def fail_first_commit():
        nonlocal commit_failed
        if not commit_failed:
            commit_failed = True
            raise RuntimeError("database commit unavailable")
        commit()

    monkeypatch.setattr(db, "commit", fail_first_commit)
    with pytest.raises(RuntimeError, match="database commit unavailable"):
        archive_expired_history(db, now=now)
    db.expire_all()

    assert db.get(AuditLog, row_id) is not None
    archives = list((tmp_path / "audit_logs").glob("*.jsonl.gz"))
    assert len(archives) == 1

    result = archive_expired_history(db, now=now)
    db.expire_all()

    assert result.archived_audit == 1
    assert db.get(AuditLog, row_id) is None
    assert list((tmp_path / "audit_logs").glob("*.jsonl.gz")) == archives


def test_gzip_readback_verification_failure_keeps_rows_and_allows_retry(db, monkeypatch, tmp_path):
    _use_archive_dir(monkeypatch, tmp_path)
    now = datetime.now(UTC)
    row = AuditLog(
        action="archive_verification_retry",
        entity_type="test",
        success=True,
        created_at=_cutoff(now) - timedelta(days=1),
    )
    db.add(row)
    db.commit()
    row_id = row.id
    read_gzip = history_archive._read_gzip
    monkeypatch.setattr(history_archive, "_read_gzip", lambda _path: b"mismatched archive payload")

    with pytest.raises(history_archive.ArchiveVerificationError, match="Published history archive"):
        archive_expired_history(db, now=now)
    db.expire_all()

    assert db.get(AuditLog, row_id) is not None
    archives = list((tmp_path / "audit_logs").glob("*.jsonl.gz"))
    assert len(archives) == 1

    monkeypatch.setattr(history_archive, "_read_gzip", read_gzip)
    result = archive_expired_history(db, now=now)
    db.expire_all()

    assert result.archived_audit == 1
    assert db.get(AuditLog, row_id) is None
    assert list((tmp_path / "audit_logs").glob("*.jsonl.gz")) == archives
