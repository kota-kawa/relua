import hashlib
import json
import math
from dataclasses import dataclass
from typing import Any

from fastapi.encoders import jsonable_encoder
from sqlalchemy import Select, and_, func, or_, select
from sqlalchemy.orm import Session, selectinload

from app.models import (
    PUBLIC_CODE_LENGTH,
    AuditLog,
    Company,
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
    public_code_string,
)
from app.schemas import OpportunityInput
from app.services.errors import master_error
from app.services.masters import choices, resolve_many, resolve_one
from app.services.normalization import normalize_company_name, normalize_tag
from app.services.serialization import opportunity_dict


class DomainValidationError(Exception):
    def __init__(self, errors: list[dict[str, Any]]):
        self.errors = errors
        super().__init__("validation_failed")


@dataclass
class SearchResult:
    items: list[Opportunity]
    total: int
    page: int
    per_page: int

    @property
    def total_pages(self) -> int:
        return max(1, math.ceil(self.total / self.per_page))


def opportunity_query() -> Select[tuple[Opportunity]]:
    return select(Opportunity).options(
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


def get_opportunity(db: Session, opportunity_id: str) -> Opportunity | None:
    return db.scalar(opportunity_query().where(Opportunity.id == opportunity_id))


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
    sort: str = "deadline",
    page: int = 1,
    per_page: int = 20,
) -> SearchResult:
    stmt = opportunity_query().join(Opportunity.company)
    count_stmt = select(func.count(func.distinct(Opportunity.id))).select_from(Opportunity).join(Opportunity.company)

    filters = []
    if q:
        term = f"%{q.strip()}%"
        filters.append(
            or_(
                Company.name.ilike(term),
                Opportunity.event_name.ilike(term),
                Opportunity.description.ilike(term),
                Opportunity.requirements.ilike(term),
            )
        )
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
    if filters:
        stmt = stmt.where(*filters)
        count_stmt = count_stmt.where(*filters)

    if sort == "updated":
        stmt = stmt.order_by(Opportunity.updated_at.desc(), Opportunity.id)
    elif sort == "created":
        stmt = stmt.order_by(Opportunity.created_at.desc(), Opportunity.id)
    else:
        stmt = stmt.order_by(Opportunity.deadline.is_(None), Opportunity.deadline.asc(), Opportunity.id)

    total = int(db.scalar(count_stmt) or 0)
    stmt = stmt.offset((page - 1) * per_page).limit(per_page)
    return SearchResult(items=list(db.scalars(stmt).unique()), total=total, page=page, per_page=per_page)


def _resolve_relations(db: Session, data: OpportunityInput) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    errors: list[dict[str, Any]] = []
    resolved: dict[str, Any] = {}
    singles = [
        ("recruitment_status", RecruitmentStatus, data.recruitment_status),
        ("industry", Industry, data.industry),
        ("sector", Sector, data.sector),
        ("event_type", EventType, data.event_type),
        ("event_format", EventFormat, data.event_format),
    ]
    for field, model, value in singles:
        item = resolve_one(db, model, value)
        if item is None:
            errors.append(master_error(field, value, choices(db, model)))
        else:
            resolved[field] = item

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

    if resolved.get("industry") and resolved.get("sector"):
        if resolved["sector"].industry_id != resolved["industry"].id:
            available = [
                item.name
                for item in db.scalars(
                    select(Sector).where(Sector.industry_id == resolved["industry"].id, Sector.is_active.is_(True))
                )
            ]
            errors.append(master_error("sector", data.sector, available))
    return resolved, errors


def _company(db: Session, name: str) -> Company:
    normalized = normalize_company_name(name)
    company = db.scalar(select(Company).where(Company.normalized_name == normalized))
    if company is None:
        company = Company(name=name, normalized_name=normalized)
        db.add(company)
        db.flush()
    return company


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


def _request_hash(data: OpportunityInput) -> str:
    payload = data.model_dump(mode="json")
    return hashlib.sha256(json.dumps(payload, ensure_ascii=False, sort_keys=True).encode()).hexdigest()


def write_opportunity(
    db: Session,
    *,
    data: OpportunityInput,
    request_id: str,
    client_name: str,
    opportunity_id: str | None = None,
) -> tuple[Opportunity, bool]:
    operation = "update" if opportunity_id else "create"
    request_hash = _request_hash(data)
    previous = db.scalar(select(IdempotencyRecord).where(IdempotencyRecord.request_id == request_id))
    if previous:
        target_mismatch = opportunity_id is not None and previous.opportunity_id != opportunity_id
        if previous.operation != operation or previous.request_hash != request_hash or target_mismatch:
            raise DomainValidationError(
                [
                    {
                        "field": "request_id",
                        "received": request_id,
                        "reason": "同じrequest_idが異なる内容の操作です",
                        "expected": "操作ごとに一意なrequest_id",
                        "example": "client-20260726-0001",
                        "alternative": "新しいrequest_idを発行してください",
                    }
                ]
            )
        item = get_opportunity(db, previous.opportunity_id)
        if item is None:
            raise RuntimeError("idempotency target not found")
        return item, True

    resolved, errors = _resolve_relations(db, data)
    if errors:
        raise DomainValidationError(errors)

    if opportunity_id:
        item = get_opportunity(db, opportunity_id)
        if item is None:
            raise LookupError("opportunity_not_found")
        before = opportunity_dict(item)
        is_new = False
    else:
        item = Opportunity(public_code=_unique_public_code(db))
        before = None
        is_new = True

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
    item.status = resolved["recruitment_status"]
    item.company = _company(db, data.company_name)
    item.industry = resolved["industry"]
    item.sector = resolved["sector"]
    item.event_type = resolved["event_type"]
    item.event_format = resolved["event_format"]
    item.job_categories = resolved["job_categories"]
    item.graduation_years = resolved["graduation_years"]
    item.degrees = resolved["degrees"]
    item.tags = _tags(db, data.tags)
    if is_new:
        db.add(item)
    db.flush()
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


def record_failed_attempt(
    db: Session,
    *,
    action: str,
    request_id: str | None,
    client_name: str,
    source_url: str | None,
    errors: list[dict[str, Any]],
) -> None:
    db.rollback()
    db.add(
        AuditLog(
            action=action,
            entity_type="opportunity",
            request_id=request_id,
            client_name=client_name,
            source_url=source_url,
            success=False,
            errors=errors,
        )
    )
    db.commit()
