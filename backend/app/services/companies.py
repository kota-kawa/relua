import hashlib
import json
import math
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from difflib import SequenceMatcher
from typing import Any, Literal

from fastapi.encoders import jsonable_encoder
from sqlalchemy import func, literal, or_, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, selectinload
from sqlalchemy.sql.elements import ColumnElement

from app.models import (
    PUBLIC_CODE_LENGTH,
    AuditLog,
    CollectionCheck,
    CollectionRequestRecord,
    CollectionSource,
    CollectionTarget,
    Company,
    CompanyAlias,
    CompanyIndustry,
    CompanyRequestRecord,
    Industry,
    Opportunity,
    public_code_string,
)
from app.schemas import COMPANY_PROFILE_FIELD_NAMES, CompanyIndustryInput
from app.services.company_industries import (
    company_industry_dict,
    resolve_company_industries,
    set_company_industries,
)
from app.services.normalization import normalize_company_name
from app.services.serialization import company_business_areas, public_company_url

#: Profile fields a caller may write through update_company_profile, in the order a merge fills
#: gaps in. The set itself is defined next to the input schema so validation and storage agree.
COMPANY_PROFILE_FIELDS = ("business_summary", "description", "business_areas", "website_url")
assert set(COMPANY_PROFILE_FIELDS) == set(COMPANY_PROFILE_FIELD_NAMES)

CompanyMatchType = Literal["canonical_exact", "alias_exact", "partial", "fuzzy"]
COMPANY_FUZZY_THRESHOLD = 0.3
PROFILE_TEXT_WHITESPACE = " \t\n\r\v\f\u00a0\u3000"

#: LIKE/ILIKE has no default escape character in either PostgreSQL or SQLite, so one has to be
#: declared on every comparison that uses a pattern built from user input. Mirrors
#: services/opportunities.py's LIKE_ESCAPE_CHARACTER/_like_contains rather than importing them:
#: opportunities.py already imports company_name_filter etc. from this module, so importing back
#: from it here would be circular.
LIKE_ESCAPE_CHARACTER = "\\"


def _like_contains(value: str) -> str:
    """Build a ``%...%`` pattern that matches the caller's text literally.

    Without escaping, a company search of "%" matches every row - and is then reported to the user
    as a keyword hit - while "_" matches any single character, and neither pattern can use an index.
    Every ilike() given one of these patterns must also pass escape=LIKE_ESCAPE_CHARACTER.
    """
    escaped = value.replace(LIKE_ESCAPE_CHARACTER, LIKE_ESCAPE_CHARACTER * 2)
    for wildcard in ("%", "_"):
        escaped = escaped.replace(wildcard, LIKE_ESCAPE_CHARACTER + wildcard)
    return f"%{escaped}%"


class CompanyIdentityValidationError(Exception):
    def __init__(self, errors: list[dict[str, Any]]):
        self.errors = errors
        super().__init__("validation_failed")


@dataclass(frozen=True)
class CompanyCandidate:
    company: Company
    match_type: CompanyMatchType
    matched_name: str
    score: float


@dataclass
class CompanyProfileGapList:
    items: list[Company]
    total: int
    page: int
    per_page: int

    @property
    def total_pages(self) -> int:
        return max(1, math.ceil(self.total / self.per_page))


@dataclass
class CompanyProfileHistoryPage:
    items: list[AuditLog]
    total: int
    page: int
    per_page: int

    @property
    def total_pages(self) -> int:
        return max(1, math.ceil(self.total / self.per_page))


def company_identity_dict(company: Company) -> dict[str, Any]:
    return {
        "id": company.id,
        "public_code": company.public_code,
        "url": public_company_url(company.public_code),
        "canonical_name": company.name,
        "normalized_name": company.normalized_name,
        "business_summary": company.business_summary,
        "description": company.description,
        "business_areas": company_business_areas(company),
        "website_url": company.website_url,
        "updated_at": company.updated_at,
        "aliases": [
            {"id": alias.id, "alias": alias.alias, "normalized_alias": alias.normalized_alias}
            for alias in sorted(company.aliases, key=lambda item: (item.normalized_alias, item.id))
        ],
        "industries": [
            company_industry_dict(row)
            for row in sorted(company.industries, key=lambda item: (not item.is_primary, item.id))
        ],
    }


def find_company(db: Session, name: str) -> Company | None:
    """Resolve a company by its own normalized name or a registered alias."""
    normalized = normalize_company_name(name)
    if not normalized:
        return None
    company = db.scalar(select(Company).where(Company.normalized_name == normalized))
    if company is not None:
        return company
    alias = db.scalar(select(CompanyAlias).where(CompanyAlias.normalized_alias == normalized))
    return alias.company if alias else None


