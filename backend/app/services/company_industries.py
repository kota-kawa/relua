"""Company-level industry/sector classification, shared by collection and opportunity writes."""

from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Company, CompanyIndustry, Industry, Sector
from app.services.serialization import master_dict


def company_industries(db: Session, company_id: int) -> list[CompanyIndustry]:
    """Classifications for one company, primary first, then oldest first."""

    return list(
        db.scalars(
            select(CompanyIndustry)
            .where(CompanyIndustry.company_id == company_id)
            .order_by(CompanyIndustry.is_primary.desc(), CompanyIndustry.id)
        )
    )


def company_industry_dict(row: CompanyIndustry) -> dict[str, Any]:
    return {
        "industry": master_dict(row.industry),
        "sector": master_dict(row.sector) if row.sector else None,
        "is_primary": row.is_primary,
    }


def primary_company_industry(rows: list[CompanyIndustry]) -> CompanyIndustry | None:
    """The row to show when a company must be presented under a single industry.

    Falls back to the first classification so a company is never rendered as unclassified merely
    because no row was ever flagged - rows written before is_primary existed have none.
    """
    return next((row for row in rows if row.is_primary), rows[0] if rows else None)


def ensure_company_industry(
    db: Session, *, company: Company, industry: Industry, sector: Sector | None
) -> CompanyIndustry:
    """Record that a company belongs to an industry, without disturbing what is already known.

    Called on every opportunity write, so classification grows from the postings themselves instead
    of depending on someone maintaining it by hand: a posting filed under 医療・製薬 teaches the
    company that industry even if it was only ever registered as IT・通信. An existing row keeps its
    sector unless it had none, since a hand-picked sector outranks whatever one posting happened to
    carry, and the first classification a company gets becomes its primary one.
    """
    existing = db.scalar(
        select(CompanyIndustry).where(
            CompanyIndustry.company_id == company.id,
            CompanyIndustry.industry_id == industry.id,
        )
    )
    if existing is not None:
        if existing.sector_id is None and sector is not None:
            existing.sector = sector
        return existing
    has_primary = db.scalar(
        select(CompanyIndustry.id).where(
            CompanyIndustry.company_id == company.id,
            CompanyIndustry.is_primary.is_(True),
        )
    )
    row = CompanyIndustry(
        company_id=company.id,
        industry=industry,
        sector=sector,
        is_primary=has_primary is None,
    )
    db.add(row)
    db.flush()
    return row


def set_company_industries(
    db: Session, *, company: Company, classifications: list[tuple[Industry, Sector | None]]
) -> list[CompanyIndustry]:
    """Replace a company's classifications wholesale; the first entry becomes the primary one.

    Rows absent from `classifications` are dropped, so this is the operation for correcting a
    misclassification, where ensure_company_industry can only ever add.
    """
    wanted = {industry.id: sector for industry, sector in classifications}
    primary_industry_id = classifications[0][0].id if classifications else None
    existing = {row.industry_id: row for row in company_industries(db, company.id)}

    # Clearing every flag in its own flush keeps the "at most one primary per company" partial
    # unique index satisfied at all times - the ORM does not order the two UPDATEs for us.
    for row in existing.values():
        row.is_primary = False
    db.flush()

    for industry_id, row in existing.items():
        if industry_id not in wanted:
            db.delete(row)
    for industry, sector in classifications:
        row = existing.get(industry.id)
        if row is None:
            row = CompanyIndustry(company_id=company.id, industry=industry)
            db.add(row)
        row.sector = sector
        row.is_primary = industry.id == primary_industry_id
    db.flush()
    return company_industries(db, company.id)

