"""Move expired operational history into durable, content-addressed gzip archives."""

from __future__ import annotations

import gzip
import hashlib
import json
import os
import tempfile
from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta
from pathlib import Path
from typing import Any

from sqlalchemy import and_, delete, exists, or_, select
from sqlalchemy.orm import Session, aliased

from app.config import HISTORY_RETENTION_DAYS, get_settings
from app.models import (
    AuditLog,
    CollectionCheck,
    CollectionRequestRecord,
    CompanyRequestRecord,
    IdempotencyRecord,
    OAuthToken,
)

DEFAULT_ARCHIVE_BATCH_SIZE = 1000


@dataclass(frozen=True)
class HistoryArchiveResult:
    archived_audit: int = 0
    archived_checks: int = 0
    archived_idempotency: int = 0
    archived_company_requests: int = 0
    archived_collection_requests: int = 0
    archived_oauth_tokens: int = 0


class ArchiveVerificationError(RuntimeError):
    """An archive path exists but does not contain the expected durable batch."""


def _json_value(value: Any) -> Any:
    if isinstance(value, datetime):
        if value.tzinfo is None:
            # SQLite returns UTC values from timezone-aware columns without tzinfo.
            value = value.replace(tzinfo=UTC)
        return value.isoformat()
    if isinstance(value, date | time):
        return value.isoformat()
    if isinstance(value, dict):
        return {key: _json_value(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_json_value(item) for item in value]
    return value


def _row_payload(model: type, row: Any) -> dict[str, Any]:
    return {column.name: _json_value(getattr(row, column.key)) for column in model.__table__.columns}


def _serialize_batch(model: type, rows: list[Any]) -> bytes:
    return b"".join(
        (
            json.dumps(
                _row_payload(model, row),
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
                allow_nan=False,
            )
            + "\n"
        ).encode("utf-8")
        for row in rows
    )


def _archive_path(root: Path, model: type, rows: list[Any], payload: bytes) -> Path:
    digest = hashlib.sha256(payload).hexdigest()
    first_id = min(row.id for row in rows)
    last_id = max(row.id for row in rows)
    filename = f"{first_id:020d}-{last_id:020d}-{digest}.jsonl.gz"
    return root / model.__tablename__ / filename


def _read_gzip(path: Path) -> bytes:
    with path.open("rb") as compressed:
        with gzip.GzipFile(fileobj=compressed, mode="rb") as archive:
            return archive.read()


def _fsync_directory(path: Path) -> None:
    flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0)
    directory_descriptor = os.open(path, flags)
    try:
        os.fsync(directory_descriptor)
    finally:
        os.close(directory_descriptor)


def _fsync_file(path: Path) -> None:
    file_descriptor = os.open(path, os.O_RDONLY)
    try:
        os.fsync(file_descriptor)
    finally:
        os.close(file_descriptor)


def _ensure_archive_directory(path: Path) -> None:
    missing: list[Path] = []
    current = path
    while not current.exists():
        missing.append(current)
        if current.parent == current:
            raise OSError("Could not find an existing parent for the history archive directory")
        current = current.parent

    for directory in reversed(missing):
        directory.mkdir(exist_ok=True)
        _fsync_directory(directory.parent)

    # Also repairs durability if a prior process stopped between mkdir and parent fsync.
    _fsync_directory(path.parent)


def _write_archive(path: Path, payload: bytes) -> None:
    _ensure_archive_directory(path.parent)

    if path.exists():
        if _read_gzip(path) != payload:
            raise ArchiveVerificationError("Existing history archive content does not match its address")
        _fsync_file(path)
        _fsync_directory(path.parent)
        return

    file_descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{path.name}.",
        suffix=".tmp",
        dir=path.parent,
    )
    temporary_path = Path(temporary_name)
    try:
        with os.fdopen(file_descriptor, "wb") as temporary_file:
            with gzip.GzipFile(filename="", fileobj=temporary_file, mode="wb", mtime=0) as archive:
                archive.write(payload)
            temporary_file.flush()
            os.fsync(temporary_file.fileno())

        # The temporary file is in the destination directory, so this rename is atomic.
        os.replace(temporary_path, path)
        _fsync_directory(path.parent)

        if _read_gzip(path) != payload:
            raise ArchiveVerificationError("Published history archive content does not match its address")
    finally:
        temporary_path.unlink(missing_ok=True)


