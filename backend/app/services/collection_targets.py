import hashlib
import json
import math
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any

from fastapi.encoders import jsonable_encoder
from sqlalchemy import case, func, or_, select
from sqlalchemy.orm import Session, selectinload

from app.models import (
    AuditLog,
    CollectionCheck,
    CollectionRequestRecord,
    CollectionSource,
    CollectionTarget,
    Company,
    CompanyIndustry,
    Industry,
    Opportunity,
    Sector,
)
from app.schemas import (
    CollectionCheckRequest,
    CollectionSourceCreateRequest,
    CollectionSourceUpdateRequest,
    CollectionTargetCreateRequest,
    CollectionTargetUpdateRequest,
    CompanyIndustryInput,
)
from app.services.companies import company_identity_dict, company_keyword_filter, get_or_create_company
from app.services.company_industries import (
    company_industries,
    company_industry_dict,
    primary_company_industry,
    set_company_industries,
)
from app.services.errors import master_error
from app.services.masters import choices, resolve_one, resolve_sector
from app.services.opportunities import DomainValidationError
from app.services.serialization import detail_url, master_dict


@dataclass
class CollectionTargetList:
    items: list[CollectionTarget]
    total: int
    page: int
    per_page: int

    @property
    def total_pages(self) -> int:
        return max(1, math.ceil(self.total / self.per_page))


@dataclass
class UnmonitoredCompany:
    company: Company
    opportunity_count: int


@dataclass
class UnmonitoredCompanyList:
    items: list[UnmonitoredCompany]
    total: int
    page: int
    per_page: int

    @property
    def total_pages(self) -> int:
        return max(1, math.ceil(self.total / self.per_page))


def collection_target_query():
    return select(CollectionTarget).options(
        selectinload(CollectionTarget.company).selectinload(Company.industries),
        selectinload(CollectionTarget.sources),
    )


def get_collection_target(db: Session, target_id: int) -> CollectionTarget | None:
    return db.scalar(collection_target_query().where(CollectionTarget.id == target_id))


def get_collection_source(db: Session, source_id: int) -> CollectionSource | None:
    return db.scalar(select(CollectionSource).where(CollectionSource.id == source_id))


def _opportunity_references(db: Session, target: CollectionTarget) -> list[dict[str, Any]]:
    items = db.scalars(
        select(Opportunity)
        .options(selectinload(Opportunity.status))
        .where(
            Opportunity.company_id == target.company_id,
            Opportunity.deleted_at.is_(None),
        )
        .order_by(Opportunity.updated_at.desc(), Opportunity.id)
    )
    return [
        {
            "id": item.id,
            "public_code": item.public_code,
            "url": detail_url(item),
            "event_name": item.event_name,
            "recruitment_status": item.status.name,
            "source_url": item.source_url,
            "updated_at": item.updated_at,
        }
        for item in items
    ]


def collection_source_dict(source: CollectionSource) -> dict[str, Any]:
    return {
        "id": source.id,
        "source_type": source.source_type,
        "url": source.url,
        "is_active": source.is_active,
        "last_checked_at": source.last_checked_at,
        "created_at": source.created_at,
        "updated_at": source.updated_at,
    }


#: Maps the existing last_check_result values onto a friendlier, self-explanatory vocabulary,
#: combined with last_checked_at IS NULL below - no schema change, purely a derived view.
_CHECK_STATUS_BY_RESULT = {
    "found": "found",
    "no_opening": "no_active_opportunity",
    "unreachable": "source_unavailable",
    "needs_review": "needs_review",
}


def _check_status(target: CollectionTarget) -> str:
    if target.last_checked_at is None:
        return "unreviewed"
    return _CHECK_STATUS_BY_RESULT.get(target.last_check_result, "needs_review")


#: The source types that actually carry openings. A target monitoring only the corporate top page
#: (source_type='other') technically has a source, but nothing that a new posting would appear on,
#: so it silently produces no_opening forever. These two decide has_primary_source below.
PRIMARY_SOURCE_TYPES = ("recruit", "internship")
#: Reported as missing_source_types so an operator can see which official pages are still unknown.
#: 'other' is excluded on purpose - it is the catch-all, never something to go hunt for.
TRACKED_SOURCE_TYPES = ("recruit", "internship", "event", "news")