def _unique_company_public_code(db: Session) -> str:
    for _ in range(10):
        code = public_code_string()
        if db.scalar(select(Company.id).where(Company.public_code == code)) is None:
            return code
    raise RuntimeError("企業の公開コードを生成できませんでした")


def company_profile_query() -> Any:
    """Company with its classification eagerly loaded.

    CompanyIndustry.industry and .sector are lazy, so a page that renders every category would
    otherwise issue one query per row.
    """
    return select(Company).options(
        selectinload(Company.industries).selectinload(CompanyIndustry.industry),
        selectinload(Company.industries).selectinload(CompanyIndustry.sector),
    )


def get_company_by_public_code(db: Session, public_code: str) -> Company | None:
    """Resolve the public company code. Case-insensitive so a hand-typed lowercase URL still works."""
    if len(public_code) != PUBLIC_CODE_LENGTH:
        return None
    return db.scalar(company_profile_query().where(Company.public_code == public_code.upper()))


def get_or_create_company(db: Session, name: str) -> Company:
    company = find_company(db, name)
    if company is not None:
        return company
    normalized = normalize_company_name(name)
    # Look-then-insert is not atomic: two concurrent postings naming the same new company both miss
    # above and race into the INSERT, and the loser would otherwise surface companies.name /
    # normalized_name UNIQUE as a raw IntegrityError, i.e. a 500 for a perfectly ordinary write.
    # The savepoint keeps that failure from poisoning the outer transaction so the winner's row can
    # simply be re-read - the same recovery add_company_alias already performs.
    try:
        with db.begin_nested():
            company = Company(name=name, normalized_name=normalized, public_code=_unique_company_public_code(db))
            db.add(company)
            db.flush()
    except IntegrityError:
        company = find_company(db, name)
        if company is None:
            raise
    return company


def replace_company_industries(
    db: Session,
    *,
    company_id: int,
    entries: list[CompanyIndustryInput],
    request_id: str,
    client_name: str,
) -> tuple[Company, bool]:
    """Replace an existing company's complete category list atomically and idempotently."""

    operation = "company_industries_update"
    request_hash = _request_hash(
        operation,
        {
            "company_id": company_id,
            "industries": [entry.model_dump(mode="json") for entry in entries],
        },
    )
    replayed = _replayed_company(db, request_id=request_id, operation=operation, request_hash=request_hash)
    if replayed is not None:
        return replayed, True

    company = db.get(Company, company_id)
    if company is None:
        raise LookupError("company_not_found")
    resolved, errors = resolve_company_industries(db, entries)
    if errors:
        raise CompanyIdentityValidationError(errors)

    # A posting written earlier in this session may have added a classification after the Company's
    # select-in-loaded relationship was populated. Refresh it so the audit snapshot includes every
    # category that currently belongs to the company.
    db.expire(company, ["industries"])
    before = company_identity_dict(company)
    set_company_industries(db, company=company, classifications=resolved)
    db.expire(company, ["industries"])
    _remember_request(
        db,
        request_id=request_id,
        operation=operation,
        request_hash=request_hash,
        company_id=company.id,
    )
    db.flush()
    _audit_identity(
        db,
        action=operation,
        company=company,
        request_id=request_id,
        client_name=client_name,
        before=before,
    )
    db.commit()
    return company, False


def _best_name(company: Company, normalized_query: str) -> tuple[str, float]:
    names = [(company.name, company.normalized_name)] + [
        (alias.alias, alias.normalized_alias) for alias in company.aliases
    ]
    matched_name, matched_normalized = max(
        names, key=lambda item: SequenceMatcher(None, normalized_query, item[1]).ratio()
    )
    score = SequenceMatcher(None, normalized_query, matched_normalized).ratio()
    if normalized_query in matched_normalized or matched_normalized in normalized_query:
        score = max(score, 0.85)
    return matched_name, score


