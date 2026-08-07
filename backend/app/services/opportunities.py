import hashlib
import json
import math
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from typing import Any

from fastapi.encoders import jsonable_encoder
from sqlalchemy import Select, and_, func, or_, select
from sqlalchemy.orm import Session, selectinload

from app.models import (
    PUBLIC_CODE_LENGTH,
    AuditLog,
    CollectionCheck,
    CollectionTarget,
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
from app.services.errors import FIELD_LABELS, master_error
from app.services.masters import choices, resolve_many, resolve_one
from app.services.normalization import normalize_common, normalize_company_name, normalize_source_url, normalize_tag
from app.services.serialization import detail_url, opportunity_dict, public_detail_url


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


def get_opportunity_for_update(db: Session, opportunity_id: str) -> Opportunity | None:
    return db.scalar(opportunity_query().where(Opportunity.id == opportunity_id).with_for_update())


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


def _company_opportunities(db: Session, company_name: str, exclude_id: str | None = None) -> list[Opportunity]:
    normalized = normalize_company_name(company_name)
    stmt = opportunity_query().join(Opportunity.company).where(Company.normalized_name == normalized)
    if exclude_id:
        stmt = stmt.where(Opportunity.id != exclude_id)
    return list(db.scalars(stmt.order_by(Opportunity.updated_at.desc())).unique())


def find_similar_opportunities(
    db: Session,
    *,
    company_name: str,
    event_name: str | None = None,
    exclude_id: str | None = None,
    limit: int = 20,
) -> list[Opportunity]:
    """Entries of the same company, narrowed by a loose event-name match.

    Company names are compared after normalization, so "(株)X" and "株式会社X" collapse to one company.
    Event names match on containment in either direction, which catches "サマーインターン" against
    "サマーインターン2027" — near-misses a caller should look at before adding a second record.
    """
    items = _company_opportunities(db, company_name, exclude_id)
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


def find_source_url_duplicates(
    db: Session, *, source_url: str, exclude_id: str | None = None, limit: int = 20
) -> list[Opportunity]:
    normalized = normalize_source_url(source_url)
    stmt = opportunity_query().where(Opportunity.normalized_source_url == normalized)
    if exclude_id:
        stmt = stmt.where(Opportunity.id != exclude_id)
    return list(db.scalars(stmt.order_by(Opportunity.updated_at.desc()).limit(limit)).unique())


def _reused_request_id_error(request_id: str) -> dict[str, Any]:
    return {
        "field": "request_id",
        "received": request_id,
        "reason": "同じrequest_idが異なる内容の操作です",
        "expected": "操作ごとに一意なrequest_id",
        "example": "client-20260726-0001",
        "alternative": "新しいrequest_idを発行してください",
    }


def _duplicate_error(matches: list[Opportunity]) -> dict[str, Any]:
    return {
        "field": "イベント名",
        "received": matches[0].event_name,
        "reason": "同じ企業の同名イベントが既に登録されています",
        "expected": "未登録のイベント名",
        "example": None,
        "alternative": (
            "既存の登録を直す場合はupdate_opportunityを使い、"
            "別日程・別コースで意図的に分けて登録する場合はallow_duplicateをtrueにしてください"
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


def validate_write(db: Session, *, data: OpportunityInput) -> list[dict[str, Any]]:
    """Master-value checks with nothing written, backing the dry-run tool."""
    _, errors = _resolve_relations(db, data)
    return errors


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


def _collection_target_for_write(
    db: Session,
    *,
    collection_target_id: int | None,
    data: OpportunityInput,
    industry: Industry,
    request_id: str,
) -> CollectionTarget | None:
    if collection_target_id is None:
        return None
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
    if target.company.normalized_name != normalize_company_name(data.company_name) or target.industry_id != industry.id:
        raise DomainValidationError(
            [
                {
                    "field": "情報収集対象ID",
                    "received": collection_target_id,
                    "reason": "収集対象の企業・業界と募集情報が一致しません",
                    "expected": f"{target.company.name} / {target.industry.name}",
                }
            ]
        )
    existing_check = db.scalar(select(CollectionCheck).where(CollectionCheck.request_id == request_id))
    if existing_check is not None:
        raise DomainValidationError([_reused_request_id_error(request_id)])
    return target


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
        item = get_opportunity(db, previous.opportunity_id)
        if item is None:
            raise RuntimeError("idempotency target not found")
        return item, True

    if opportunity_id is None and not allow_duplicate:
        # Idempotency only catches a replay of the same request_id. A client that re-reads the same
        # source page next week sends a new request_id, so the same posting would land twice.
        duplicates = find_exact_duplicates(db, company_name=data.company_name, event_name=data.event_name)
        if duplicates:
            raise DomainValidationError([_duplicate_error(duplicates)])

    resolved, errors = _resolve_relations(db, data)
    if errors:
        raise DomainValidationError(errors)

    collection_target = _collection_target_for_write(
        db,
        collection_target_id=collection_target_id,
        data=data,
        industry=resolved["industry"],
        request_id=request_id,
    )

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
    item.company = _company(db, data.company_name)
    item.industry = resolved["industry"]
    item.sector = resolved["sector"]
    item.event_type = resolved["event_type"]
    item.event_format = resolved["event_format"]
    item.job_categories = resolved["job_categories"]
    item.graduation_years = resolved["graduation_years"]
    item.degrees = resolved["degrees"]
    item.tags = _tags(db, data.tags)
    # Every source-backed write advances the version used by optimistic locking. Python's
    # microsecond clock also keeps SQLite tests from collapsing two writes into one timestamp.
    verified_at = datetime.now(timezone.utc)  # noqa: UP017 -- tests also support Python 3.10
    if item.updated_at is not None and verified_at <= _as_utc(item.updated_at):
        verified_at = _as_utc(item.updated_at) + timedelta(microseconds=1)
    item.updated_at = verified_at
    if is_new:
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
        item = get_opportunity(db, previous.opportunity_id)
        if item is None:
            raise RuntimeError("idempotency target not found")
        return item, True

    item = get_opportunity(db, opportunity_id)
    if item is None:
        raise LookupError("opportunity_not_found")

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
    #: A status edit is still an agent reporting what the source says now, so it refreshes the stamp.
    item.updated_at = func.now()
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


def recent_write_logs(db: Session, *, client_name: str | None = None, limit: int = 20) -> list[dict[str, Any]]:
    """What this connection already wrote, so an agent can see its own history instead of re-registering."""
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
