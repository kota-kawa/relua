from app.models import Opportunity


def master_dict(item: object) -> dict[str, object]:
    return {"id": item.id, "slug": item.slug, "name": item.name}


def opportunity_dict(item: Opportunity) -> dict[str, object]:
    return {
        "id": item.id,
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
