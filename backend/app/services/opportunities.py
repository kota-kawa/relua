import base64
import binascii
import hashlib
import json
import math
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from typing import Any

from fastapi.encoders import jsonable_encoder
from sqlalchemy import Integer, Select, and_, case, cast, func, literal, or_, select
from sqlalchemy.orm import Session, selectinload
from sqlalchemy.sql.elements import ColumnElement

from app.dates import today_in_tokyo
from app.models import (
    PUBLIC_CODE_LENGTH,
    AuditLog,
    CollectionCheck,
    CollectionTarget,
    Company,
    CompanyAlias,
    Degree,
    EventFormat,
    EventType,
    GraduationYear,
    IdempotencyRecord,
    Industry,
    JobCategory,
    Opportunity,
    RecruitmentStatus,
    Sector,
    Tag,
    opportunity_jobs,
    public_code_string,
)
from app.schemas import OpportunityInput
from app.services.companies import company_name_filter, find_company, get_or_create_company
from app.services.company_industries import ensure_company_industry
from app.services.errors import FIELD_LABELS, master_error
from app.services.masters import choices, resolve_many, resolve_one, resolve_sector, sectors_for_industry
from app.services.normalization import (
    normalize_common,
    normalize_company_name,
    normalize_source_url,
    normalize_tag,
    source_url_is_allowed,
)
from app.services.serialization import detail_url, opportunity_dict, public_detail_url


class DomainValidationError(Exception):
    def __init__(self, errors: list[dict[str, Any]]):
        self.errors = errors
        super().__init__("validation_failed")


class InvalidSearchCursor(ValueError):
    """The opaque search cursor is malformed or belongs to different filters."""


@dataclass
class SearchResult:
    items: list[Opportunity]
    total: int
    page: int
    per_page: int
    next_cursor: str | None = None

    @property
    def total_pages(self) -> int:
        return max(1, math.ceil(self.total / self.per_page))


@dataclass(frozen=True)
class OpportunityReview:
    """A live posting that needs operator confirmation, with machine-detected reasons."""

    opportunity: Opportunity
    reasons: list[str]


# These are the only recruitment states that should receive routine source checks.  Keeping this as
# an allowlist also makes newly added terminal states opt out of maintenance queues by default.
RECONFIRMABLE_RECRUITMENT_STATUSES = ("募集予定", "募集中", "通年募集")


def _search_signature(
    *,
    q: str | None,
    status: list[str] | None,
    industry: list[str] | None,
    sector: list[str] | None,
    event_type: list[str] | None,
    event_format: list[str] | None,
    job_category: list[str] | None,
    graduation_year: list[str] | None,
    degree: list[str] | None,
    deadline_on_or_after: date | None,
    sort: str,
) -> str:
    filters = {
        "q": q.strip() if q else None,
        "status": sorted(status or []),
        "industry": sorted(industry or []),
        "sector": sorted(sector or []),
        "event_type": sorted(event_type or []),
        "event_format": sorted(event_format or []),
        "job_category": sorted(job_category or []),
        "graduation_year": sorted(graduation_year or []),
        "degree": sorted(degree or []),
        "deadline_on_or_after": deadline_on_or_after.isoformat() if deadline_on_or_after else None,
        "sort": sort,
    }
    encoded = json.dumps(filters, ensure_ascii=False, separators=(",", ":"), sort_keys=True)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _encode_search_cursor(
    item: Opportunity,
    *,
    sort: str,
    signature: str,
    snapshot_at: datetime,
    relevance_score: int | None = None,
) -> str:
    sort_value = relevance_score if sort == "relevance" else getattr(
        item, "deadline" if sort == "deadline" else f"{sort}_at"
    )
    payload = {
        "v": 1,
        "sort": sort,
        "signature": signature,
        "snapshot_at": snapshot_at.isoformat(),
        "value": sort_value.isoformat() if isinstance(sort_value, (date, datetime)) else sort_value,
        "id": item.id,
    }
    raw = json.dumps(payload, separators=(",", ":"), sort_keys=True).encode("utf-8")
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def _decode_search_cursor(
    cursor: str, *, sort: str, signature: str
) -> tuple[datetime, date | datetime | int | None, str]:
    try:
        padding = "=" * (-len(cursor) % 4)
        raw = base64.b64decode(cursor + padding, altchars=b"-_", validate=True)
        payload = json.loads(raw)
        if (
            not isinstance(payload, dict)
            or payload.get("v") != 1
            or payload.get("sort") != sort
            or payload.get("signature") != signature
            or not isinstance(payload.get("id"), str)
        ):
            raise ValueError
        snapshot_at = datetime.fromisoformat(payload["snapshot_at"])
        if snapshot_at.tzinfo is None:
            raise ValueError
        raw_value = payload.get("value")
        if sort == "relevance":
            if isinstance(raw_value, bool) or not isinstance(raw_value, int):
                raise ValueError
            value = raw_value
        elif sort == "deadline":
            value = date.fromisoformat(raw_value) if raw_value is not None else None
        else:
            if not isinstance(raw_value, str):
                raise ValueError
            value = datetime.fromisoformat(raw_value)
    except (binascii.Error, json.JSONDecodeError, TypeError, ValueError, KeyError) as exc:
        raise InvalidSearchCursor(
            "検索カーソルが無効です。最初のページからやり直し、同じ検索条件で返されたnext_cursorをそのまま渡してください。"
        ) from exc
    return snapshot_at, value, payload["id"]


def _search_relevance_score(db: Session, query: str) -> ColumnElement[int]:
    """Return a deterministic weighted score suitable for ordering and cursors.

    PostgreSQL uses pg_trgm's word similarity so a short query is measured against the most
    relevant part of a long description. SQLite keeps an exact-substring approximation for local
    development and the unit test suite; PostgreSQL integration tests cover the production path.
    """
    term = f"%{query}%"
    # normalize_company_name strips nakaguro ("・"), legal suffixes, and casing, so it lines up a
    # query like "ディーエヌエー" with a stored name like "株式会社ディー・エヌ・エー" that the raw
    # ilike/trigram comparisons below cannot: those compare literal text, not normalized text.
    normalized_query = normalize_company_name(query)
    normalized_term = f"%{normalized_query}%"
    is_postgresql = db.get_bind().dialect.name == "postgresql"

    def field_score(
        column: ColumnElement[str], weight: int, *, text: str = query, pattern: str = term
    ) -> ColumnElement[int]:
        similarity = (
            func.word_similarity(text.casefold(), func.lower(func.coalesce(column, "")))
            if is_postgresql
            else case((column.ilike(pattern), 1.0), else_=0.0)
        )
        contains_bonus = case((column.ilike(pattern), float(weight)), else_=0.0)
        return cast((similarity * weight + contains_bonus) * 1000, Integer)

    job_score = (
        select(func.coalesce(func.max(field_score(JobCategory.name, 2)), 0))
        .select_from(
            opportunity_jobs.join(JobCategory, opportunity_jobs.c.job_category_id == JobCategory.id)
        )
        .where(opportunity_jobs.c.opportunity_id == Opportunity.id)
        .correlate(Opportunity)
        .scalar_subquery()
    )
    # A company can have several aliases (e.g. "DeNA" and "ディーエヌエー" for the same row), so the
    # best-matching one - not an arbitrary one - contributes to the score, same as job categories above.
    alias_score = (
        select(
            func.coalesce(
                func.max(
                    field_score(CompanyAlias.alias, 4)
                    + field_score(
                        CompanyAlias.normalized_alias, 4, text=normalized_query, pattern=normalized_term
                    )
                ),
                0,
            )
        )
        .where(CompanyAlias.company_id == Company.id)
        .correlate(Company)
        .scalar_subquery()
    )
    return cast(
        field_score(Company.name, 4)
        + field_score(Company.normalized_name, 4, text=normalized_query, pattern=normalized_term)
        + alias_score
        + field_score(Opportunity.event_name, 3)
        + job_score
        + field_score(Opportunity.description, 1)
        + field_score(Opportunity.requirements, 1) / 2,
        Integer,
    )