def resolve_company_candidates(
    db: Session, query: str, *, limit: int = 5, threshold: float = COMPANY_FUZZY_THRESHOLD
) -> list[CompanyCandidate]:
    """Return exact identities first and review-only partial/fuzzy candidates otherwise."""
    normalized = normalize_company_name(query)
    if not normalized:
        raise CompanyIdentityValidationError(
            [{"field": "企業名", "received": query, "reason": "正規化後の企業名が空です"}]
        )

    company = db.scalar(select(Company).where(Company.normalized_name == normalized))
    if company is not None:
        return [CompanyCandidate(company, "canonical_exact", company.name, 1.0)]
    alias = db.scalar(select(CompanyAlias).where(CompanyAlias.normalized_alias == normalized))
    if alias is not None:
        return [CompanyCandidate(alias.company, "alias_exact", alias.alias, 1.0)]

    normalized_term = _like_contains(normalized)
    if db.get_bind().dialect.name == "postgresql":
        alias_score = (
            select(func.coalesce(func.max(func.similarity(CompanyAlias.normalized_alias, normalized)), 0.0))
            .where(CompanyAlias.company_id == Company.id)
            .correlate(Company)
            .scalar_subquery()
        )
        score = func.greatest(func.similarity(Company.normalized_name, normalized), alias_score)
        candidates = list(
            db.scalars(
                select(Company)
                .where(
                    or_(
                        Company.normalized_name.ilike(normalized_term, escape=LIKE_ESCAPE_CHARACTER),
                        Company.normalized_name.op("%")(literal(normalized)),
                        Company.aliases.any(
                            CompanyAlias.normalized_alias.ilike(normalized_term, escape=LIKE_ESCAPE_CHARACTER)
                        ),
                        Company.aliases.any(CompanyAlias.normalized_alias.op("%")(literal(normalized))),
                    )
                )
                .order_by(score.desc(), Company.name)
                .limit(max(limit * 5, 25))
            ).unique()
        )
    else:
        candidates = list(db.scalars(select(Company).order_by(Company.name)).unique())

    resolved = []
    for candidate in candidates:
        matched_name, candidate_score = _best_name(candidate, normalized)
        matched_normalized = normalize_company_name(matched_name)
        partial = normalized in matched_normalized or matched_normalized in normalized
        if not partial and candidate_score < threshold:
            continue
        resolved.append(
            CompanyCandidate(
                candidate,
                "partial" if partial else "fuzzy",
                matched_name,
                round(candidate_score, 4),
            )
        )
    return sorted(resolved, key=lambda item: (-item.score, item.company.name))[:limit]


def _request_hash(operation: str, payload: dict[str, Any]) -> str:
    serialized = json.dumps(
        {"operation": operation, **payload}, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    )
    return hashlib.sha256(serialized.encode()).hexdigest()


def _request_id_error(request_id: str) -> dict[str, Any]:
    return {
        "field": "request_id",
        "received": request_id,
        "reason": "このrequest_idは別の企業操作（別の企業、別の内容、または別のツール）で使用済みです",
        "expected": "これまでに使っていない一意なrequest_id",
        "alternative": "入力内容の問題ではありません。新しいrequest_idを発行して同じ内容を再送してください",
    }


def _replayed_company(db: Session, *, request_id: str, operation: str, request_hash: str) -> Company | None:
    previous = db.scalar(select(CompanyRequestRecord).where(CompanyRequestRecord.request_id == request_id))
    if previous is None:
        return None
    if previous.operation != operation or previous.request_hash != request_hash:
        raise CompanyIdentityValidationError([_request_id_error(request_id)])
    company = db.get(Company, previous.company_id)
    if company is None:
        raise RuntimeError("company identity idempotency target not found")
    return company


def _remember_request(db: Session, *, request_id: str, operation: str, request_hash: str, company_id: int) -> None:
    db.add(
        CompanyRequestRecord(
            request_id=request_id,
            operation=operation,
            request_hash=request_hash,
            company_id=company_id,
        )
    )


def _audit_identity(
    db: Session,
    *,
    action: str,
    company: Company,
    request_id: str,
    client_name: str,
    before: dict[str, Any],
    source_url: str | None = None,
) -> None:
    db.add(
        AuditLog(
            action=action,
            entity_type="company",
            entity_id=str(company.id),
            request_id=request_id,
            client_name=client_name,
            source_url=source_url,
            success=True,
            changes={"before": jsonable_encoder(before), "after": jsonable_encoder(company_identity_dict(company))},
        )
    )


