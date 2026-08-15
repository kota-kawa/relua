from sqlalchemy import or_, select
from sqlalchemy.orm import Session
from sqlalchemy.sql.elements import ColumnElement

from app.models import Company, CompanyAlias
from app.services.normalization import normalize_company_name


def find_company(db: Session, name: str) -> Company | None:
    """Resolve a company by its own (normalized) name or by a registered alias.

    Aliases absorb spelling variants normalization cannot collapse on its own, such as
    "DeNA" and "ディーエヌエー" both resolving to 株式会社ディー・エヌ・エー.
    """
    normalized = normalize_company_name(name)
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


def company_name_filter(company_name: str) -> ColumnElement[bool]:
    """Match Company rows whose normalized name or any alias equals the given name.

    Used where a caller supplies one exact company name (duplicate detection, collection-target
    linkage) and every row referring to that company - under any known spelling - must match.
    """
    normalized = normalize_company_name(company_name)
    return or_(
        Company.normalized_name == normalized,
        Company.id.in_(select(CompanyAlias.company_id).where(CompanyAlias.normalized_alias == normalized)),
    )


def company_keyword_filter(query: str) -> ColumnElement[bool]:
    """Match Company rows whose name or any alias contains the given free-text query.

    Matching also happens on normalized text so a query like "ディーエヌエー" finds a stored name
    like "株式会社ディー・エヌ・エー" - the literal ilike above only catches identical spelling.
    """
    term = f"%{query}%"
    normalized_term = f"%{normalize_company_name(query)}%"
    return or_(
        Company.name.ilike(term),
        Company.normalized_name.ilike(normalized_term),
        Company.aliases.any(CompanyAlias.alias.ilike(term)),
        Company.aliases.any(CompanyAlias.normalized_alias.ilike(normalized_term)),
    )
