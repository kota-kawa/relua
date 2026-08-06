from app.config import get_settings
from app.models import Opportunity

#: Length of the excerpt search results carry instead of the whole description.
#: Long enough to judge relevance, short enough that a 20-item page stays cheap to read.
EXCERPT_LENGTH = 120


def master_dict(item: object) -> dict[str, object]:
    return {"id": item.id, "slug": item.slug, "name": item.name}


def public_detail_url(public_code: str) -> str:
    """Public page for a record, so an MCP client can cite the entry instead of only naming it."""
    return f"{get_settings().site_origin}/opportunities/{public_code}"


def detail_url(item: Opportunity) -> str:
    return public_detail_url(item.public_code)


def _excerpt(value: str) -> str:
    if len(value) <= EXCERPT_LENGTH:
        return value
    return value[:EXCERPT_LENGTH] + "…"


def opportunity_dict(item: Opportunity) -> dict[str, object]:
    return {
        "id": item.id,
        "public_code": item.public_code,
        "url": detail_url(item),
        "recruitment_status": master_dict(item.status),
        "company": {"id": item.company.id, "name": item.company.name},
        "industry": master_dict(item.industry),
        "sector": master_dict(item.sector),
        "event_name": item.event_name,
        "deadline": item.deadline,
        "event_type": master_dict(item.event_type),
        "description": item.description,
        "event_format": master_dict(item.event_format),
        "location": item.location,
        "selection_process": item.selection_process,
        "homepage_url": item.homepage_url,
        "job_categories": [master_dict(value) for value in sorted(item.job_categories, key=lambda x: x.sort_order)],
        "tags": [value.name for value in sorted(item.tags, key=lambda x: x.name)],
        "event_start_date": item.event_start_date,
        "event_end_date": item.event_end_date,
        "period_note": item.period_note,
        "requirements": item.requirements,
        "compensation": item.compensation,
        "graduation_years": [master_dict(value) for value in sorted(item.graduation_years, key=lambda x: x.sort_order)],
        "degrees": [master_dict(value) for value in sorted(item.degrees, key=lambda x: x.sort_order)],
        "audience_note": item.audience_note,
        "recruitment_start_date": item.recruitment_start_date,
        "entry_url": item.entry_url,
        "source_url": item.source_url,
        "created_at": item.created_at,
        "updated_at": item.updated_at,
    }


def opportunity_summary(item: Opportunity) -> dict[str, object]:
    """Compact shape for search hits.

    A search page holds 20 records, and free-text fields make a full record large. Callers that need
    the whole entry follow up with get_opportunity, which is the search/fetch split remote clients expect.
    """
    return {
        "id": item.id,
        "public_code": item.public_code,
        "url": detail_url(item),
        "company_name": item.company.name,
        "event_name": item.event_name,
        "recruitment_status": item.status.name,
        "event_type": item.event_type.name,
        "event_format": item.event_format.name,
        "industry": item.industry.name,
        "sector": item.sector.name,
        "deadline": item.deadline,
        "location": item.location,
        "description_excerpt": _excerpt(item.description),
        "job_categories": [value.name for value in sorted(item.job_categories, key=lambda x: x.sort_order)],
        "graduation_years": [value.name for value in sorted(item.graduation_years, key=lambda x: x.sort_order)],
        "degrees": [value.name for value in sorted(item.degrees, key=lambda x: x.sort_order)],
        "tags": [value.name for value in sorted(item.tags, key=lambda x: x.name)],
        "entry_url": item.entry_url,
        "source_url": item.source_url,
        "updated_at": item.updated_at,
    }