def _source_coverage(target: CollectionTarget) -> tuple[bool, list[str]]:
    present = {source.source_type for source in target.sources if source.is_active}
    return (
        any(source_type in present for source_type in PRIMARY_SOURCE_TYPES),
        [source_type for source_type in TRACKED_SOURCE_TYPES if source_type not in present],
    )


def collection_target_dict(db: Session, target: CollectionTarget) -> dict[str, Any]:
    opportunities = _opportunity_references(db, target)
    has_primary_source, missing_source_types = _source_coverage(target)
    classifications = company_industries(db, target.company_id)
    primary = primary_company_industry(classifications)
    return {
        "id": target.id,
        "company": {"id": target.company.id, "name": target.company.name},
        #: Every industry this company belongs to. A company spanning two industries is one target
        #: with two entries here, never two targets.
        "industries": [company_industry_dict(row) for row in classifications],
        #: The single industry to show where only one fits, derived from `industries` above.
        "primary_industry": master_dict(primary.industry) if primary else None,
        "primary_sector": master_dict(primary.sector) if primary and primary.sector else None,
        "priority_tier": target.priority_tier,
        "check_interval_days": target.check_interval_days,
        "last_checked_at": target.last_checked_at,
        "next_check_at": target.next_check_at,
        "last_check_result": target.last_check_result,
        "check_status": _check_status(target),
        "last_found_at": target.last_found_at,
        "is_active": target.is_active,
        "selection_reason": target.selection_reason,
        "sources": [
            collection_source_dict(source)
            for source in sorted(target.sources, key=lambda value: (not value.is_active, value.id))
        ],
        #: False when every active source is a corporate top page or similar catch-all. Such a target
        #: is monitored but structurally unable to surface a new opening, so it needs an operator to
        #: find the real recruit/internship page - see list_collection_targets(source_gap=True).
        "has_primary_source": has_primary_source,
        "missing_source_types": missing_source_types,
        "opportunities": opportunities,
        #: Every live posting for this company. A target covers the whole company, so there is no
        #: longer a second, industry-scoped count that could disagree with this one.
        "company_opportunity_count": len(opportunities),
        "created_at": target.created_at,
        "updated_at": target.updated_at,
    }


def collection_check_dict(check: CollectionCheck) -> dict[str, Any]:
    return {
        "id": check.id,
        "collection_target_id": check.collection_target_id,
        "result": check.result,
        "checked_at": check.checked_at,
        "source_url": check.source_url,
        "opportunity_id": check.opportunity_id,
        "request_id": check.request_id,
        "client_name": check.client_name,
        "note": check.note,
    }


def list_collection_checks(db: Session, *, target_id: int, limit: int = 20) -> list[CollectionCheck]:
    if get_collection_target(db, target_id) is None:
        raise LookupError("collection_target_not_found")
    return list(
        db.scalars(
            select(CollectionCheck)
            .where(CollectionCheck.collection_target_id == target_id)
            .order_by(CollectionCheck.checked_at.desc(), CollectionCheck.id.desc())
            .limit(limit)
        )
    )


def _classified_as_clause(*, industry: str | None = None, sector: str | None = None):
    """Match targets whose company carries the given industry or sector classification.

    Classification is company-level and many-to-many, so an industry filter is an EXISTS over
    company_industries rather than a column comparison: Ubie appears under both IT・通信 and
    医療・製薬 while remaining a single target.
    """
    conditions = [CompanyIndustry.company_id == CollectionTarget.company_id]
    if industry is not None:
        conditions.append(
            CompanyIndustry.industry_id.in_(
                select(Industry.id).where(or_(Industry.name == industry, Industry.slug == industry))
            )
        )
    if sector is not None:
        conditions.append(
            CompanyIndustry.sector_id.in_(
                select(Sector.id).where(or_(Sector.name == sector, Sector.slug == sector))
            )
        )
    return select(CompanyIndustry.id).where(*conditions).correlate(CollectionTarget).exists()


def _company_classified_as_clause(*, industry: str | None = None):
    """Company-level counterpart for the unmonitored-company repair queue."""
    conditions = [CompanyIndustry.company_id == Company.id]
    if industry is not None:
        conditions.append(
            CompanyIndustry.industry_id.in_(
                select(Industry.id).where(or_(Industry.name == industry, Industry.slug == industry))
            )
        )
    return select(CompanyIndustry.id).where(*conditions).correlate(Company).exists()


