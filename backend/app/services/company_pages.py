"""Read models for the public company pages.

Lives apart from ``services/companies.py`` because it needs both the opportunity query helpers and
the company classification serializer, and ``opportunities.py`` already imports ``companies.py``.
Nothing here writes: the profile itself is written through ``companies.update_company_profile``.
"""

import math
from dataclasses import dataclass
from datetime import date, datetime
from typing import Any

from sqlalchemy import and_, case, func, or_, select
from sqlalchemy.orm import Session, selectinload
from sqlalchemy.sql.elements import ColumnElement

from app.models import Company, CompanyIndustry, Opportunity, RecruitmentStatus
from app.services.company_industries import company_industry_dict
from app.services.opportunities import RECONFIRMABLE_RECRUITMENT_STATUSES, opportunity_query
from app.services.serialization import company_business_areas, opportunity_dict, public_company_url

#: A company page lists at most this many finished postings. They are context, not the point of the
#: page, and an old company would otherwise push its current openings off the screen.
PAST_OPPORTUNITY_LIMIT = 12


@dataclass
class CompanyPage:
    company: Company
    current: list[Opportunity]
    past: list[Opportunity]


@dataclass
class CompanySummary:
    company: Company
    current_opportunity_count: int
    openings_updated_at: datetime | None


@dataclass
class CompanySummaryList:
    items: list[CompanySummary]
    total: int
    page: int
    per_page: int

    @property
    def total_pages(self) -> int:
        return max(1, math.ceil(self.total / self.per_page))


def current_opening_filter(today: date) -> ColumnElement[bool]:
    """A posting a visitor can still act on: live status, and a deadline that has not passed."""
    return and_(
        Opportunity.deleted_at.is_(None),
        Opportunity.status_id.in_(
            select(RecruitmentStatus.id).where(RecruitmentStatus.name.in_(RECONFIRMABLE_RECRUITMENT_STATUSES))
        ),
        or_(Opportunity.deadline.is_(None), Opportunity.deadline >= today),
    )


def company_opportunities(
    db: Session, company_id: int, *, today: date, current: bool, limit: int | None = None
) -> list[Opportunity]:
    """Openings for one company, split into what is still open and what has finished.

    The split is by ``company_id`` rather than by name: on a company page the company is already
    resolved, so alias matching would only risk pulling in a different row.
    """
    stmt = opportunity_query().where(Opportunity.company_id == company_id)
    if current:
        stmt = stmt.where(current_opening_filter(today)).order_by(
            # An undated posting sorts after every dated one. nulls_last() is avoided because the
            # SQLite used by the tests does not accept NULLS LAST.
            case((Opportunity.deadline.is_(None), 1), else_=0),
            Opportunity.deadline.asc(),
            Opportunity.updated_at.desc(),
        )
    else:
        stmt = stmt.where(~current_opening_filter(today)).order_by(Opportunity.updated_at.desc())
    if limit is not None:
        stmt = stmt.limit(limit)
    return list(db.scalars(stmt).unique())


def _openings_aggregate(today: date) -> Any:
    """Current-opening count and newest update per company, as one grouped subquery.

    Joining this is what keeps a listing page to a fixed number of queries instead of one per
    company, and the join itself expresses "has at least one current opening".
    """
    return (
        select(
            Opportunity.company_id.label("company_id"),
            func.count(Opportunity.id).label("current_count"),
            func.max(Opportunity.updated_at).label("openings_updated_at"),
        )
        .where(current_opening_filter(today))
        .group_by(Opportunity.company_id)
        .subquery()
    )


def _profile_is_complete() -> ColumnElement[bool]:
    """A page worth sending a search engine to has both a lead and a body.

    The minimum lengths are enforced when the profile is written, so presence is enough here. The
    frontend applies the same two-part rule for robots, keeping the sitemap and the pages in step.
    """
    return and_(
        Company.business_summary.is_not(None),
        func.length(func.trim(Company.business_summary)) > 0,
        Company.description.is_not(None),
        func.length(func.trim(Company.description)) > 0,
    )


def get_company_page(db: Session, company: Company, *, today: date) -> CompanyPage:
    return CompanyPage(
        company=company,
        current=company_opportunities(db, company.id, today=today, current=True),
        past=company_opportunities(db, company.id, today=today, current=False, limit=PAST_OPPORTUNITY_LIMIT),
    )


def list_indexable_companies(db: Session, *, today: date, page: int = 1, per_page: int = 20) -> CompanySummaryList:
    """Companies whose page carries its own content: a full profile plus at least one open posting.

    This is the same condition the frontend uses to decide indexability, so a sitemap built from
    this list and the pages themselves cannot disagree.
    """
    openings = _openings_aggregate(today)
    condition = _profile_is_complete()
    stmt = (
        select(Company, openings.c.current_count, openings.c.openings_updated_at)
        .join(openings, openings.c.company_id == Company.id)
        .options(
            selectinload(Company.industries).selectinload(CompanyIndustry.industry),
            selectinload(Company.industries).selectinload(CompanyIndustry.sector),
        )
        .where(condition)
        .order_by(Company.name, Company.id)
        .offset((page - 1) * per_page)
        .limit(per_page)
    )
    count_stmt = select(func.count()).select_from(
        select(Company.id).join(openings, openings.c.company_id == Company.id).where(condition).subquery()
    )
    rows = db.execute(stmt).all()
    return CompanySummaryList(
        items=[
            CompanySummary(company=row[0], current_opportunity_count=int(row[1]), openings_updated_at=row[2])
            for row in rows
        ],
        total=int(db.scalar(count_stmt) or 0),
        page=page,
        per_page=per_page,
    )


def company_summary_dict(
    company: Company, *, current_opportunity_count: int, openings_updated_at: datetime | None
) -> dict[str, Any]:
    return {
        "id": company.id,
        "public_code": company.public_code,
        "url": public_company_url(company.public_code),
        "name": company.name,
        "business_summary": company.business_summary,
        "description": company.description,
        "business_areas": company_business_areas(company),
        "website_url": company.website_url,
        "industries": [
            company_industry_dict(row)
            for row in sorted(company.industries, key=lambda item: (not item.is_primary, item.id))
        ],
        "current_opportunity_count": current_opportunity_count,
        "openings_updated_at": openings_updated_at,
        "created_at": company.created_at,
        "updated_at": company.updated_at,
    }


def company_detail_dict(page: CompanyPage) -> dict[str, Any]:
    openings_updated_at = max(
        (item.updated_at for item in page.current if item.updated_at is not None), default=None
    )
    return company_summary_dict(
        page.company,
        current_opportunity_count=len(page.current),
        openings_updated_at=openings_updated_at,
    ) | {
        "current_opportunities": [opportunity_dict(item) for item in page.current],
        "past_opportunities": [opportunity_dict(item) for item in page.past],
    }