def add_company_alias(
    db: Session, *, company_id: int, alias: str, request_id: str, client_name: str
) -> tuple[Company, bool, bool]:
    normalized = normalize_company_name(alias)
    if not normalized:
        raise CompanyIdentityValidationError([{"field": "別名", "received": alias, "reason": "正規化後の別名が空です"}])
    operation = "company_alias_add"
    request_hash = _request_hash(operation, {"company_id": company_id, "normalized_alias": normalized})
    replayed = _replayed_company(db, request_id=request_id, operation=operation, request_hash=request_hash)
    if replayed is not None:
        return replayed, False, True

    company = db.get(Company, company_id)
    if company is None:
        raise LookupError("company_not_found")
    before = company_identity_dict(company)

    canonical_collision = db.scalar(select(Company).where(Company.normalized_name == normalized))
    if canonical_collision is not None and canonical_collision.id != company.id:
        raise CompanyIdentityValidationError(
            [
                {
                    "field": "別名",
                    "received": alias,
                    "reason": f"別の企業「{canonical_collision.name}」の正式名と一致します",
                    "expected": "他社の正式名・別名と重複しない名称",
                }
            ]
        )

    existing = db.scalar(select(CompanyAlias).where(CompanyAlias.normalized_alias == normalized))
    if existing is not None and existing.company_id != company.id:
        raise CompanyIdentityValidationError(
            [
                {
                    "field": "別名",
                    "received": alias,
                    "reason": f"別の企業「{existing.company.name}」の別名として登録済みです",
                    "expected": "他社の正式名・別名と重複しない名称",
                }
            ]
        )

    created = canonical_collision is None and existing is None
    if created:
        try:
            with db.begin_nested():
                db.add(CompanyAlias(company_id=company.id, alias=alias, normalized_alias=normalized))
                db.flush()
        except IntegrityError as exc:
            existing = db.scalar(select(CompanyAlias).where(CompanyAlias.normalized_alias == normalized))
            if existing is None or existing.company_id != company.id:
                raise CompanyIdentityValidationError(
                    [{"field": "別名", "received": alias, "reason": "別名が別の企業と競合しました"}]
                ) from exc
            created = False

    db.expire(company, ["aliases"])
    _remember_request(
        db,
        request_id=request_id,
        operation=operation,
        request_hash=request_hash,
        company_id=company.id,
    )
    db.flush()
    _audit_identity(
        db,
        action="company_alias_add",
        company=company,
        request_id=request_id,
        client_name=client_name,
        before=before,
    )
    db.commit()
    return company, created, False


def update_company_profile(
    db: Session,
    *,
    company_id: int,
    changes: dict[str, Any],
    source_url: str,
    request_id: str,
    client_name: str,
    expected_updated_at: datetime | None = None,
) -> tuple[Company, bool, bool]:
    """Write the operator-confirmed company profile.

    A patch: only the keys present in ``changes`` are touched, and an explicit ``None`` clears the
    field.  ``business_areas`` is the exception, replacing the stored set as a whole, the same way a
    company's industry list is replaced.  ``source_url`` is the company page the text was read from
    and is kept in the audit log rather than on the row, matching how a posting separates its content
    from the evidence for it.

    Every length rule lives on ``CompanyProfileUpdateRequest``; by the time a value reaches here it
    is either absent, null, or long enough to be worth showing.
    """
    unknown = [key for key in changes if key not in COMPANY_PROFILE_FIELDS]
    if unknown:
        raise CompanyIdentityValidationError(
            [{"field": unknown[0], "received": unknown[0], "reason": "企業プロフィールの項目ではありません"}]
        )

    operation = "company_profile_update"
    # The hash carries the keys as sent, so "field omitted" and "field explicitly cleared" are two
    # different operations and cannot replay each other's result.
    payload = {"company_id": company_id, "changes": changes, "source_url": source_url}
    if expected_updated_at is not None:
        expected_updated_at = expected_updated_at.replace(tzinfo=expected_updated_at.tzinfo or UTC)
        expected_updated_at = expected_updated_at.astimezone(UTC)
        payload["expected_updated_at"] = expected_updated_at.isoformat()
    request_hash = _request_hash(operation, payload)
    replayed = _replayed_company(db, request_id=request_id, operation=operation, request_hash=request_hash)
    if replayed is not None:
        return replayed, False, True

    company = db.scalar(
        select(Company)
        .where(Company.id == company_id)
        .with_for_update(of=Company)
        .execution_options(populate_existing=True)
    )
    if company is None:
        raise LookupError("company_not_found")
    # A concurrent retry may have committed while this request waited for the row lock.
    replayed = _replayed_company(db, request_id=request_id, operation=operation, request_hash=request_hash)
    if replayed is not None:
        return replayed, False, True
    actual_updated_at = company.updated_at.replace(tzinfo=company.updated_at.tzinfo or UTC)
    actual_updated_at = actual_updated_at.astimezone(UTC)
    if expected_updated_at is not None and actual_updated_at != expected_updated_at:
        raise CompanyIdentityValidationError(
            [
                {
                    "field": "更新前の最終確認日時",
                    "received": expected_updated_at.isoformat(),
                    "reason": "取得後に企業情報が更新されています",
                    "expected": actual_updated_at.isoformat(),
                    "alternative": "企業一覧で最新値を取得し、変更内容を確認して新しいrequest_idで再試行してください",
                }
            ]
        )
    before = company_identity_dict(company)

    changed = False
    for field, value in changes.items():
        if getattr(company, field) != value:
            setattr(company, field, value)
            changed = True

    if changed:
        # Explicit microseconds keep successive writes distinct even within the same DB clock tick.
        company.updated_at = max(datetime.now(UTC), actual_updated_at + timedelta(microseconds=1))

    _remember_request(
        db,
        request_id=request_id,
        operation=operation,
        request_hash=request_hash,
        company_id=company.id,
    )
    db.flush()
    _audit_identity(
        db,
        action=operation,
        company=company,
        request_id=request_id,
        client_name=client_name,
        before=before,
        source_url=source_url,
    )
    db.commit()
    return company, changed, False