def _keyword_filter(db: Session, query: str) -> ColumnElement[bool]:
    term = f"%{query}%"
    normalized_query = normalize_company_name(query)
    normalized_term = f"%{normalized_query}%"
    matches: list[ColumnElement[bool]] = [
        Company.name.ilike(term),
        Company.normalized_name.ilike(normalized_term),
        Company.aliases.any(CompanyAlias.alias.ilike(term)),
        Company.aliases.any(CompanyAlias.normalized_alias.ilike(normalized_term)),
        Opportunity.event_name.ilike(term),
        Opportunity.description.ilike(term),
        Opportunity.requirements.ilike(term),
        Opportunity.job_categories.any(JobCategory.name.ilike(term)),
    ]
    if db.get_bind().dialect.name == "postgresql" and len(query) >= 3:
        # Similarity operators use pg_trgm indexes and recover common misspellings in concise,
        # high-signal fields. Long free text remains substring matched to avoid noisy recall.
        # This still cannot bridge a script change (DeNA vs. ディーエヌエー) - only the registered
        # aliases above cover that.
        matches.extend(
            [
                Company.name.op("%")(literal(query)),
                Company.normalized_name.op("%")(literal(normalized_query)),
                Company.aliases.any(CompanyAlias.alias.op("%")(literal(query))),
                Company.aliases.any(CompanyAlias.normalized_alias.op("%")(literal(normalized_query))),
                Opportunity.event_name.op("%")(literal(query)),
                Opportunity.job_categories.any(JobCategory.name.op("%")(literal(query))),
            ]
        )
    return or_(*matches)


def opportunity_query(*, include_deleted: bool = False) -> Select[tuple[Opportunity]]:
    stmt = select(Opportunity).options(
        selectinload(Opportunity.status),
        selectinload(Opportunity.company),
        selectinload(Opportunity.industry),
        selectinload(Opportunity.sector),
        selectinload(Opportunity.event_type),
        selectinload(Opportunity.event_format),
        selectinload(Opportunity.job_categories),
        selectinload(Opportunity.graduation_years),
        selectinload(Opportunity.degrees),
        selectinload(Opportunity.tags),
    )
    return stmt if include_deleted else stmt.where(Opportunity.deleted_at.is_(None))


def get_opportunity(db: Session, opportunity_id: str) -> Opportunity | None:
    return db.scalar(opportunity_query().where(Opportunity.id == opportunity_id))


def get_opportunity_including_deleted(db: Session, opportunity_id: str) -> Opportunity | None:
    return db.scalar(opportunity_query(include_deleted=True).where(Opportunity.id == opportunity_id))


def get_opportunity_for_update(
    db: Session, opportunity_id: str, *, include_deleted: bool = False
) -> Opportunity | None:
    return db.scalar(
        opportunity_query(include_deleted=include_deleted)
        .where(Opportunity.id == opportunity_id)
        .with_for_update()
    )


def get_opportunity_by_public_ref(db: Session, reference: str) -> Opportunity | None:
    """Resolve either the UUID or the short public code.

    Read paths accept both so that links minted before public codes existed keep working.
    Write paths stay UUID-only via get_opportunity, keeping the idempotency target unambiguous.
    """
    if len(reference) == PUBLIC_CODE_LENGTH:
        return db.scalar(opportunity_query().where(Opportunity.public_code == reference.upper()))
    return get_opportunity(db, reference)


def _unique_public_code(db: Session) -> str:
    for _ in range(10):
        code = public_code_string()
        if db.scalar(select(Opportunity.id).where(Opportunity.public_code == code)) is None:
            return code
    raise RuntimeError("公開コードを生成できませんでした")


def search_opportunities(
    db: Session,
    *,
    q: str | None = None,
    status: list[str] | None = None,
    industry: list[str] | None = None,
    sector: list[str] | None = None,
    event_type: list[str] | None = None,
    event_format: list[str] | None = None,
    job_category: list[str] | None = None,
    graduation_year: list[str] | None = None,
    degree: list[str] | None = None,
    deadline_on_or_after: date | None = None,
    sort: str | None = None,
    page: int | None = 1,
    per_page: int = 20,
    cursor: str | None = None,
) -> SearchResult:
    normalized_q = q.strip() if q and q.strip() else None
    effective_sort = sort or ("relevance" if normalized_q else "deadline")
    if effective_sort == "relevance" and normalized_q is None:
        effective_sort = "deadline"
    cursor_mode = page is None or cursor is not None
    signature = _search_signature(
        q=normalized_q,
        status=status,
        industry=industry,
        sector=sector,
        event_type=event_type,
        event_format=event_format,
        job_category=job_category,
        graduation_year=graduation_year,
        degree=degree,
        deadline_on_or_after=deadline_on_or_after,
        sort=effective_sort,
    )
    snapshot_at = datetime.now(timezone.utc)  # noqa: UP017 -- tests also support Python 3.10
    cursor_value: date | datetime | int | None = None
    cursor_id: str | None = None
    if cursor_mode and cursor:
        snapshot_at, cursor_value, cursor_id = _decode_search_cursor(
            cursor, sort=effective_sort, signature=signature
        )

    stmt = opportunity_query().join(Opportunity.company)
    count_stmt = (
        select(func.count(func.distinct(Opportunity.id)))
        .select_from(Opportunity)
        .join(Opportunity.company)
        .where(Opportunity.deleted_at.is_(None))
    )

    filters = []
    relevance_score = _search_relevance_score(db, normalized_q) if normalized_q else None
    if normalized_q:
        filters.append(_keyword_filter(db, normalized_q))
    mappings = [
        (status, Opportunity.status_id, RecruitmentStatus),
        (event_type, Opportunity.event_type_id, EventType),
        (event_format, Opportunity.event_format_id, EventFormat),
    ]
    for values, column, model in mappings:
        if values:
            ids = select(model.id).where(or_(model.slug.in_(values), model.name.in_(values)))
            filters.append(column.in_(ids))
    if industry and sector:
        industry_ids = select(Industry.id).where(or_(Industry.slug.in_(industry), Industry.name.in_(industry)))
        chosen_sectors = select(Sector.id).where(
            or_(Sector.slug.in_(sector), Sector.name.in_(sector)),
            Sector.industry_id.in_(industry_ids),
        )
        refined_industries = select(Sector.industry_id).where(
            or_(Sector.slug.in_(sector), Sector.name.in_(sector)),
            Sector.industry_id.in_(industry_ids),
        )
        filters.append(
            or_(
                Opportunity.sector_id.in_(chosen_sectors),
                and_(
                    Opportunity.industry_id.in_(industry_ids),
                    Opportunity.industry_id.not_in(refined_industries),
                ),
            )
        )
    elif industry:
        industry_ids = select(Industry.id).where(or_(Industry.slug.in_(industry), Industry.name.in_(industry)))
        filters.append(Opportunity.industry_id.in_(industry_ids))
    elif sector:
        sector_ids = select(Sector.id).where(or_(Sector.slug.in_(sector), Sector.name.in_(sector)))
        filters.append(Opportunity.sector_id.in_(sector_ids))
    if job_category:
        filters.append(Opportunity.job_categories.any(or_(JobCategory.slug.in_(job_category), JobCategory.name.in_(job_category))))
    if graduation_year:
        filters.append(
            Opportunity.graduation_years.any(
                or_(GraduationYear.slug.in_(graduation_year), GraduationYear.name.in_(graduation_year))
            )
        )
    if degree:
        filters.append(Opportunity.degrees.any(or_(Degree.slug.in_(degree), Degree.name.in_(degree))))
    if deadline_on_or_after:
        filters.append(
            or_(
                Opportunity.deadline.is_(None),
                Opportunity.deadline >= deadline_on_or_after,
            )
        )
    if filters:
        stmt = stmt.where(*filters)
        count_stmt = count_stmt.where(*filters)

    if cursor_mode:
        # Keep a multi-call scan bounded to records that had not changed when it began. Combined
        # with keyset pagination below, deleting already-returned rows cannot move the next boundary.
        snapshot_filters = (
            Opportunity.created_at <= snapshot_at,
            Opportunity.updated_at <= snapshot_at,
        )
        stmt = stmt.where(*snapshot_filters)
        count_stmt = count_stmt.where(*snapshot_filters)

    if effective_sort == "relevance":
        assert relevance_score is not None
        stmt = stmt.order_by(relevance_score.desc(), Opportunity.id)
        if cursor_id is not None:
            assert isinstance(cursor_value, int)
            stmt = stmt.where(
                or_(
                    relevance_score < cursor_value,
                    and_(relevance_score == cursor_value, Opportunity.id > cursor_id),
                )
            )
    elif effective_sort == "updated":
        stmt = stmt.order_by(Opportunity.updated_at.desc(), Opportunity.id)
        if cursor_id is not None:
            assert isinstance(cursor_value, datetime)
            stmt = stmt.where(
                or_(
                    Opportunity.updated_at < cursor_value,
                    and_(Opportunity.updated_at == cursor_value, Opportunity.id > cursor_id),
                )
            )
    elif effective_sort == "created":
        stmt = stmt.order_by(Opportunity.created_at.desc(), Opportunity.id)
        if cursor_id is not None:
            assert isinstance(cursor_value, datetime)
            stmt = stmt.where(
                or_(
                    Opportunity.created_at < cursor_value,
                    and_(Opportunity.created_at == cursor_value, Opportunity.id > cursor_id),
                )
            )
    else:
        stmt = stmt.order_by(Opportunity.deadline.is_(None), Opportunity.deadline.asc(), Opportunity.id)
        if cursor_id is not None:
            if cursor_value is None:
                stmt = stmt.where(Opportunity.deadline.is_(None), Opportunity.id > cursor_id)
            else:
                assert isinstance(cursor_value, date)
                stmt = stmt.where(
                    or_(
                        Opportunity.deadline.is_(None),
                        Opportunity.deadline > cursor_value,
                        and_(Opportunity.deadline == cursor_value, Opportunity.id > cursor_id),
                    )
                )

    if not cursor_mode:
        assert page is not None
        stmt = stmt.offset((page - 1) * per_page).limit(per_page)
        items = list(db.scalars(stmt).unique())
        # A first-page miss proves that the complete filtered result is empty. Return immediately
        # instead of making PostgreSQL evaluate the same wide keyword/facet predicates again for
        # COUNT(*), which is particularly expensive when every search branch has to prove a miss.
        if page == 1 and not items:
            return SearchResult(items=[], total=0, page=page, per_page=per_page)
        total = int(db.scalar(count_stmt) or 0)
        return SearchResult(items=items, total=total, page=page, per_page=per_page)

    items = list(db.scalars(stmt.limit(per_page + 1)).unique())
    # The initial cursor request has no preceding rows, so an empty page also proves total=0. A
    # later cursor can legitimately be exhausted while the complete result remains non-empty and
    # must still run the count below to preserve the response contract.
    if cursor is None and not items:
        return SearchResult(items=[], total=0, page=1, per_page=per_page)
    has_more = len(items) > per_page
    items = items[:per_page]
    last_relevance_score = None
    if has_more and items and relevance_score is not None:
        last_relevance_score = int(
            db.scalar(
                select(relevance_score)
                .select_from(Opportunity)
                .join(Opportunity.company)
                .where(Opportunity.id == items[-1].id)
            )
            or 0
        )
    next_cursor = None
    if has_more and items:
        next_cursor = _encode_search_cursor(
            items[-1],
            sort=effective_sort,
            signature=signature,
            snapshot_at=snapshot_at,
            relevance_score=last_relevance_score,
        )
    total = int(db.scalar(count_stmt) or 0)
    return SearchResult(items=items, total=total, page=1, per_page=per_page, next_cursor=next_cursor)