def _has_primary_source_clause():
    """SQL twin of _source_coverage's first element, for filtering without loading every source."""

    return (
        select(CollectionSource.id)
        .where(
            CollectionSource.collection_target_id == CollectionTarget.id,
            CollectionSource.is_active.is_(True),
            CollectionSource.source_type.in_(PRIMARY_SOURCE_TYPES),
        )
        .correlate(CollectionTarget)
        .exists()
    )


def list_collection_targets(
    db: Session,
    *,
    query: str | None = None,
    industry: str | None = None,
    sector: str | None = None,
    priority_tier: int | None = None,
    due_only: bool = False,
    source_gap: bool = False,
    include_inactive: bool = False,
    page: int = 1,
    per_page: int = 20,
) -> CollectionTargetList:
    stmt = collection_target_query().join(CollectionTarget.company)
    count_stmt = select(func.count(CollectionTarget.id)).select_from(CollectionTarget).join(CollectionTarget.company)
    filters = []
    if query:
        filters.append(company_keyword_filter(db, query.strip()))
    if industry:
        filters.append(_classified_as_clause(industry=industry))
    if sector:
        filters.append(_classified_as_clause(sector=sector))
    if priority_tier:
        filters.append(CollectionTarget.priority_tier == priority_tier)
    if source_gap:
        filters.append(~_has_primary_source_clause())
    if not include_inactive:
        filters.append(CollectionTarget.is_active.is_(True))
    if due_only:
        now = datetime.now(timezone.utc)  # noqa: UP017 -- tests also support Python 3.10
        filters.append(
            or_(
                CollectionTarget.last_checked_at.is_(None),
                CollectionTarget.next_check_at.is_(None),
                CollectionTarget.next_check_at <= now,
            )
        )
    if filters:
        stmt = stmt.where(*filters)
        count_stmt = count_stmt.where(*filters)
    stmt = stmt.order_by(
        CollectionTarget.priority_tier,
        case((CollectionTarget.last_checked_at.is_(None), 0), else_=1),
        CollectionTarget.next_check_at,
        Company.name,
    )
    total = int(db.scalar(count_stmt) or 0)
    items = list(db.scalars(stmt.offset((page - 1) * per_page).limit(per_page)).unique())
    return CollectionTargetList(items=items, total=total, page=page, per_page=per_page)


def collection_queue(db: Session, *, industry: str | None = None, limit: int = 20) -> list[CollectionTarget]:
    return list_collection_targets(
        db,
        industry=industry,
        due_only=True,
        include_inactive=False,
        page=1,
        per_page=limit,
    ).items


def undercovered_collection_targets(
    db: Session, *, industry: str | None = None, limit: int = 50
) -> list[CollectionTarget]:
    """Active targets ordered by how few live postings their company has, fewest first.

    Lets an operator fetch "companies we're missing postings for" directly, instead of paging
    through the whole queue client-side and filtering on opportunities == []. Counted per company
    rather than per company-and-industry, so a company whose postings are filed under one of its
    several industries no longer reports as uncovered under the others.
    """
    linked_count = (
        select(func.count(Opportunity.id))
        .where(
            Opportunity.company_id == CollectionTarget.company_id,
            Opportunity.deleted_at.is_(None),
        )
        .correlate(CollectionTarget)
        .scalar_subquery()
    )
    stmt = collection_target_query().join(CollectionTarget.company).where(CollectionTarget.is_active.is_(True))
    if industry:
        stmt = stmt.where(_classified_as_clause(industry=industry))
    stmt = stmt.order_by(linked_count.asc(), Company.name).limit(limit)
    return list(db.scalars(stmt).unique())


def unmonitored_company_dict(item: UnmonitoredCompany) -> dict[str, Any]:
    return company_identity_dict(item.company) | {
        "industries": [company_industry_dict(row) for row in company_industries_for_dict(item.company)],
        "company_opportunity_count": item.opportunity_count,
        "created_at": item.company.created_at,
    }


def company_industries_for_dict(company: Company) -> list[CompanyIndustry]:
    """Use the eagerly loaded relationship when listing many companies, primary first."""
    return sorted(company.industries, key=lambda row: (not row.is_primary, row.id))