def delete_company_alias(db: Session, *, alias_id: int, request_id: str, client_name: str) -> tuple[Company, bool]:
    operation = "company_alias_delete"
    request_hash = _request_hash(operation, {"alias_id": alias_id})
    replayed = _replayed_company(db, request_id=request_id, operation=operation, request_hash=request_hash)
    if replayed is not None:
        return replayed, True

    alias = db.get(CompanyAlias, alias_id)
    if alias is None:
        raise LookupError("company_alias_not_found")
    company = alias.company
    before = company_identity_dict(company)
    db.delete(alias)
    db.flush()
    db.expire(company, ["aliases"])
    _remember_request(
        db,
        request_id=request_id,
        operation=operation,
        request_hash=request_hash,
        company_id=company.id,
    )
    db.flush()
    _audit_identity(
        db,
        action="company_alias_delete",
        company=company,
        request_id=request_id,
        client_name=client_name,
        before=before,
    )
    db.commit()
    return company, False


def _company_merge_error(field: str, received: Any, reason: str) -> CompanyIdentityValidationError:
    return CompanyIdentityValidationError([{"field": field, "received": received, "reason": reason}])


def _latest(*values: Any) -> Any:
    return max((value for value in values if value is not None), default=None)


def _earliest_due(*values: Any) -> Any:
    """Merge two next_check_at values, keeping the soonest re-check.

    A NULL next_check_at is not "unknown, ignore it": list_collection_targets(due_only=True) reads it
    as "due now", so it is the earliest value there is. Taking MIN over the non-NULL values instead
    would push a never-checked company's re-check out by the surviving target's whole interval.
    """
    if any(value is None for value in values):
        return None
    return min(values, default=None)


def _remap_collection_request_records(db: Session, *, entity_type: str, old_id: int, new_id: int) -> int:
    """Point replayable collection writes at the row that survived a merge.

    ``collection_request_records.entity_id`` is a plain string with no foreign key, so deleting the
    row it names leaves the idempotency record dangling.  Replaying that request_id then makes
    create_collection_target / add_collection_source resolve an id that no longer exists and raise
    ``RuntimeError`` - a 500 for a retry that is supposed to be a silent no-op.  ``company_request_records``
    has always been remapped this way in merge_company; this closes the same gap on the collection side.
    """
    result = db.execute(
        update(CollectionRequestRecord)
        .where(
            CollectionRequestRecord.entity_type == entity_type,
            CollectionRequestRecord.entity_id == str(old_id),
        )
        .values(entity_id=str(new_id))
    )
    return int(result.rowcount or 0)


def _merge_collection_targets(
    db: Session, *, source_company_id: int, target_company_id: int
) -> dict[str, int]:
    """Move or coalesce the one-per-company collection targets.

    A duplicate source URL is deliberately represented once on the target.  Checks are append-only
    evidence, so all of them are retained even when the target rows themselves are coalesced.
    """
    source_target = db.scalar(
        select(CollectionTarget).where(CollectionTarget.company_id == source_company_id).with_for_update()
    )
    target_target = db.scalar(
        select(CollectionTarget).where(CollectionTarget.company_id == target_company_id).with_for_update()
    )
    summary = {"collection_targets_merged": 0, "collection_sources_moved": 0, "collection_sources_deduplicated": 0,
               "collection_checks_moved": 0, "collection_request_records_remapped": 0}
    if source_target is None:
        return summary

    if target_target is None:
        source_target.company_id = target_company_id
        summary["collection_targets_merged"] = 1
        return summary

    target_sources = list(
        db.scalars(select(CollectionSource).where(CollectionSource.collection_target_id == target_target.id).with_for_update())
    )
    source_by_url = {item.url: item for item in target_sources}
    source_sources = list(
        db.scalars(select(CollectionSource).where(CollectionSource.collection_target_id == source_target.id).with_for_update())
    )
    for item in source_sources:
        surviving = source_by_url.get(item.url)
        if surviving is not None:
            summary["collection_request_records_remapped"] += _remap_collection_request_records(
                db, entity_type="collection_source", old_id=item.id, new_id=surviving.id
            )
            db.delete(item)
            summary["collection_sources_deduplicated"] += 1
        else:
            item.collection_target_id = target_target.id
            source_by_url[item.url] = item
            summary["collection_sources_moved"] += 1

    source_checks = list(
        db.scalars(select(CollectionCheck).where(CollectionCheck.collection_target_id == source_target.id).with_for_update())
    )
    for item in source_checks:
        item.collection_target_id = target_target.id
    summary["collection_checks_moved"] = len(source_checks)

    # Preserve the more conservative schedule and the freshest evidence.  A merge must not turn an
    # active target inactive or postpone a review that either former target had already scheduled.
    source_was_latest = (
        source_target.last_checked_at is not None
        and (target_target.last_checked_at is None or source_target.last_checked_at > target_target.last_checked_at)
    )
    target_target.priority_tier = min(target_target.priority_tier, source_target.priority_tier)
    target_target.check_interval_days = min(target_target.check_interval_days, source_target.check_interval_days)
    target_target.is_active = target_target.is_active or source_target.is_active
    target_target.last_checked_at = _latest(target_target.last_checked_at, source_target.last_checked_at)
    target_target.next_check_at = _earliest_due(target_target.next_check_at, source_target.next_check_at)
    target_target.last_found_at = _latest(target_target.last_found_at, source_target.last_found_at)
    if source_was_latest:
        # last_checked_at and last_check_result describe the same event, so they move together or not
        # at all.  Migration 20260820_0012 took MAX(last_checked_at) while leaving the keeper's own
        # (often NULL) last_check_result behind, which makes _check_status report "needs_review" for a
        # target that had in fact just been checked; the follow-up revision repairs those rows.
        target_target.last_check_result = source_target.last_check_result
        target_target.consecutive_failed_checks = source_target.consecutive_failed_checks
    if target_target.selection_reason is None:
        target_target.selection_reason = source_target.selection_reason
    # The losing target's id disappears below, so any idempotency record naming it has to follow the
    # surviving row before the delete.
    summary["collection_request_records_remapped"] += _remap_collection_request_records(
        db, entity_type="collection_target", old_id=source_target.id, new_id=target_target.id
    )
    # CollectionTarget also owns sources/checks through delete-orphan relationships.  Refresh the
    # old collections after moving their rows before deleting the now-redundant target.
    db.flush()
    db.expire(source_target, ["sources", "checks"])
    db.delete(source_target)
    summary["collection_targets_merged"] = 1
    return summary