def _company_opportunities(
    db: Session,
    company_name: str,
    exclude_id: str | None = None,
    *,
    recruitment_statuses: list[str] | None = None,
    deadline_on_or_after: date | None = None,
) -> list[Opportunity]:
    stmt = opportunity_query().join(Opportunity.company).where(company_name_filter(company_name))
    if exclude_id:
        stmt = stmt.where(Opportunity.id != exclude_id)
    if recruitment_statuses:
        status_ids = select(RecruitmentStatus.id).where(RecruitmentStatus.name.in_(recruitment_statuses))
        stmt = stmt.where(Opportunity.status_id.in_(status_ids))
    if deadline_on_or_after:
        stmt = stmt.where(or_(Opportunity.deadline.is_(None), Opportunity.deadline >= deadline_on_or_after))
    return list(db.scalars(stmt.order_by(Opportunity.updated_at.desc())).unique())


def find_similar_opportunities(
    db: Session,
    *,
    company_name: str,
    event_name: str | None = None,
    exclude_id: str | None = None,
    recruitment_statuses: list[str] | None = None,
    deadline_on_or_after: date | None = None,
    limit: int = 20,
) -> list[Opportunity]:
    """Entries of the same company, narrowed by a loose event-name match.

    Company names are compared after normalization, so "(株)X" and "株式会社X" collapse to one company.
    Event names match on containment in either direction, which catches "サマーインターン" against
    "サマーインターン2027" — near-misses a caller should look at before adding a second record.
    """
    items = _company_opportunities(
        db,
        company_name,
        exclude_id,
        recruitment_statuses=recruitment_statuses,
        deadline_on_or_after=deadline_on_or_after,
    )
    if event_name:
        target = normalize_common(event_name)
        items = [
            item
            for item in items
            if target in normalize_common(item.event_name) or normalize_common(item.event_name) in target
        ]
    return items[:limit]


def find_exact_duplicates(
    db: Session, *, company_name: str, event_name: str, exclude_id: str | None = None
) -> list[Opportunity]:
    """Same company and the same event name after normalization: a re-registration, not a new entry."""
    target = normalize_common(event_name)
    return [
        item for item in _company_opportunities(db, company_name, exclude_id) if normalize_common(item.event_name) == target
    ]


def _distinguishes_same_named_postings(
    existing: Opportunity,
    *,
    graduation_years: list[str],
    event_start_date: date | None,
    job_categories: list[str],
) -> bool:
    """True when the identity fields show two same-named postings are actually different postings.

    Companies routinely reuse one event name across cohorts, terms, or tracks - "新卒採用エントリー"
    for both 28卒 and 29卒, "サマーインターン" for both a June and an August term. Same company + same
    event name alone cannot tell those apart, so a match is only downgraded from exact to probable when
    a field that both sides actually specify disagrees. A field left unset on either side (e.g. no
    event_start_date yet) is not evidence of a difference, so it never downgrades a match on its own.
    """
    existing_grad = {item.name for item in existing.graduation_years}
    new_grad = set(graduation_years)
    if existing_grad and new_grad and existing_grad.isdisjoint(new_grad):
        return True
    if existing.event_start_date and event_start_date and existing.event_start_date != event_start_date:
        return True
    existing_jobs = {item.name for item in existing.job_categories}
    new_jobs = set(job_categories)
    if existing_jobs and new_jobs and existing_jobs.isdisjoint(new_jobs):
        return True
    return False


def classify_duplicate_candidates(
    db: Session,
    *,
    company_name: str,
    event_name: str,
    graduation_years: list[str],
    event_start_date: date | None,
    job_categories: list[str],
    exclude_id: str | None = None,
) -> tuple[list[Opportunity], list[Opportunity]]:
    """Split same-company/same-event-name candidates into exact and probable duplicates.

    A company+event_name match is downgraded from exact to probable when graduation_years,
    event_start_date, or job_categories clearly disagree with the incoming posting - see
    _distinguishes_same_named_postings. Only exact duplicates should block a write; probable
    duplicates are real candidates for the same identity check but not certain enough to refuse the
    write outright, so callers should surface them as a non-blocking warning instead.
    """
    candidates = find_exact_duplicates(db, company_name=company_name, event_name=event_name, exclude_id=exclude_id)
    exact: list[Opportunity] = []
    probable: list[Opportunity] = []
    for item in candidates:
        target = probable if _distinguishes_same_named_postings(
            item,
            graduation_years=graduation_years,
            event_start_date=event_start_date,
            job_categories=job_categories,
        ) else exact
        target.append(item)
    return exact, probable


def find_probable_duplicates(
    db: Session, *, data: OpportunityInput, exclude_id: str | None = None
) -> list[Opportunity]:
    """Same-company/same-event-name matches downgraded by classify_duplicate_candidates.

    Used post-write (exclude_id=the just-written row) to surface a non-blocking warning: the write
    already succeeded because these differed on graduation year, start date, or job category, but a
    caller should still double check it wasn't actually the same posting.
    """
    _, probable = classify_duplicate_candidates(
        db,
        company_name=data.company_name,
        event_name=data.event_name,
        graduation_years=data.graduation_years,
        event_start_date=data.event_start_date,
        job_categories=data.job_categories,
        exclude_id=exclude_id,
    )
    return probable