def list_unmonitored_companies(
    db: Session,
    *,
    query: str | None = None,
    industry: str | None = None,
    page: int = 1,
    per_page: int = 20,
) -> UnmonitoredCompanyList:
    """Find master companies that have no collection target yet.

    This is deliberately a Company query rather than a collection-target filter: it exposes
    postings-created companies that are otherwise invisible to the monitoring workflow.
    """
    opportunity_count = (
        select(func.count(Opportunity.id))
        .where(Opportunity.company_id == Company.id, Opportunity.deleted_at.is_(None))
        .correlate(Company)
        .scalar_subquery()
    )
    filters = [~Company.id.in_(select(CollectionTarget.company_id))]
    if query:
        filters.append(company_keyword_filter(db, query.strip()))
    if industry:
        filters.append(_company_classified_as_clause(industry=industry))
    count_stmt = select(func.count(Company.id)).where(*filters)
    stmt = (
        select(Company, opportunity_count.label("opportunity_count"))
        .options(
            selectinload(Company.aliases),
            selectinload(Company.industries).selectinload(CompanyIndustry.industry),
            selectinload(Company.industries).selectinload(CompanyIndustry.sector),
        )
        .where(*filters)
        .order_by(Company.name)
        .offset((page - 1) * per_page)
        .limit(per_page)
    )
    rows = db.execute(stmt).all()
    return UnmonitoredCompanyList(
        items=[UnmonitoredCompany(company=row[0], opportunity_count=int(row[1])) for row in rows],
        total=int(db.scalar(count_stmt) or 0),
        page=page,
        per_page=per_page,
    )


def _hash_payload(payload: dict[str, Any]) -> str:
    return hashlib.sha256(json.dumps(payload, ensure_ascii=False, sort_keys=True, default=str).encode()).hexdigest()


def _request_hash(payload: Any, **context: Any) -> str:
    return _hash_payload(payload.model_dump(mode="json") | context)


def _request_id_error(request_id: str) -> dict[str, Any]:
    return {
        "field": "request_id",
        "received": request_id,
        "reason": "同じrequest_idが異なる収集リスト操作で使用されています",
        "expected": "操作ごとに一意なrequest_id",
        "example": "chatgpt-collection-20260807-0001",
        "alternative": "新しいrequest_idを発行してください",
    }


def _replayed_entity_id(db: Session, *, request_id: str, operation: str, request_hash: str) -> str | None:
    previous = db.scalar(select(CollectionRequestRecord).where(CollectionRequestRecord.request_id == request_id))
    if previous is None:
        return None
    if previous.operation != operation or previous.request_hash != request_hash:
        raise DomainValidationError([_request_id_error(request_id)])
    return previous.entity_id


def _remember_request(
    db: Session,
    *,
    request_id: str,
    operation: str,
    request_hash: str,
    entity_type: str,
    entity_id: int,
) -> None:
    db.add(
        CollectionRequestRecord(
            request_id=request_id,
            operation=operation,
            request_hash=request_hash,
            entity_type=entity_type,
            entity_id=str(entity_id),
        )
    )


def _audit(
    db: Session,
    *,
    action: str,
    entity_type: str,
    entity_id: int,
    request_id: str,
    client_name: str,
    source_url: str | None,
    before: dict[str, Any] | None,
    after: dict[str, Any],
) -> None:
    db.add(
        AuditLog(
            action=action,
            entity_type=entity_type,
            entity_id=str(entity_id),
            request_id=request_id,
            client_name=client_name,
            source_url=source_url,
            success=True,
            changes={"before": jsonable_encoder(before), "after": jsonable_encoder(after)},
        )
    )


#: Tier 1 is meant to order a short "check these first" list, not to describe most of the queue.
#: A cap keeps it a priority signal instead of a headcount that only ever grows.
PRIORITY_TIER_1_CAP = 200


def _ensure_tier_one_capacity(db: Session) -> None:
    count = int(
        db.scalar(
            select(func.count(CollectionTarget.id)).where(
                CollectionTarget.priority_tier == 1, CollectionTarget.is_active.is_(True)
            )
        )
        or 0
    )
    if count >= PRIORITY_TIER_1_CAP:
        raise DomainValidationError(
            [
                {
                    "field": "priority_tier",
                    "received": 1,
                    "reason": f"tier1の収集対象が上限（{PRIORITY_TIER_1_CAP}社）に達しています",
                    "expected": f"tier1は{PRIORITY_TIER_1_CAP}社以下",
                    "alternative": "既存のtier1対象をtier2以下に見直してから追加するか、tier2以下で登録してください",
                }
            ]
        )