def merge_company(
    db: Session, *, source_company_id: int, target_company_id: int, request_id: str, client_name: str
) -> tuple[Company, dict[str, int], bool]:
    """Physically merge a confirmed duplicate company into the canonical target.

    The operation is intentionally ID-based: name similarity is only a review aid and must never be
    sufficient to move public postings.  It is atomic, idempotent, and leaves audit history intact.
    """
    if source_company_id == target_company_id:
        raise _company_merge_error("source_company_id", source_company_id, "統合元と統合先には異なる企業IDを指定してください")

    operation = "company_merge"
    request_hash = _request_hash(
        operation, {"source_company_id": source_company_id, "target_company_id": target_company_id}
    )
    replayed = _replayed_company(db, request_id=request_id, operation=operation, request_hash=request_hash)
    if replayed is not None:
        audit = db.scalar(
            select(AuditLog)
            .where(AuditLog.action == operation, AuditLog.request_id == request_id)
            .order_by(AuditLog.id.desc())
        )
        migration = (audit.changes or {}).get("after", {}).get("migration", {}) if audit else {}
        return replayed, migration, True

    # Lock in a stable order to avoid two opposing merges deadlocking on PostgreSQL.
    companies = {
        item.id: item
        for item in db.scalars(
            select(Company)
            .where(Company.id.in_([source_company_id, target_company_id]))
            .order_by(Company.id)
            .with_for_update()
        )
    }
    source = companies.get(source_company_id)
    target = companies.get(target_company_id)
    if source is None:
        raise LookupError("source_company_not_found")
    if target is None:
        raise LookupError("target_company_not_found")

    # Reject a third-party identity collision before changing anything.  Collisions with the target
    # are harmless duplicates and are folded into its existing alias.
    source_aliases = list(
        db.scalars(select(CompanyAlias).where(CompanyAlias.company_id == source.id).with_for_update())
    )
    target_aliases = list(
        db.scalars(select(CompanyAlias).where(CompanyAlias.company_id == target.id).with_for_update())
    )
    # The source's canonical name and one of its own aliases can normalize to the same value
    # ("ユニ・チャーム株式会社" and "ユニチャーム" both become "ユニチャーム").  Kept as two entries, the
    # alias loop below re-parents that single alias row on the first pass and then deletes the row it
    # just moved on the second, losing the old name for resolution.  Deduplicate by normalized value,
    # keeping the canonical spelling, which is the one worth preserving as the alias text.
    seen_normalized: set[str] = set()
    source_names: list[tuple[str, str]] = []
    for name, normalized in [(source.name, source.normalized_name)] + [
        (alias.alias, alias.normalized_alias) for alias in source_aliases
    ]:
        if normalized in seen_normalized:
            continue
        seen_normalized.add(normalized)
        source_names.append((name, normalized))
    target_alias_by_normalized = {alias.normalized_alias: alias for alias in target_aliases}
    for _name, normalized in source_names:
        canonical = db.scalar(select(Company).where(Company.normalized_name == normalized))
        if canonical is not None and canonical.id not in {source.id, target.id}:
            raise _company_merge_error("source_company_id", source.id, f"別の企業「{canonical.name}」の正式名と競合します")
        alias = db.scalar(select(CompanyAlias).where(CompanyAlias.normalized_alias == normalized))
        if alias is not None and alias.company_id not in {source.id, target.id}:
            raise _company_merge_error("source_company_id", source.id, f"別の企業「{alias.company.name}」の別名と競合します")

    before = {"source_company": company_identity_dict(source), "target_company": company_identity_dict(target)}
    summary = {
        "opportunities_moved": 0,
        "aliases_moved": 0,
        "aliases_deduplicated": 0,
        "industries_moved": 0,
        "industries_deduplicated": 0,
        "company_request_records_moved": 0,
    }

    # The old canonical name becomes an alias, retaining resolution of old company names.  Source
    # aliases that already exist on the target or equal its canonical name are redundant.
    source_alias_by_normalized = {alias.normalized_alias: alias for alias in source_aliases}
    for alias_name, normalized in source_names:
        if normalized == target.normalized_name or normalized in target_alias_by_normalized:
            source_alias = source_alias_by_normalized.get(normalized)
            if source_alias is not None:
                db.delete(source_alias)
                summary["aliases_deduplicated"] += 1
            continue
        source_alias = source_alias_by_normalized.get(normalized)
        if source_alias is not None:
            source_alias.company_id = target.id
        else:
            db.add(CompanyAlias(company_id=target.id, alias=alias_name, normalized_alias=normalized))
        target_alias_by_normalized[normalized] = source_alias  # Marks later duplicate source data as handled.
        summary["aliases_moved"] += 1

    target_industries = {
        row.industry_id: row
        for row in db.scalars(select(CompanyIndustry).where(CompanyIndustry.company_id == target.id).with_for_update())
    }
    target_has_primary = any(row.is_primary for row in target_industries.values())
    source_industries = list(
        db.scalars(select(CompanyIndustry).where(CompanyIndustry.company_id == source.id).with_for_update())
    )
    for row in source_industries:
        existing = target_industries.get(row.industry_id)
        if existing is None:
            if row.is_primary and target_has_primary:
                row.is_primary = False
            elif row.is_primary:
                target_has_primary = True
            row.company_id = target.id
            summary["industries_moved"] += 1
            continue
        if existing.sector_id is None and row.sector_id is not None:
            existing.sector_id = row.sector_id
        if row.is_primary and not target_has_primary:
            row.is_primary = False
            existing.is_primary = True
            target_has_primary = True
        elif row.is_primary:
            row.is_primary = False
        db.delete(row)
        summary["industries_deduplicated"] += 1

    opportunities = list(
        db.scalars(select(Opportunity).where(Opportunity.company_id == source.id).with_for_update())
    )
    for item in opportunities:
        item.company_id = target.id
    summary["opportunities_moved"] = len(opportunities)

    request_records = list(
        db.scalars(select(CompanyRequestRecord).where(CompanyRequestRecord.company_id == source.id).with_for_update())
    )
    for item in request_records:
        item.company_id = target.id
    summary["company_request_records_moved"] = len(request_records)

    # The surviving company's own profile wins; only fields it never had are inherited, so a merge
    # never silently replaces text the operator confirmed for the target.
    for field in COMPANY_PROFILE_FIELDS:
        if getattr(target, field) is None and getattr(source, field) is not None:
            setattr(target, field, getattr(source, field))

    summary.update(_merge_collection_targets(db, source_company_id=source.id, target_company_id=target.id))
    # ``Company.aliases`` and ``Company.industries`` are delete-orphan relationships.  Flush and
    # expire the old collections after their children have been reassigned so deleting source does
    # not treat an already-moved child as an orphan from its stale in-memory collection.
    db.flush()
    db.expire(source, ["aliases", "industries"])
    _remember_request(
        db,
        request_id=request_id,
        operation=operation,
        request_hash=request_hash,
        company_id=target.id,
    )
    db.delete(source)
    db.flush()
    db.expire(target, ["aliases", "industries"])
    db.add(
        AuditLog(
            action=operation,
            entity_type="company",
            entity_id=str(target.id),
            request_id=request_id,
            client_name=client_name,
            source_url=None,
            success=True,
            changes={
                "before": jsonable_encoder(before),
                "after": jsonable_encoder({"company": company_identity_dict(target), "migration": summary}),
            },
        )
    )
    db.commit()
    return target, summary, False