def find_source_url_duplicates(
    db: Session, *, source_url: str, exclude_id: str | None = None, limit: int = 20
) -> list[Opportunity]:
    normalized = normalize_source_url(source_url)
    stmt = opportunity_query().where(Opportunity.normalized_source_url == normalized)
    if exclude_id:
        stmt = stmt.where(Opportunity.id != exclude_id)
    return list(db.scalars(stmt.order_by(Opportunity.updated_at.desc()).limit(limit)).unique())


def list_stale_opportunities(
    db: Session,
    *,
    days: int = 7,
    deadline_on_or_after: date | None = None,
    limit: int = 50,
) -> list[Opportunity]:
    """Reconfirmable postings whose official source hasn't been checked in at least `days` days.

    Ordered so an operator works through the worst gaps first: never-checked rows (source_checked_at
    is null, e.g. records predating this column) before the oldest confirmed ones. Closed and other
    non-reconfirmable statuses are intentionally excluded from this routine-maintenance queue.
    """
    threshold = datetime.now(timezone.utc) - timedelta(days=days)  # noqa: UP017 -- tests also support Python 3.10
    stmt = (
        opportunity_query()
        .join(Opportunity.company)
        .join(Opportunity.status)
        .where(
            RecruitmentStatus.name.in_(RECONFIRMABLE_RECRUITMENT_STATUSES),
            or_(Opportunity.source_checked_at.is_(None), Opportunity.source_checked_at <= threshold),
        )
    )
    if deadline_on_or_after:
        stmt = stmt.where(or_(Opportunity.deadline.is_(None), Opportunity.deadline >= deadline_on_or_after))
    stmt = stmt.order_by(
        case((Opportunity.source_checked_at.is_(None), 0), else_=1),
        Opportunity.source_checked_at.asc(),
        Opportunity.id,
    ).limit(limit)
    return list(db.scalars(stmt).unique())


def list_opportunities_requiring_review(
    db: Session, *, days: int = 7, limit: int = 50
) -> list[OpportunityReview]:
    """Return reconfirmable postings and date/status contradictions in review priority order.

    The date checks are deliberately a live query rather than stored flags: an extended deadline
    disappears from the queue immediately after an operator updates it.  Contradictions are placed
    before ordinary stale-source work but never alter the published status themselves. Only
    募集予定, 募集中, and 通年募集 are routine-maintenance states; closed and other terminal states
    stay out of this queue.
    """
    now = datetime.now(timezone.utc)  # noqa: UP017 -- tests also support Python 3.10
    today = today_in_tokyo(now)
    threshold = now - timedelta(days=days)
    source_stale = or_(Opportunity.source_checked_at.is_(None), Opportunity.source_checked_at <= threshold)
    date_status_conflict = and_(
        RecruitmentStatus.name == "募集中",
        or_(Opportunity.deadline < today, Opportunity.event_end_date < today),
    )
    stmt = (
        opportunity_query()
        .join(Opportunity.company)
        .join(Opportunity.status)
        .where(
            RecruitmentStatus.name.in_(RECONFIRMABLE_RECRUITMENT_STATUSES),
            or_(date_status_conflict, source_stale),
        )
        .order_by(
            case((date_status_conflict, 0), else_=1),
            case((Opportunity.source_checked_at.is_(None), 0), else_=1),
            Opportunity.source_checked_at.asc(),
            Opportunity.id,
        )
        .limit(limit)
    )
    reviews = []
    for item in db.scalars(stmt).unique():
        reasons = []
        if item.status.name == "募集中" and item.deadline is not None and item.deadline < today:
            reasons.append("deadline_passed_while_open")
        if item.status.name == "募集中" and item.event_end_date is not None and item.event_end_date < today:
            reasons.append("event_ended_while_open")
        if item.source_checked_at is None or _as_utc(item.source_checked_at) <= threshold:
            reasons.append("source_not_checked_recently")
        reviews.append(OpportunityReview(opportunity=item, reasons=reasons))
    return reviews


def _reused_request_id_error(request_id: str) -> dict[str, Any]:
    return {
        "field": "request_id",
        "received": request_id,
        "reason": "同じrequest_idが異なる内容の操作です",
        "expected": "操作ごとに一意なrequest_id",
        "example": "client-20260726-0001",
        "alternative": "新しいrequest_idを発行してください",
    }


def _active_idempotency_target(db: Session, opportunity_id: str) -> Opportunity:
    item = get_opportunity_including_deleted(db, opportunity_id)
    if item is None:
        raise RuntimeError("idempotency target not found")
    if item.deleted_at is not None:
        raise DomainValidationError(
            [
                {
                    "field": "募集情報ID",
                    "received": opportunity_id,
                    "reason": "前回の操作対象は現在削除されています",
                    "expected": "公開中の募集情報ID",
                    "alternative": "restore_opportunityで復元してから、新しいrequest_idで操作してください",
                }
            ]
        )
    return item


def _duplicate_error(matches: list[Opportunity]) -> dict[str, Any]:
    return {
        "field": "イベント名",
        "received": matches[0].event_name,
        "reason": "同じ企業・同名イベントで、対象学年・実施日・対象職種も一致する登録が既にあります",
        "expected": "未登録のイベント名、または異なる対象学年・実施日・対象職種",
        "example": None,
        "alternative": (
            "既存の登録を直す場合はpatch_opportunityまたはupdate_opportunityを使い、"
            "全く同じ日程・コースを意図的に複数登録する場合はallow_duplicateをtrueにしてください"
        ),
        "existing": [
            {"id": item.id, "public_code": item.public_code, "url": detail_url(item), "event_name": item.event_name}
            for item in matches
        ],
    }


def probable_duplicate_warning(matches: list[Opportunity]) -> dict[str, Any]:
    """Non-blocking counterpart to _duplicate_error for a company+event_name match that

    classify_duplicate_candidates downgraded because graduation year, start date, or job category
    disagreed - most often the same event name reused across cohorts, terms, or tracks.
    """
    return {
        "field": "イベント名",
        "received": matches[0].event_name,
        "reason": "同じ企業・同名イベントの登録がありますが、対象学年・実施日・対象職種のいずれかが異なるため別募集として保存しました",
        "expected": "別の学年・日程・職種であることを確認してください",
        "example": None,
        "alternative": (
            "同一の募集を誤って分けてしまった場合は、既存側をupdate_opportunityまたはdelete_opportunityで整理してください"
        ),
        "existing": [
            {"id": item.id, "public_code": item.public_code, "url": detail_url(item), "event_name": item.event_name}
            for item in matches
        ],
    }


def source_duplicate_warning(matches: list[Opportunity], source_url: str) -> dict[str, Any]:
    return {
        "field": "情報源",
        "received": source_url,
        "reason": "同じ一次情報URLを使用する募集が既に登録されています",
        "expected": "別の募集であることを確認してください",
        "example": None,
        "alternative": "同じページに複数募集が掲載されている場合はそのまま登録できます",
        "existing": [
            {"id": item.id, "public_code": item.public_code, "url": detail_url(item), "event_name": item.event_name}
            for item in matches
        ],
    }