def _resolve_classification(
    db: Session, *, industry_value: str, sector_value: str | None
) -> tuple[Industry, Sector | None]:
    industry = resolve_one(db, Industry, industry_value)
    if industry is None:
        raise DomainValidationError([master_error("industry", industry_value, choices(db, Industry))])
    sector = None
    if sector_value is not None:
        sector = resolve_sector(db, industry_id=industry.id, value=sector_value)
        if sector is None:
            available = list(
                db.scalars(
                    select(Sector.name)
                    .where(Sector.industry_id == industry.id, Sector.is_active.is_(True))
                    .order_by(Sector.sort_order, Sector.id)
                )
            )
            raise DomainValidationError([master_error("sector", sector_value, available)])
    return industry, sector


def _resolve_classifications(
    db: Session, entries: list[CompanyIndustryInput]
) -> list[tuple[Industry, Sector | None]]:
    resolved = []
    seen: set[int] = set()
    for entry in entries:
        industry, sector = _resolve_classification(db, industry_value=entry.industry, sector_value=entry.sector)
        if industry.id in seen:
            raise DomainValidationError(
                [
                    {
                        "field": "業界",
                        "received": entry.industry,
                        "reason": "同じ業界を重複して指定できません",
                        "expected": "業界ごとに1件",
                    }
                ]
            )
        seen.add(industry.id)
        resolved.append((industry, sector))
    return resolved


def create_collection_target(db: Session, payload: CollectionTargetCreateRequest) -> tuple[CollectionTarget, bool]:
    operation = "collection_target_create"
    request_hash = _request_hash(payload)
    replay_id = _replayed_entity_id(db, request_id=payload.request_id, operation=operation, request_hash=request_hash)
    if replay_id is not None:
        target = get_collection_target(db, int(replay_id))
        if target is None:
            raise RuntimeError("collection target idempotency target not found")
        return target, True

    if payload.priority_tier == 1:
        _ensure_tier_one_capacity(db)

    classifications = _resolve_classifications(db, payload.industries)
    if payload.company_id is not None:
        company = db.get(Company, payload.company_id)
        if company is None:
            raise LookupError("company_not_found")
    else:
        # The schema guarantees company_name is present when an ID was not supplied.
        company = get_or_create_company(db, payload.company_name or "")
    existing = db.scalar(select(CollectionTarget).where(CollectionTarget.company_id == company.id))
    if existing is not None:
        raise DomainValidationError(
            [
                {
                    "field": "企業名",
                    "received": company.name,
                    "reason": "この企業の収集対象が既に存在します",
                    "expected": "未登録の企業",
                    "example": None,
                    "alternative": (
                        f"業界を追加したい場合もtarget_id={existing.id}をupdate_collection_targetのindustriesで"
                        "更新してください。1つの企業につき収集対象は1件です"
                    ),
                }
            ]
        )

    target = CollectionTarget(
        company=company,
        priority_tier=payload.priority_tier,
        check_interval_days=payload.check_interval_days,
        selection_reason=payload.selection_reason,
    )
    target.sources = [CollectionSource(source_type=source.source_type, url=source.url) for source in payload.sources]
    db.add(target)
    set_company_industries(db, company=company, classifications=classifications)
    db.flush()
    after = collection_target_dict(db, target)
    _audit(
        db,
        action="collection_target_create",
        entity_type="collection_target",
        entity_id=target.id,
        request_id=payload.request_id,
        client_name=payload.client_name,
        source_url=target.sources[0].url,
        before=None,
        after=after,
    )
    _remember_request(
        db,
        request_id=payload.request_id,
        operation=operation,
        request_hash=request_hash,
        entity_type="collection_target",
        entity_id=target.id,
    )
    db.commit()
    return target, False