def company_name_filter(company_name: str) -> ColumnElement[bool]:
    """Match Company rows whose normalized name or any alias equals the given name."""
    normalized = normalize_company_name(company_name)
    return or_(
        Company.normalized_name == normalized,
        Company.id.in_(select(CompanyAlias.company_id).where(CompanyAlias.normalized_alias == normalized)),
    )


def company_keyword_filter(db: Session, query: str) -> ColumnElement[bool]:
    """Match Company rows by substring and, on PostgreSQL, typo-tolerant trigram similarity."""
    term = _like_contains(query)
    normalized_query = normalize_company_name(query)
    normalized_term = _like_contains(normalized_query)
    matches: list[ColumnElement[bool]] = [
        Company.name.ilike(term, escape=LIKE_ESCAPE_CHARACTER),
        Company.normalized_name.ilike(normalized_term, escape=LIKE_ESCAPE_CHARACTER),
        Company.aliases.any(CompanyAlias.alias.ilike(term, escape=LIKE_ESCAPE_CHARACTER)),
        Company.aliases.any(CompanyAlias.normalized_alias.ilike(normalized_term, escape=LIKE_ESCAPE_CHARACTER)),
    ]
    if db.get_bind().dialect.name == "postgresql" and len(normalized_query) >= 3:
        matches.extend(
            [
                Company.name.op("%")(literal(query)),
                Company.normalized_name.op("%")(literal(normalized_query)),
                Company.aliases.any(CompanyAlias.alias.op("%")(literal(query))),
                Company.aliases.any(CompanyAlias.normalized_alias.op("%")(literal(normalized_query))),
            ]
        )
    return or_(*matches)