def opportunity_consistency_warnings(
    *,
    recruitment_status: str,
    deadline: date | None,
    event_start_date: date | None,
    event_end_date: date | None,
    today: date | None = None,
) -> list[dict[str, Any]]:
    """Return non-blocking date/status contradictions that still need an operator's judgement.

    A deadline extension, additional recruiting round, or cancelled event can all make these
    combinations legitimate. They therefore remain warnings instead of validation errors, while
    ensuring every write client sees the inconsistency before treating the update as routine.
    """
    today = today or today_in_tokyo()
    warnings = []
    if recruitment_status == "締切" and deadline is not None and deadline > today:
        warnings.append(
            {
                "field": "募集状況",
                "received": recruitment_status,
                "reason": "締め切りが未来ですが募集状況は「締切」です",
                "expected": f"締め切りが{today.isoformat()}以前、または募集状況が「募集中」",
                "alternative": "締切延長・追加募集なら、公式情報を確認して募集状況と締め切りを更新してください",
            }
        )
    if recruitment_status == "締切" and event_start_date is not None and event_start_date > today:
        warnings.append(
            {
                "field": "募集状況",
                "received": recruitment_status,
                "reason": "実施開始日が未来ですが募集状況は「締切」です",
                "expected": f"実施開始日が{today.isoformat()}以前、または募集状況が「募集中」",
                "alternative": "中止・募集取りやめの場合は公式情報で確認し、必要なら内容の補足を更新してください",
            }
        )
    if recruitment_status == "募集中" and deadline is not None and deadline < today:
        warnings.append(
            {
                "field": "募集状況",
                "received": recruitment_status,
                "reason": "締め切りが過去ですが募集状況は「募集中」です",
                "expected": f"締め切りが{today.isoformat()}以降、または募集状況が「締切」",
                "alternative": "締切延長・追加募集なら、公式情報を確認して新しい締め切りを登録してください",
            }
        )
    if recruitment_status == "募集中" and event_end_date is not None and event_end_date < today:
        warnings.append(
            {
                "field": "募集状況",
                "received": recruitment_status,
                "reason": "実施終了日が過去ですが募集状況は「募集中」です",
                "expected": f"実施終了日が{today.isoformat()}以降、または募集状況が「締切」",
                "alternative": "追加日程・別イベントでないか公式情報を確認してください",
            }
        )
    return warnings


def _resolve_relations(db: Session, data: OpportunityInput) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    errors: list[dict[str, Any]] = []
    resolved: dict[str, Any] = {}
    singles = [
        ("recruitment_status", RecruitmentStatus, data.recruitment_status),
        ("industry", Industry, data.industry),
        ("event_type", EventType, data.event_type),
        ("event_format", EventFormat, data.event_format),
    ]
    for field, model, value in singles:
        item = resolve_one(db, model, value)
        if item is None:
            errors.append(master_error(field, value, choices(db, model)))
        else:
            resolved[field] = item

    # Sector names repeat across industries (every industry seeds its own "その他"), so resolution
    # must be scoped to the already-resolved industry - see resolve_sector's docstring.
    industry = resolved.get("industry")
    sector = resolve_sector(db, industry_id=industry.id if industry else None, value=data.sector)
    if sector is None:
        available = sectors_for_industry(db, data.industry)[1] if industry is not None else None
        errors.append(
            master_error(
                "sector",
                data.sector,
                [item.name for item in available] if available is not None else choices(db, Sector),
            )
        )
    else:
        resolved["sector"] = sector

    multiples = [
        ("job_categories", JobCategory, data.job_categories),
        ("graduation_years", GraduationYear, data.graduation_years),
        ("degrees", Degree, data.degrees),
    ]
    for field, model, values in multiples:
        items, missing = resolve_many(db, model, values)
        if missing:
            errors.append(master_error(field, missing, choices(db, model)))
        else:
            resolved[field] = items

    return resolved, errors


def validate_write(db: Session, *, data: OpportunityInput) -> list[dict[str, Any]]:
    """Master-value checks with nothing written, backing the dry-run tool."""
    _, errors = _resolve_relations(db, data)
    return errors


def _tags(db: Session, names: list[str]) -> list[Tag]:
    result: list[Tag] = []
    for name in names:
        normalized = normalize_tag(name)
        tag = db.scalar(select(Tag).where(Tag.normalized_name == normalized))
        if tag is None:
            tag = Tag(name=name, normalized_name=normalized)
            db.add(tag)
            db.flush()
        result.append(tag)
    return result


def _hash_payload(payload: dict[str, Any]) -> str:
    return hashlib.sha256(json.dumps(payload, ensure_ascii=False, sort_keys=True, default=str).encode()).hexdigest()


def _request_hash(data: OpportunityInput, **context: Any) -> str:
    payload = data.model_dump(mode="json")
    payload.update({f"_{key}": value for key, value in context.items() if value is not None})
    return _hash_payload(payload)


def opportunity_input_dict(item: Opportunity) -> dict[str, Any]:
    """Return the exact write shape so a partial patch can merge without losing fields."""
    return {
        "recruitment_status": item.status.name,
        "company_name": item.company.name,
        "industry": item.industry.name,
        "sector": item.sector.name,
        "event_name": item.event_name,
        "deadline": item.deadline,
        "event_type": item.event_type.name,
        "description": item.description,
        "event_format": item.event_format.name,
        "location": item.location,
        "selection_process": item.selection_process,
        "homepage_url": item.homepage_url,
        "job_categories": [value.name for value in sorted(item.job_categories, key=lambda value: value.sort_order)],
        "tags": [value.name for value in sorted(item.tags, key=lambda value: value.name)],
        "event_start_date": item.event_start_date,
        "event_end_date": item.event_end_date,
        "period_note": item.period_note,
        "requirements": item.requirements,
        "compensation": item.compensation,
        "graduation_years": [
            value.name for value in sorted(item.graduation_years, key=lambda value: value.sort_order)
        ],
        "degrees": [value.name for value in sorted(item.degrees, key=lambda value: value.sort_order)],
        "audience_note": item.audience_note,
        "recruitment_start_date": item.recruitment_start_date,
        "entry_url": item.entry_url,
        "source_url": item.source_url,
    }


def opportunity_patch_changes(item: Opportunity, data: OpportunityInput) -> list[dict[str, Any]]:
    before = opportunity_input_dict(item)
    after = data.model_dump()
    return [
        {"field": field, "before": before[field], "after": after[field]}
        for field in before
        if before[field] != after[field]
    ]


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)  # noqa: UP017 -- tests also support Python 3.10
    return value.astimezone(timezone.utc)  # noqa: UP017 -- tests also support Python 3.10


def _next_version_timestamp(item: Opportunity) -> datetime:
    moment = datetime.now(timezone.utc)  # noqa: UP017 -- tests also support Python 3.10
    if item.updated_at is not None and moment <= _as_utc(item.updated_at):
        return _as_utc(item.updated_at) + timedelta(microseconds=1)
    return moment


def optimistic_lock_error(expected: datetime, actual: datetime) -> dict[str, Any]:
    return {
        "field": "更新前の最終確認日時",
        "received": expected.isoformat(),
        "reason": "取得後に募集情報が更新されています",
        "expected": actual.isoformat(),
        "example": actual.isoformat(),
        "alternative": "get_opportunityで最新値を取得し、変更内容を確認して新しいrequest_idで再試行してください",
    }


def ensure_expected_updated_at(item: Opportunity, expected: datetime) -> None:
    if _as_utc(item.updated_at) != _as_utc(expected):
        raise DomainValidationError([optimistic_lock_error(expected, item.updated_at)])


def is_patch_replay(db: Session, *, request_id: str, opportunity_id: str) -> bool:
    previous = db.scalar(select(IdempotencyRecord).where(IdempotencyRecord.request_id == request_id))
    return bool(
        previous
        and previous.operation == "patch"
        and previous.opportunity_id == opportunity_id
    )


def _auto_matched_collection_target(
    db: Session, *, data: OpportunityInput, request_id: str
) -> CollectionTarget | None:
    """Attribute a write to its collection target when the caller didn't pass collection_target_id.

    company_id is unique on collection_targets, so once the company already exists the match is
    exactly as unambiguous as an explicit collection_target_id would be - it is just recovered from
    data the write already carries instead of a lookup step a caller can forget. Without this, a
    queued company's last_checked_at stays null forever whenever a posting for it is registered by a
    route that never learned the target's id, even though the posting is real.
    """
    company = find_company(db, data.company_name)
    if company is None:
        return None
    target = db.scalar(
        select(CollectionTarget)
        .options(selectinload(CollectionTarget.company), selectinload(CollectionTarget.sources))
        .where(
            CollectionTarget.company_id == company.id,
            CollectionTarget.is_active.is_(True),
        )
        .with_for_update()
    )
    if target is None:
        return None
    existing_check = db.scalar(select(CollectionCheck).where(CollectionCheck.request_id == request_id))
    if existing_check is not None:
        # Only relevant if this request_id was already used for an unrelated collection check - too
        # narrow an edge case to fail an otherwise-valid write over, unlike the explicit-id path below.
        return None
    return target


