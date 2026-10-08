from typing import Annotated, Literal

from fastapi import APIRouter, HTTPException, Query

from app.dates import today_in_tokyo
from app.db import DbSession
from app.schemas import OpportunityListResponse, OpportunityResponse
from app.services.opportunities import (
    find_similar_opportunities,
    get_opportunity_by_public_ref,
    search_opportunities,
)
from app.services.serialization import opportunity_dict

router = APIRouter(prefix="/opportunities", tags=["opportunities"])


@router.get("", response_model=OpportunityListResponse)
def list_opportunities(
    db: DbSession,
    q: str | None = Query(default=None, max_length=100),
    status: Annotated[list[str] | None, Query()] = None,
    industry: Annotated[list[str] | None, Query()] = None,
    sector: Annotated[list[str] | None, Query()] = None,
    event_type: Annotated[list[str] | None, Query()] = None,
    event_format: Annotated[list[str] | None, Query()] = None,
    job_category: Annotated[list[str] | None, Query()] = None,
    graduation_year: Annotated[list[str] | None, Query()] = None,
    degree: Annotated[list[str] | None, Query()] = None,
    sort: Literal["relevance", "deadline", "updated", "created"] | None = None,
    page: int = Query(default=1, ge=1),
    per_page: int = Query(default=20, ge=1, le=100),
) -> dict[str, object]:
    result = search_opportunities(
        db,
        q=q,
        status=status,
        industry=industry,
        sector=sector,
        event_type=event_type,
        event_format=event_format,
        job_category=job_category,
        graduation_year=graduation_year,
        degree=degree,
        deadline_on_or_after=today_in_tokyo(),
        sort=sort,
        page=page,
        per_page=per_page,
    )
    return {
        "items": [opportunity_dict(item) for item in result.items],
        "total": result.total,
        "page": result.page,
        "per_page": result.per_page,
        "total_pages": result.total_pages,
    }


@router.get("/{opportunity_id}", response_model=OpportunityResponse)
def opportunity_detail(opportunity_id: str, db: DbSession) -> dict[str, object]:
    item = get_opportunity_by_public_ref(db, opportunity_id)
    if item is None:
        raise HTTPException(status_code=404, detail="募集情報が見つかりません")
    return opportunity_dict(item)


@router.get("/{opportunity_id}/same-company", response_model=list[OpportunityResponse])
def same_company_opportunities(
    opportunity_id: str,
    db: DbSession,
) -> list[dict[str, object]]:
    item = get_opportunity_by_public_ref(db, opportunity_id)
    if item is None:
        raise HTTPException(status_code=404, detail="募集情報が見つかりません")

    matches = find_similar_opportunities(
        db,
        company_name=item.company.name,
        exclude_id=item.id,
        recruitment_statuses=["募集予定", "募集中", "通年募集"],
        deadline_on_or_after=today_in_tokyo(),
        limit=3,
    )
    return [opportunity_dict(match) for match in matches]