def company_profile_missing_fields(company: Company) -> list[Literal["business_summary", "description"]]:
    """Return required public-page profile text fields that are empty or whitespace-only."""
    return [
        field
        for field in ("business_summary", "description")
        if not (getattr(company, field) or "").strip(PROFILE_TEXT_WHITESPACE)
    ]


def _company_profile_has_gaps(db: Session) -> ColumnElement[bool]:
    """Match companies missing either profile text field used by company pages."""
    # SQLite's trim(X, Y) and PostgreSQL's btrim(X, Y) both strip the listed edge characters.
    # The default SQL trim only strips ASCII spaces, which would disagree with Python's whitespace
    # check for tab/newline-only legacy values.
    trim = func.btrim if db.get_bind().dialect.name == "postgresql" else func.trim
    return or_(
        Company.business_summary.is_(None),
        func.length(trim(Company.business_summary, PROFILE_TEXT_WHITESPACE)) == 0,
        Company.description.is_(None),
        func.length(trim(Company.description, PROFILE_TEXT_WHITESPACE)) == 0,
    )


def list_companies_missing_profile(
    db: Session,
    *,
    query: str | None = None,
    industry: str | None = None,
    page: int = 1,
    per_page: int = 20,
) -> CompanyProfileGapList:
    """List every company missing a summary or description, regardless of collection target."""
    filters: list[ColumnElement[bool]] = [_company_profile_has_gaps(db)]
    if query:
        filters.append(company_keyword_filter(db, query.strip()))
    if industry:
        industry_ids = select(Industry.id).where(or_(Industry.name == industry, Industry.slug == industry))
        filters.append(
            select(CompanyIndustry.id)
            .where(
                CompanyIndustry.company_id == Company.id,
                CompanyIndustry.industry_id.in_(industry_ids),
            )
            .correlate(Company)
            .exists()
        )

    count_stmt = select(func.count(Company.id)).where(*filters)
    stmt = (
        company_profile_query()
        .options(selectinload(Company.aliases))
        .where(*filters)
        .order_by(Company.name)
        .offset((page - 1) * per_page)
        .limit(per_page)
    )
    items = list(db.scalars(stmt).unique())
    return CompanyProfileGapList(
        items=items,
        total=int(db.scalar(count_stmt) or 0),
        page=page,
        per_page=per_page,
    )


def list_company_profile_history(
    db: Session, *, company_id: int, page: int = 1, per_page: int = 20
) -> CompanyProfileHistoryPage:
    if db.get(Company, company_id) is None:
        raise LookupError("company_not_found")

    filters = (
        AuditLog.entity_type == "company",
        AuditLog.entity_id == str(company_id),
        AuditLog.action == "company_profile_update",
        AuditLog.success.is_(True),
    )
    count_stmt = select(func.count(AuditLog.id)).where(*filters)
    stmt = (
        select(AuditLog)
        .where(*filters)
        .order_by(AuditLog.created_at.desc(), AuditLog.id.desc())
        .offset((page - 1) * per_page)
        .limit(per_page)
    )
    return CompanyProfileHistoryPage(
        items=list(db.scalars(stmt)),
        total=int(db.scalar(count_stmt) or 0),
        page=page,
        per_page=per_page,
    )