def _collection_target_for_write(
    db: Session,
    *,
    collection_target_id: int | None,
    data: OpportunityInput,
    request_id: str,
) -> CollectionTarget | None:
    if collection_target_id is None:
        return _auto_matched_collection_target(db, data=data, request_id=request_id)
    target = db.scalar(
        select(CollectionTarget)
        .options(
            selectinload(CollectionTarget.company),
            selectinload(CollectionTarget.sources),
        )
        .where(CollectionTarget.id == collection_target_id)
        .with_for_update()
    )
    if target is None:
        raise DomainValidationError(
            [{"field": "情報収集対象ID", "received": collection_target_id, "reason": "収集対象が見つかりません"}]
        )
    if not target.is_active:
        raise DomainValidationError(
            [{"field": "情報収集対象ID", "received": collection_target_id, "reason": "収集対象が無効化されています"}]
        )
    matched_company = find_company(db, data.company_name)
    if matched_company is None or matched_company.id != target.company_id:
        raise DomainValidationError(
            [
                {
                    "field": "情報収集対象ID",
                    "received": collection_target_id,
                    "reason": f"収集対象の企業は「{target.company.name}」ですが、募集情報の企業名は「{data.company_name}」です",
                    "expected": target.company.name,
                    "alternative": (
                        "表記揺れが同じ企業を指している場合、現時点では別名（CompanyAlias）を登録するMCPツールが"
                        "ないため自動では吸収できません。正しいcollection_target_idを再確認するか、"
                        "collection_target_idを指定せずに登録してください"
                    ),
                }
            ]
        )
    # No industry check: a target covers a whole company, and a company legitimately posts under
    # several industries. The posting's own industry is recorded against the company instead, by
    # ensure_company_industry in write_opportunity.
    existing_check = db.scalar(select(CollectionCheck).where(CollectionCheck.request_id == request_id))
    if existing_check is not None:
        raise DomainValidationError([_reused_request_id_error(request_id)])
    return target


def _ensure_company_source_allowed(
    db: Session,
    *,
    company: Company,
    source_url: str,
    target: CollectionTarget | None = None,
) -> None:
    """Enforce a company's active collection sources as its official-source allowlist.

    Unmonitored companies have no curated trust anchor yet and retain the legacy denylist check.
    Once a collection target exists, however, an agent cannot silently introduce an unrelated host
    through an opportunity write.  Operators extend the allowlist explicitly with
    add_collection_source/update_collection_source, both of which are audited writes.
    """

    target = target or db.scalar(
        select(CollectionTarget)
        .options(selectinload(CollectionTarget.sources))
        .where(CollectionTarget.company_id == company.id)
    )
    if target is None:
        return
    allowed_urls = [source.url for source in target.sources if source.is_active]
    if allowed_urls and source_url_is_allowed(source_url, allowed_urls):
        return
    raise DomainValidationError(
        [
            {
                "field": FIELD_LABELS["source_url"],
                "received": source_url,
                "reason": "この企業の公式情報源allowlistに含まれないURLです",
                "expected": allowed_urls,
                "alternative": (
                    "企業自身の公式ページであることを確認し、先にadd_collection_sourceで"
                    "収集対象へ登録してください"
                ),
            }
        ]
    )


def _record_collection_success(
    db: Session,
    *,
    target: CollectionTarget,
    item: Opportunity,
    request_id: str,
    client_name: str,
) -> None:
    now = datetime.now(timezone.utc)  # noqa: UP017 -- tests also support Python 3.10
    target.last_checked_at = now
    target.last_found_at = now
    target.last_check_result = "found"
    target.next_check_at = now + timedelta(days=target.check_interval_days)
    for source in target.sources:
        if normalize_source_url(source.url) == item.normalized_source_url:
            source.last_checked_at = now
            break
    check = CollectionCheck(
        collection_target_id=target.id,
        result="found",
        checked_at=now,
        source_url=item.source_url,
        opportunity=item,
        request_id=request_id,
        client_name=client_name,
        note="募集情報の書き込みと同時に記録",
    )
    db.add(check)
    db.flush()
    db.add(
        AuditLog(
            action="collection_check_create",
            entity_type="collection_check",
            entity_id=str(check.id),
            request_id=request_id,
            client_name=client_name,
            source_url=item.source_url,
            success=True,
            changes={
                "before": None,
                "after": {
                    "collection_target_id": target.id,
                    "result": "found",
                    "opportunity_id": item.id,
                    "checked_at": now.isoformat(),
                },
            },
        )
    )


def write_opportunity(
    db: Session,
    *,
    data: OpportunityInput,
    request_id: str,
    client_name: str,
    opportunity_id: str | None = None,
    allow_duplicate: bool = False,
    collection_target_id: int | None = None,
    expected_updated_at: datetime | None = None,
    action: str | None = None,
) -> tuple[Opportunity, bool]:
    operation = action or ("update" if opportunity_id else "create")
    request_hash = _request_hash(
        data,
        collection_target_id=collection_target_id,
        expected_updated_at=expected_updated_at.isoformat() if expected_updated_at else None,
        action=action,
    )
    previous = db.scalar(select(IdempotencyRecord).where(IdempotencyRecord.request_id == request_id))
    if previous:
        target_mismatch = opportunity_id is not None and previous.opportunity_id != opportunity_id
        if previous.operation != operation or previous.request_hash != request_hash or target_mismatch:
            raise DomainValidationError([_reused_request_id_error(request_id)])
        return _active_idempotency_target(db, previous.opportunity_id), True

    # Resolved (and row-locked) before the duplicate check below, not after it, so two concurrent
    # writes for the same company serialize here instead of both passing find_exact_duplicates
    # before either commits - the same .with_for_update() idiom used on CollectionTarget further
    # down in this function. Other companies are unaffected: this is a row lock, not a table lock.
    company = get_or_create_company(db, data.company_name)
    db.scalar(select(Company.id).where(Company.id == company.id).with_for_update())

    if opportunity_id is None and not allow_duplicate:
        # Idempotency only catches a replay of the same request_id. A client that re-reads the same
        # source page next week sends a new request_id, so the same posting would land twice.
        # Only an exact match blocks the write: a company can legitimately reuse one event name across
        # graduation years, terms, or tracks (e.g. "新卒採用エントリー" for both 28卒 and 29卒), and a
        # hard block on event_name alone made an agent about to register a genuinely separate posting
        # believe it already existed. A probable match still gets created; it surfaces as a warning
        # below instead (see _write_warnings / find_probable_duplicates).
        exact_duplicates, _ = classify_duplicate_candidates(
            db,
            company_name=data.company_name,
            event_name=data.event_name,
            graduation_years=data.graduation_years,
            event_start_date=data.event_start_date,
            job_categories=data.job_categories,
        )
        if exact_duplicates:
            raise DomainValidationError([_duplicate_error(exact_duplicates)])

    resolved, errors = _resolve_relations(db, data)
    if errors:
        raise DomainValidationError(errors)

    if opportunity_id:
        item = get_opportunity_for_update(db, opportunity_id) if expected_updated_at else get_opportunity(db, opportunity_id)
        if item is None:
            raise LookupError("opportunity_not_found")
        if expected_updated_at:
            ensure_expected_updated_at(item, expected_updated_at)
        before = opportunity_dict(item)
        is_new = False
    else:
        item = Opportunity(public_code=_unique_public_code(db))
        before = None
        is_new = True

    # Linking a collection target - and the "found" freshness it stamps on the target and on
    # source_checked_at below - only belongs to a brand-new registration: that is the one case where
    # writing the row *is* confirming the primary source right now. An update or patch is a plain
    # content edit and must not silently claim a source check that didn't happen; write != verify. A
    # caller who did re-check the source records that separately via verify_opportunity or
    # record_collection_check.
    if collection_target_id is not None and not is_new:
        raise DomainValidationError(
            [
                {
                    "field": "情報収集対象ID",
                    "received": collection_target_id,
                    "reason": (
                        "更新では指定できません。公式情報を確認した場合はverify_opportunityまたは"
                        "record_collection_checkで別途記録してください"
                    ),
                }
            ]
        )
    collection_target = (
        _collection_target_for_write(
            db,
            collection_target_id=collection_target_id,
            data=data,
            request_id=request_id,
        )
        if is_new
        else None
    )

    previous_source = (
        item.normalized_source_url
        if is_new or item.normalized_source_url is not None
        else normalize_source_url(item.source_url)
    )
    source_changed = is_new or normalize_source_url(data.source_url) != previous_source
    if source_changed:
        _ensure_company_source_allowed(
            db,
            company=company,
            source_url=data.source_url,
            target=collection_target,
        )

    scalar_fields = [
        "event_name",
        "deadline",
        "description",
        "location",
        "selection_process",
        "homepage_url",
        "event_start_date",
        "event_end_date",
        "period_note",
        "requirements",
        "compensation",
        "audience_note",
        "recruitment_start_date",
        "entry_url",
        "source_url",
    ]
    for field in scalar_fields:
        setattr(item, field, getattr(data, field))
    item.normalized_source_url = normalize_source_url(data.source_url)
    item.status = resolved["recruitment_status"]
    item.company = company
    item.industry = resolved["industry"]
    item.sector = resolved["sector"]
    # The posting states which industry and sector this company operates in, so record it. This is
    # how classification stays complete without anyone maintaining it: a company registered only as
    # IT・通信 learns 医療・製薬 the first time it posts under it.
    ensure_company_industry(db, company=company, industry=resolved["industry"], sector=resolved["sector"])
    item.event_type = resolved["event_type"]
    item.event_format = resolved["event_format"]
    item.job_categories = resolved["job_categories"]
    item.graduation_years = resolved["graduation_years"]
    item.degrees = resolved["degrees"]
    item.tags = _tags(db, data.tags)
    # Every source-backed write advances the version used by optimistic locking. Python's
    # microsecond clock also keeps SQLite tests from collapsing two writes into one timestamp.
    item.updated_at = _next_version_timestamp(item)
    if is_new:
        # This write's data came from reading data.source_url just now, so it also counts as
        # confirming the official source - independently of updated_at, which exists for optimistic
        # locking. An update/patch does not get the same treatment: see the collection_target guard
        # above for why write and verification are kept separate past registration.
        item.source_checked_at = item.updated_at
        db.add(item)
    db.flush()
    if collection_target is not None:
        _record_collection_success(
            db,
            target=collection_target,
            item=item,
            request_id=request_id,
            client_name=client_name,
        )
    response = opportunity_dict(item)
    json_response = jsonable_encoder(response)

    db.add(
        AuditLog(
            action=operation,
            entity_type="opportunity",
            entity_id=item.id,
            request_id=request_id,
            client_name=client_name,
            source_url=data.source_url,
            success=True,
            changes={"before": jsonable_encoder(before), "after": json_response},
        )
    )
    db.add(
        IdempotencyRecord(
            request_id=request_id,
            operation=operation,
            request_hash=request_hash,
            opportunity_id=item.id,
            response_data=json_response,
        )
    )
    db.commit()
    return item, False