def _archive_collection_check_filter(cutoff: datetime):
    recent_request = aliased(CollectionRequestRecord)
    has_unexpired_request = exists(
        select(recent_request.id).where(
            recent_request.request_id == CollectionCheck.request_id,
            recent_request.created_at >= cutoff,
        )
    )
    return ~has_unexpired_request


def _archive_audit_filter(cutoff: datetime):
    recent_company_request = aliased(CompanyRequestRecord)
    has_unexpired_merge_request = exists(
        select(recent_company_request.id).where(
            recent_company_request.request_id == AuditLog.request_id,
            recent_company_request.created_at >= cutoff,
        )
    )
    return ~(and_(AuditLog.action == "company_merge", has_unexpired_merge_request))


def _archive_oauth_token_filter(now: datetime, cutoff: datetime):
    same_grant_token = aliased(OAuthToken)
    has_active_token = exists(
        select(same_grant_token.id).where(
            same_grant_token.grant_id == OAuthToken.grant_id,
            same_grant_token.revoked_at.is_(None),
            or_(same_grant_token.expires_at.is_(None), same_grant_token.expires_at > now),
        )
    )
    return or_(
        and_(OAuthToken.kind == "access", OAuthToken.expires_at < cutoff),
        and_(
            ~has_active_token,
            or_(OAuthToken.revoked_at < cutoff, OAuthToken.expires_at < cutoff),
        ),
    )


def _archive_model_batches(
    db: Session,
    *,
    model: type,
    cutoff: datetime,
    archive_dir: Path,
    batch_size: int,
    extra_filter: Any = None,
) -> int:
    archived = 0
    while True:
        conditions = [model.created_at < cutoff]
        if extra_filter is not None:
            conditions.append(extra_filter)
        rows = list(
            db.scalars(
                select(model)
                .where(*conditions)
                .order_by(model.id)
                .limit(batch_size)
                .with_for_update(skip_locked=True, of=model)
            )
        )
        if not rows:
            return archived

        try:
            ids = [row.id for row in rows]
            payload = _serialize_batch(model, rows)
            archive_path = _archive_path(archive_dir, model, rows, payload)
            _write_archive(archive_path, payload)
            deleted = db.execute(delete(model).where(model.id.in_(ids)))
            db.commit()
        except Exception:
            db.rollback()
            raise
        archived += int(deleted.rowcount or 0)


def archive_expired_history(
    db: Session,
    *,
    now: datetime | None = None,
    batch_size: int = DEFAULT_ARCHIVE_BATCH_SIZE,
) -> HistoryArchiveResult:
    """Archive rows older than the fixed retention period, committing only after durable storage."""
    if batch_size <= 0:
        raise ValueError("batch_size must be positive")

    instant = now or datetime.now(UTC)
    if instant.tzinfo is None:
        instant = instant.replace(tzinfo=UTC)
    else:
        instant = instant.astimezone(UTC)
    cutoff = instant - timedelta(days=HISTORY_RETENTION_DAYS)
    archive_dir = Path(get_settings().history_archive_dir)

    # Request records are archived before checks so an expired request cannot indefinitely keep
    # its corresponding check in the hot table. Recent request records still protect their checks.
    counts = {
        "archived_audit": _archive_model_batches(
            db,
            model=AuditLog,
            cutoff=cutoff,
            archive_dir=archive_dir,
            batch_size=batch_size,
            extra_filter=_archive_audit_filter(cutoff),
        ),
        "archived_idempotency": _archive_model_batches(
            db, model=IdempotencyRecord, cutoff=cutoff, archive_dir=archive_dir, batch_size=batch_size
        ),
        "archived_company_requests": _archive_model_batches(
            db, model=CompanyRequestRecord, cutoff=cutoff, archive_dir=archive_dir, batch_size=batch_size
        ),
        "archived_collection_requests": _archive_model_batches(
            db, model=CollectionRequestRecord, cutoff=cutoff, archive_dir=archive_dir, batch_size=batch_size
        ),
        "archived_checks": _archive_model_batches(
            db,
            model=CollectionCheck,
            cutoff=cutoff,
            archive_dir=archive_dir,
            batch_size=batch_size,
            extra_filter=_archive_collection_check_filter(cutoff),
        ),
        "archived_oauth_tokens": _archive_model_batches(
            db,
            model=OAuthToken,
            cutoff=cutoff,
            archive_dir=archive_dir,
            batch_size=batch_size,
            extra_filter=_archive_oauth_token_filter(instant, cutoff),
        ),
    }
    return HistoryArchiveResult(**counts)
