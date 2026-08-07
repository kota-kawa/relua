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
)
from app.services.errors import master_error
from app.services.masters import choices, resolve_one
from app.services.normalization import normalize_company_name
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


def collection_target_query():
    return select(CollectionTarget).options(
        selectinload(CollectionTarget.company),
        selectinload(CollectionTarget.industry),
        selectinload(CollectionTarget.sector),
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
            Opportunity.industry_id == target.industry_id,
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


def collection_target_dict(db: Session, target: CollectionTarget) -> dict[str, Any]:
    return {
        "id": target.id,
        "company": {"id": target.company.id, "name": target.company.name},
        "industry": master_dict(target.industry),
        "sector": master_dict(target.sector) if target.sector else None,
        "priority_tier": target.priority_tier,
        "check_interval_days": target.check_interval_days,
        "last_checked_at": target.last_checked_at,
        "next_check_at": target.next_check_at,
        "last_check_result": target.last_check_result,
        "last_found_at": target.last_found_at,
        "is_active": target.is_active,
        "selection_reason": target.selection_reason,
        "sources": [
            collection_source_dict(source)
            for source in sorted(target.sources, key=lambda value: (not value.is_active, value.id))
        ],
        "opportunities": _opportunity_references(db, target),
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


def list_collection_targets(
    db: Session,
    *,
    query: str | None = None,
    industry: str | None = None,
    sector: str | None = None,
    priority_tier: int | None = None,
    due_only: bool = False,
    include_inactive: bool = False,
    page: int = 1,
    per_page: int = 20,
) -> CollectionTargetList:
    stmt = collection_target_query().join(CollectionTarget.company)
    count_stmt = select(func.count(CollectionTarget.id)).select_from(CollectionTarget).join(CollectionTarget.company)
    filters = []
    if query:
        filters.append(Company.name.ilike(f"%{query.strip()}%"))
    if industry:
        industry_ids = select(Industry.id).where(or_(Industry.name == industry, Industry.slug == industry))
        filters.append(CollectionTarget.industry_id.in_(industry_ids))
    if sector:
        sector_ids = select(Sector.id).where(or_(Sector.name == sector, Sector.slug == sector))
        filters.append(CollectionTarget.sector_id.in_(sector_ids))
    if priority_tier:
        filters.append(CollectionTarget.priority_tier == priority_tier)
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


def _get_or_create_company(db: Session, name: str) -> Company:
    normalized = normalize_company_name(name)
    company = db.scalar(select(Company).where(Company.normalized_name == normalized))
    if company is None:
        company = Company(name=name, normalized_name=normalized)
        db.add(company)
        db.flush()
    return company


def _resolve_classification(
    db: Session, *, industry_value: str, sector_value: str | None
) -> tuple[Industry, Sector | None]:
    industry = resolve_one(db, Industry, industry_value)
    if industry is None:
        raise DomainValidationError([master_error("industry", industry_value, choices(db, Industry))])
    sector = None
    if sector_value is not None:
        sector = resolve_one(db, Sector, sector_value)
        available = list(
            db.scalars(
                select(Sector.name)
                .where(Sector.industry_id == industry.id, Sector.is_active.is_(True))
                .order_by(Sector.sort_order, Sector.id)
            )
        )
        if sector is None or sector.industry_id != industry.id:
            raise DomainValidationError([master_error("sector", sector_value, available)])
    return industry, sector


def create_collection_target(db: Session, payload: CollectionTargetCreateRequest) -> tuple[CollectionTarget, bool]:
    operation = "collection_target_create"
    request_hash = _request_hash(payload)
    replay_id = _replayed_entity_id(db, request_id=payload.request_id, operation=operation, request_hash=request_hash)
    if replay_id is not None:
        target = get_collection_target(db, int(replay_id))
        if target is None:
            raise RuntimeError("collection target idempotency target not found")
        return target, True

    industry, sector = _resolve_classification(db, industry_value=payload.industry, sector_value=payload.sector)
    company = _get_or_create_company(db, payload.company_name)
    existing = db.scalar(
        select(CollectionTarget).where(
            CollectionTarget.company_id == company.id,
            CollectionTarget.industry_id == industry.id,
        )
    )
    if existing is not None:
        raise DomainValidationError(
            [
                {
                    "field": "企業名・業界",
                    "received": f"{company.name} / {industry.name}",
                    "reason": "同じ企業と業界の収集対象が既に存在します",
                    "expected": "未登録の企業と業界の組み合わせ",
                    "example": None,
                    "alternative": f"target_id={existing.id}をupdate_collection_targetで更新してください",
                }
            ]
        )

    target = CollectionTarget(
        company=company,
        industry=industry,
        sector=sector,
        priority_tier=payload.priority_tier,
        check_interval_days=payload.check_interval_days,
        selection_reason=payload.selection_reason,
    )
    target.sources = [CollectionSource(source_type=source.source_type, url=source.url) for source in payload.sources]
    db.add(target)
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
        company = _get_or_create_company(db, payload.company_name)
    industry_value = payload.industry if "industry" in fields else target.industry.name
    if industry_value is None:
        raise DomainValidationError([{"field": "業界", "received": None, "reason": "nullにはできません"}])
    sector_value = payload.sector if "sector" in fields else (target.sector.name if target.sector else None)
    industry, sector = _resolve_classification(db, industry_value=industry_value, sector_value=sector_value)
    collision = db.scalar(
        select(CollectionTarget).where(
            CollectionTarget.company_id == company.id,
            CollectionTarget.industry_id == industry.id,
            CollectionTarget.id != target.id,
        )
    )
    if collision is not None:
        raise DomainValidationError(
            [
                {
                    "field": "企業名・業界",
                    "received": f"{company.name} / {industry.name}",
                    "reason": "同じ収集対象が既に存在します",
                }
            ]
        )
    target.company = company
    target.industry = industry
    target.sector = sector
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
        if opportunity.company_id != target.company_id or opportunity.industry_id != target.industry_id:
            raise DomainValidationError(
                [
                    {
                        "field": "opportunity_id",
                        "received": payload.opportunity_id,
                        "reason": "収集対象の企業・業界と一致しません",
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
    if payload.source_url:
        for source in target.sources:
            if source.url == payload.source_url:
                source.last_checked_at = now
                break
    db.flush()
    check_after = collection_check_dict(check)
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