def update_recruitment_status(
    db: Session,
    *,
    opportunity_id: str,
    expected_updated_at: datetime,
    recruitment_status: str,
    request_id: str,
    client_name: str,
    deadline: date | None = None,
    clear_deadline: bool = False,
) -> tuple[Opportunity, bool]:
    """Change only the status, and optionally the deadline.

    Marking a posting 締切 is the most common maintenance edit. Requiring the full replacement payload
    for it makes an agent re-send 25 fields it did not verify, which is how stale values creep in.
    """
    payload = {
        "opportunity_id": opportunity_id,
        "expected_updated_at": _as_utc(expected_updated_at).isoformat(),
        "recruitment_status": recruitment_status,
        "deadline": deadline,
        "clear_deadline": clear_deadline,
    }
    request_hash = _hash_payload(payload)
    previous = db.scalar(select(IdempotencyRecord).where(IdempotencyRecord.request_id == request_id))
    if previous:
        if (
            previous.operation != "status_update"
            or previous.request_hash != request_hash
            or previous.opportunity_id != opportunity_id
        ):
            raise DomainValidationError([_reused_request_id_error(request_id)])
        return _active_idempotency_target(db, previous.opportunity_id), True

    item = get_opportunity_for_update(db, opportunity_id)
    if item is None:
        raise LookupError("opportunity_not_found")
    ensure_expected_updated_at(item, expected_updated_at)

    status = resolve_one(db, RecruitmentStatus, recruitment_status)
    if status is None:
        raise DomainValidationError([master_error("recruitment_status", recruitment_status, choices(db, RecruitmentStatus))])

    new_deadline = item.deadline
    if deadline is not None:
        new_deadline = deadline
    elif clear_deadline:
        new_deadline = None
    if new_deadline is not None:
        limit = date.today().replace(year=date.today().year + 5)
        if not date(2000, 1, 1) <= new_deadline <= limit:
            raise DomainValidationError(
                [
                    {
                        "field": FIELD_LABELS["deadline"],
                        "received": new_deadline,
                        "reason": "許容範囲外の日付です",
                        "expected": "YYYY-MM-DD形式（2000-01-01から実行日の5年後まで）",
                        "example": "2026-08-31",
                        "alternative": "不明な場合はclear_deadlineをtrueにしてください",
                    }
                ]
            )
        if item.recruitment_start_date and new_deadline < item.recruitment_start_date:
            raise DomainValidationError(
                [
                    {
                        "field": FIELD_LABELS["deadline"],
                        "received": new_deadline,
                        "reason": "締め切りは募集開始日以降にしてください",
                        "expected": f"{item.recruitment_start_date.isoformat()}以降の日付",
                        "example": item.recruitment_start_date.isoformat(),
                        "alternative": "募集開始日も直す場合はupdate_opportunityを使ってください",
                    }
                ]
            )

    before = opportunity_dict(item)
    item.status = status
    item.deadline = new_deadline
    item.updated_at = _next_version_timestamp(item)
    db.flush()
    json_response = jsonable_encoder(opportunity_dict(item))

    db.add(
        AuditLog(
            action="status_update",
            entity_type="opportunity",
            entity_id=item.id,
            request_id=request_id,
            client_name=client_name,
            source_url=item.source_url,
            success=True,
            changes={"before": jsonable_encoder(before), "after": json_response},
        )
    )
    db.add(
        IdempotencyRecord(
            request_id=request_id,
            operation="status_update",
            request_hash=request_hash,
            opportunity_id=item.id,
            response_data=json_response,
        )
    )
    db.commit()
    return item, False


def verify_opportunity(
    db: Session,
    *,
    opportunity_id: str,
    checked_at: datetime,
    source_url: str,
    request_id: str,
    client_name: str,
) -> tuple[Opportunity, bool]:
    """Record that an unchanged posting was checked on its official source.

    Unlike a content or status update, this deliberately leaves ``updated_at`` intact: callers can
    acknowledge a fresh source check without creating an optimistic-locking conflict for an editor.
    """
    checked_at = _as_utc(checked_at)
    payload = {
        "opportunity_id": opportunity_id,
        "checked_at": checked_at.isoformat(),
        "source_url": source_url,
    }
    request_hash = _hash_payload(payload)
    previous = db.scalar(select(IdempotencyRecord).where(IdempotencyRecord.request_id == request_id))
    if previous:
        if (
            previous.operation != "verify"
            or previous.request_hash != request_hash
            or previous.opportunity_id != opportunity_id
        ):
            raise DomainValidationError([_reused_request_id_error(request_id)])
        return _active_idempotency_target(db, previous.opportunity_id), True

    item = get_opportunity(db, opportunity_id)
    if item is None:
        raise LookupError("opportunity_not_found")

    if normalize_source_url(source_url) != item.normalized_source_url:
        raise DomainValidationError(
            [
                {
                    "field": FIELD_LABELS["source_url"],
                    "received": source_url,
                    "reason": "登録済みの一次情報URLと一致しません",
                    "expected": item.source_url,
                    "alternative": "情報源URL自体を変更する場合はpatch_opportunityを使ってください",
                }
            ]
        )
    now = datetime.now(timezone.utc)  # noqa: UP017 -- tests also support Python 3.10
    if checked_at > now:
        raise DomainValidationError(
            [
                {
                    "field": "確認日時",
                    "received": checked_at.isoformat(),
                    "reason": "未来の日時は指定できません",
                    "expected": f"{now.isoformat()}以前のISO 8601日時",
                    "alternative": "公式ページを確認した時刻をタイムゾーン付きで指定してください",
                }
            ]
        )
    if item.source_checked_at is not None and checked_at <= _as_utc(item.source_checked_at):
        raise DomainValidationError(
            [
                {
                    "field": "確認日時",
                    "received": checked_at.isoformat(),
                    "reason": "登録済みの最終確認日時より新しい日時を指定してください",
                    "expected": f"{_as_utc(item.source_checked_at).isoformat()}より後のISO 8601日時",
                    "alternative": "同じ確認操作の再試行なら同じrequest_idを使ってください",
                }
            ]
        )

    before = {"source_checked_at": item.source_checked_at}
    item.source_checked_at = checked_at
    db.flush()
    json_response = jsonable_encoder(opportunity_dict(item))
    db.add(
        AuditLog(
            action="verify",
            entity_type="opportunity",
            entity_id=item.id,
            request_id=request_id,
            client_name=client_name,
            source_url=source_url,
            success=True,
            changes={
                "before": jsonable_encoder(before),
                "after": {"source_checked_at": checked_at.isoformat()},
            },
        )
    )
    db.add(
        IdempotencyRecord(
            request_id=request_id,
            operation="verify",
            request_hash=request_hash,
            opportunity_id=item.id,
            response_data=json_response,
        )
    )
    db.commit()
    return item, False