def update_collection_target(
    db: Session, *, target_id: int, payload: CollectionTargetUpdateRequest
) -> tuple[CollectionTarget, bool]:
    operation = "collection_target_update"
    request_hash = _request_hash(payload, target_id=target_id)
    replay_id = _replayed_entity_id(db, request_id=payload.request_id, operation=operation, request_hash=request_hash)
    if replay_id is not None:
        target = get_collection_target(db, int(replay_id))
        if target is None:
            raise RuntimeError("collection target idempotency target not found")
        return target, True
    target = get_collection_target(db, target_id)
    if target is None:
        raise LookupError("collection_target_not_found")
    before = collection_target_dict(db, target)
    fields = payload.model_fields_set

    company = target.company
    if "company_name" in fields:
        if payload.company_name is None:
            raise DomainValidationError([{"field": "企業名", "received": None, "reason": "nullにはできません"}])
        company = get_or_create_company(db, payload.company_name)
    classifications = None
    if "industries" in fields:
        if not payload.industries:
            raise DomainValidationError([{"field": "業界", "received": None, "reason": "1件以上指定してください"}])
        classifications = _resolve_classifications(db, payload.industries)
    collision = db.scalar(
        select(CollectionTarget).where(
            CollectionTarget.company_id == company.id,
            CollectionTarget.id != target.id,
        )
    )
    if collision is not None:
        raise DomainValidationError(
            [
                {
                    "field": "企業名",
                    "received": company.name,
                    "reason": "この企業の収集対象が既に存在します",
                    "alternative": f"target_id={collision.id}へ統合してください",
                }
            ]
        )
    final_priority_tier = payload.priority_tier if "priority_tier" in fields else target.priority_tier
    final_is_active = payload.is_active if "is_active" in fields else target.is_active
    already_active_tier_one = target.priority_tier == 1 and target.is_active
    if final_priority_tier == 1 and final_is_active and not already_active_tier_one:
        _ensure_tier_one_capacity(db)

    target.company = company
    if classifications is not None:
        set_company_industries(db, company=company, classifications=classifications)
    for name in ("priority_tier", "check_interval_days", "selection_reason", "is_active"):
        if name in fields:
            value = getattr(payload, name)
            if name in {"priority_tier", "check_interval_days", "is_active"} and value is None:
                raise DomainValidationError([{"field": name, "received": None, "reason": "nullにはできません"}])
            setattr(target, name, value)
    if "check_interval_days" in fields and target.last_checked_at is not None:
        target.next_check_at = target.last_checked_at + timedelta(days=target.check_interval_days)
    db.flush()
    after = collection_target_dict(db, target)
    _audit(
        db,
        action="collection_target_update",
        entity_type="collection_target",
        entity_id=target.id,
        request_id=payload.request_id,
        client_name=payload.client_name,
        source_url=next((source.url for source in target.sources if source.is_active), None),
        before=before,
        after=after,
    )
    _remember_request(
        db,
        request_id=payload.request_id,
        operation=operation,
        request_hash=request_hash,
        entity_type="collection_target",
        entity_id=target.id,
    )
    db.commit()
    return target, False


def create_collection_source(
    db: Session, *, target_id: int, payload: CollectionSourceCreateRequest
) -> tuple[CollectionSource, bool]:
    operation = "collection_source_create"
    request_hash = _request_hash(payload, target_id=target_id)
    replay_id = _replayed_entity_id(db, request_id=payload.request_id, operation=operation, request_hash=request_hash)
    if replay_id is not None:
        source = get_collection_source(db, int(replay_id))
        if source is None:
            raise RuntimeError("collection source idempotency target not found")
        return source, True
    target = get_collection_target(db, target_id)
    if target is None:
        raise LookupError("collection_target_not_found")
    if any(source.url == payload.url for source in target.sources):
        raise DomainValidationError(
            [{"field": "情報源URL", "received": payload.url, "reason": "同じURLが既に登録されています"}]
        )
    source = CollectionSource(
        collection_target_id=target.id,
        source_type=payload.source_type,
        url=payload.url,
    )
    db.add(source)
    db.flush()
    after = collection_source_dict(source)
    _audit(
        db,
        action="collection_source_create",
        entity_type="collection_source",
        entity_id=source.id,
        request_id=payload.request_id,
        client_name=payload.client_name,
        source_url=source.url,
        before=None,
        after=after,
    )
    _remember_request(
        db,
        request_id=payload.request_id,
        operation=operation,
        request_hash=request_hash,
        entity_type="collection_source",
        entity_id=source.id,
    )
    db.commit()
    return source, False


