import hashlib
import json
from dataclasses import dataclass
from difflib import SequenceMatcher
from typing import Any, Literal

from fastapi.encoders import jsonable_encoder
from sqlalchemy import func, literal, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from sqlalchemy.sql.elements import ColumnElement

from app.models import AuditLog, Company, CompanyAlias, CompanyRequestRecord
from app.services.normalization import normalize_company_name

CompanyMatchType = Literal["canonical_exact", "alias_exact", "partial", "fuzzy"]
COMPANY_FUZZY_THRESHOLD = 0.3


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


def company_identity_dict(company: Company) -> dict[str, Any]:
    return {
        "id": company.id,
        "canonical_name": company.name,
        "normalized_name": company.normalized_name,
        "aliases": [
            {"id": alias.id, "alias": alias.alias, "normalized_alias": alias.normalized_alias}
            for alias in sorted(company.aliases, key=lambda item: (item.normalized_alias, item.id))
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


def get_or_create_company(db: Session, name: str) -> Company:
    company = find_company(db, name)
    if company is not None:
        return company
    normalized = normalize_company_name(name)
    company = Company(name=name, normalized_name=normalized)
    db.add(company)
    db.flush()
    return company


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

    normalized_term = f"%{normalized}%"
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
                        Company.normalized_name.ilike(normalized_term),
                        Company.normalized_name.op("%")(literal(normalized)),
                        Company.aliases.any(CompanyAlias.normalized_alias.ilike(normalized_term)),
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
        "reason": "同じrequest_idが異なる企業名操作で使用されています",
        "expected": "操作ごとに一意なrequest_id",
        "alternative": "新しいrequest_idを発行してください",
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
) -> None:
    db.add(
        AuditLog(
            action=action,
            entity_type="company",
            entity_id=str(company.id),
            request_id=request_id,
            client_name=client_name,
            source_url=None,
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


def company_name_filter(company_name: str) -> ColumnElement[bool]:
    """Match Company rows whose normalized name or any alias equals the given name."""
    normalized = normalize_company_name(company_name)
    return or_(
        Company.normalized_name == normalized,
        Company.id.in_(select(CompanyAlias.company_id).where(CompanyAlias.normalized_alias == normalized)),
    )


def company_keyword_filter(db: Session, query: str) -> ColumnElement[bool]:
    """Match Company rows by substring and, on PostgreSQL, typo-tolerant trigram similarity."""
    term = f"%{query}%"
    normalized_query = normalize_company_name(query)
    normalized_term = f"%{normalized_query}%"
    matches: list[ColumnElement[bool]] = [
        Company.name.ilike(term),
        Company.normalized_name.ilike(normalized_term),
        Company.aliases.any(CompanyAlias.alias.ilike(term)),
        Company.aliases.any(CompanyAlias.normalized_alias.ilike(normalized_term)),
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