def preview_opportunity_deletion(db: Session, *, opportunity_id: str) -> tuple[Opportunity, int]:
    item = get_opportunity(db, opportunity_id)
    if item is None:
        raise LookupError("opportunity_not_found")
    linked_checks = int(
        db.scalar(
            select(func.count(CollectionCheck.id)).where(CollectionCheck.opportunity_id == opportunity_id)
        )
        or 0
    )
    return item, linked_checks


def _deletion_state(item: Opportunity, deleted_at: datetime) -> dict[str, Any]:
    return {
        "id": item.id,
        "public_code": item.public_code,
        "company_name": item.company.name,
        "event_name": item.event_name,
        "source_url": item.source_url,
        "deleted_at": _as_utc(deleted_at).isoformat(),
    }


def delete_opportunity(
    db: Session,
    *,
    opportunity_id: str,
    expected_updated_at: datetime,
    request_id: str,
    client_name: str,
) -> tuple[dict[str, Any], bool]:
    """Hide one posting from active queries while retaining it for restoration."""
    normalized_expected = _as_utc(expected_updated_at).isoformat()
    request_hash = _hash_payload(
        {"opportunity_id": opportunity_id, "expected_updated_at": normalized_expected}
    )
    previous = db.scalar(select(IdempotencyRecord).where(IdempotencyRecord.request_id == request_id))
    if previous:
        if (
            previous.operation != "delete"
            or previous.opportunity_id != opportunity_id
            or previous.request_hash != request_hash
        ):
            raise DomainValidationError([_reused_request_id_error(request_id)])
        return previous.response_data, True

    item = get_opportunity_for_update(db, opportunity_id)
    if item is None:
        deleted = get_opportunity_including_deleted(db, opportunity_id)
        if deleted is not None and deleted.deleted_at is not None:
            raise DomainValidationError(
                [
                    {
                        "field": "募集情報ID",
                        "received": opportunity_id,
                        "reason": "募集情報は既に削除されています",
                        "expected": "公開中の募集情報ID",
                        "alternative": "復元する場合はrestore_opportunityを使用してください",
                    }
                ]
            )
        raise LookupError("opportunity_not_found")
    ensure_expected_updated_at(item, expected_updated_at)

    before = jsonable_encoder(opportunity_dict(item))
    deleted_at = _next_version_timestamp(item)
    item.deleted_at = deleted_at
    item.updated_at = deleted_at
    db.flush()
    response = _deletion_state(item, deleted_at)
    db.add(
        AuditLog(
            action="delete",
            entity_type="opportunity",
            entity_id=opportunity_id,
            request_id=request_id,
            client_name=client_name,
            source_url=item.source_url,
            success=True,
            changes={
                "request": {"expected_updated_at": normalized_expected},
                "before": before,
                "after": jsonable_encoder(response),
            },
        )
    )
    db.add(
        IdempotencyRecord(
            request_id=request_id,
            operation="delete",
            request_hash=request_hash,
            opportunity_id=item.id,
            response_data=jsonable_encoder(response),
        )
    )
    db.commit()
    return response, False


def restore_opportunity(
    db: Session,
    *,
    opportunity_id: str,
    request_id: str,
    client_name: str,
) -> tuple[dict[str, Any], bool]:
    request_hash = _hash_payload({"opportunity_id": opportunity_id})
    previous = db.scalar(select(IdempotencyRecord).where(IdempotencyRecord.request_id == request_id))
    if previous:
        if (
            previous.operation != "restore"
            or previous.opportunity_id != opportunity_id
            or previous.request_hash != request_hash
        ):
            raise DomainValidationError([_reused_request_id_error(request_id)])
        return previous.response_data, True

    item = get_opportunity_for_update(db, opportunity_id, include_deleted=True)
    if item is None:
        raise LookupError("opportunity_not_found")
    if item.deleted_at is None:
        raise DomainValidationError(
            [
                {
                    "field": "募集情報ID",
                    "received": opportunity_id,
                    "reason": "募集情報は削除されていません",
                    "expected": "削除済みの募集情報ID",
                    "alternative": "公開中の募集情報はget_opportunityで確認できます",
                }
            ]
        )

    _ensure_company_source_allowed(db, company=item.company, source_url=item.source_url)

    duplicates, _ = classify_duplicate_candidates(
        db,
        company_name=item.company.name,
        event_name=item.event_name,
        graduation_years=[value.name for value in item.graduation_years],
        event_start_date=item.event_start_date,
        job_categories=[value.name for value in item.job_categories],
        exclude_id=item.id,
    )
    if duplicates:
        error = _duplicate_error(duplicates)
        error["reason"] = "同じ企業・同名イベントで、対象学年・実施日・対象職種も一致する募集が公開中のため復元できません"
        error["alternative"] = "公開中の登録を確認し、重複を解消してから復元してください"
        raise DomainValidationError([error])

    before = jsonable_encoder(opportunity_dict(item)) | {
        "deleted_at": _as_utc(item.deleted_at).isoformat()
    }
    item.deleted_at = None
    item.updated_at = _next_version_timestamp(item)
    db.flush()
    response = jsonable_encoder(opportunity_dict(item))
    db.add(
        AuditLog(
            action="restore",
            entity_type="opportunity",
            entity_id=item.id,
            request_id=request_id,
            client_name=client_name,
            source_url=item.source_url,
            success=True,
            changes={"before": before, "after": response},
        )
    )
    db.add(
        IdempotencyRecord(
            request_id=request_id,
            operation="restore",
            request_hash=request_hash,
            opportunity_id=item.id,
            response_data=response,
        )
    )
    db.commit()
    return response, False


def recent_write_logs(db: Session, *, client_name: str | None = None, limit: int = 20) -> list[dict[str, Any]]:
    """Recent creates, updates, deletes, and restores for reviewing write history."""
    stmt = select(AuditLog).where(AuditLog.entity_type == "opportunity")
    if client_name:
        stmt = stmt.where(AuditLog.client_name == client_name)
    logs = db.scalars(stmt.order_by(AuditLog.created_at.desc(), AuditLog.id.desc()).limit(limit))
    items = []
    for log in logs:
        after = (log.changes or {}).get("after") or {}
        public_code = after.get("public_code")
        items.append(
            {
                "action": log.action,
                "request_id": log.request_id,
                "client_name": log.client_name,
                "success": log.success,
                "opportunity_id": log.entity_id,
                "url": public_detail_url(public_code) if public_code else None,
                "source_url": log.source_url,
                "errors": log.errors,
                "created_at": log.created_at,
            }
        )
    return items


def record_failed_attempt(
    db: Session,
    *,
    action: str,
    request_id: str | None,
    client_name: str,
    source_url: str | None,
    errors: list[dict[str, Any]],
    entity_type: str = "opportunity",
) -> None:
    db.rollback()
    db.add(
        AuditLog(
            action=action,
            entity_type=entity_type,
            request_id=request_id,
            client_name=client_name,
            source_url=source_url,
            success=False,
            errors=errors,
        )
    )
    db.commit()