def update_collection_source(
    db: Session, *, source_id: int, payload: CollectionSourceUpdateRequest
) -> tuple[CollectionSource, bool]:
    operation = "collection_source_update"
    request_hash = _request_hash(payload, source_id=source_id)
    replay_id = _replayed_entity_id(db, request_id=payload.request_id, operation=operation, request_hash=request_hash)
    if replay_id is not None:
        source = get_collection_source(db, int(replay_id))
        if source is None:
            raise RuntimeError("collection source idempotency target not found")
        return source, True
    source = get_collection_source(db, source_id)
    if source is None:
        raise LookupError("collection_source_not_found")
    before = collection_source_dict(source)
    for name in ("source_type", "url", "is_active"):
        if name in payload.model_fields_set:
            value = getattr(payload, name)
            if value is None:
                raise DomainValidationError([{"field": name, "received": None, "reason": "nullにはできません"}])
            setattr(source, name, value)
    db.flush()
    after = collection_source_dict(source)
    _audit(
        db,
        action="collection_source_update",
        entity_type="collection_source",
        entity_id=source.id,
        request_id=payload.request_id,
        client_name=payload.client_name,
        source_url=source.url,
        before=before,
        after=after,
    )
    _remember_request(
        db,
        request_id=payload.request_id,
        operation=operation,
        request_hash=request_hash,
        entity_type="collection_source",
        entity_id=source.id,
    )
    db.commit()
    return source, False


def record_collection_check(
    db: Session, *, target_id: int, payload: CollectionCheckRequest
) -> tuple[CollectionCheck, CollectionTarget, bool]:
    operation = "collection_check_create"
    request_hash = _request_hash(payload, target_id=target_id)
    replay_id = _replayed_entity_id(db, request_id=payload.request_id, operation=operation, request_hash=request_hash)
    if replay_id is not None:
        check = db.get(CollectionCheck, int(replay_id))
        if check is None:
            raise RuntimeError("collection check idempotency target not found")
        target = get_collection_target(db, check.collection_target_id)
        if target is None:
            raise RuntimeError("collection check target not found")
        return check, target, True
    target = get_collection_target(db, target_id)
    if target is None:
        raise LookupError("collection_target_not_found")
    opportunity = None
    if payload.opportunity_id:
        opportunity = db.get(Opportunity, payload.opportunity_id)
        if opportunity is None:
            raise DomainValidationError(
                [{"field": "opportunity_id", "received": payload.opportunity_id, "reason": "募集情報が見つかりません"}]
            )
        if opportunity.company_id != target.company_id:
            raise DomainValidationError(
                [
                    {
                        "field": "opportunity_id",
                        "received": payload.opportunity_id,
                        "reason": "収集対象の企業と一致しません",
                    }
                ]
            )
    now = datetime.now(timezone.utc)  # noqa: UP017 -- tests also support Python 3.10
    check = CollectionCheck(
        collection_target_id=target.id,
        result=payload.result,
        checked_at=now,
        source_url=payload.source_url,
        opportunity=opportunity,
        request_id=payload.request_id,
        client_name=payload.client_name,
        note=payload.note,
    )
    db.add(check)
    target.last_checked_at = now
    target.next_check_at = now + timedelta(days=target.check_interval_days)
    target.last_check_result = payload.result
    if payload.result == "found":
        target.last_found_at = now
        if opportunity is not None:
            # A "found, unchanged" confirmation never calls write_opportunity, so without this the
            # posting's official-source-confirmed date would go stale even though someone just verified
            # it. Deliberately not touching opportunity.updated_at, which drives optimistic locking.
            opportunity.source_checked_at = now
    if payload.source_url:
        for source in target.sources:
            if source.url == payload.source_url:
                source.last_checked_at = now
                break
    # Closes the loop for targets that only knew the corporate top page: whoever just read that page
    # can register the recruit/internship pages it linked to, in the same call as the check result,
    # instead of remembering to follow up with add_collection_source afterwards.
    known_urls = {source.url for source in target.sources}
    added_sources = []
    for discovered in payload.discovered_sources:
        if discovered.url in known_urls:
            continue
        known_urls.add(discovered.url)
        source = CollectionSource(source_type=discovered.source_type, url=discovered.url)
        target.sources.append(source)
        added_sources.append(source)
    db.flush()
    check_after = collection_check_dict(check)
    if added_sources:
        check_after["discovered_sources"] = [collection_source_dict(source) for source in added_sources]
    _audit(
        db,
        action="collection_check_create",
        entity_type="collection_check",
        entity_id=check.id,
        request_id=payload.request_id,
        client_name=payload.client_name,
        source_url=payload.source_url,
        before=None,
        after=check_after,
    )
    _remember_request(
        db,
        request_id=payload.request_id,
        operation=operation,
        request_hash=request_hash,
        entity_type="collection_check",
        entity_id=check.id,
    )
    db.commit()
    return check, target, False
